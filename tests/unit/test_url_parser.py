import pytest

from app.models.enums import MarketplaceCode as M
from app.services.url_parser import UrlErrorCode as E
from app.services.url_parser import UrlParseError, parse_product_url

ZEPTO_ID = "3f2c1a9e-8b7d-4c6e-9a1b-2d3e4f5a6b7c"
AMZ = "https://www.amazon.in/dp/B07JGFGW3V"


@pytest.mark.parametrize(
    ("url", "marketplace", "external_id", "canonical"),
    [
        # Amazon: tracking params, slugs, mobile host and ASIN casing are normalised away
        (
            "https://www.amazon.in/Tata-Salt-1kg/dp/B07JGFGW3V/ref=sr_1_3?tag=x&th=1",
            M.AMAZON_IN,
            "B07JGFGW3V",
            AMZ,
        ),
        ("amazon.in/dp/b07jgfgw3v", M.AMAZON_IN, "B07JGFGW3V", AMZ),
        ("http://m.amazon.in/gp/product/B07JGFGW3V", M.AMAZON_IN, "B07JGFGW3V", AMZ),
        ("https://www.amazon.in/gp/aw/d/B07JGFGW3V?psc=1", M.AMAZON_IN, "B07JGFGW3V", AMZ),
        ("https://WWW.AMAZON.IN./dp/B07JGFGW3V", M.AMAZON_IN, "B07JGFGW3V", AMZ),
        # Flipkart: FSN from pid; slug kept; other params dropped
        (
            "https://www.flipkart.com/tata-salt-1-kg/p/itm4d5e6f7a8b9c0"
            "?pid=SALFYZ8HZZQGZ9YK&lid=abc&marketplace=FLIPKART",
            M.FLIPKART,
            "SALFYZ8HZZQGZ9YK",
            "https://www.flipkart.com/tata-salt-1-kg/p/itm4d5e6f7a8b9c0?pid=SALFYZ8HZZQGZ9YK",
        ),
        (
            "https://www.flipkart.com/tata-salt-1-kg/p/itm4d5e6f7a8b9c0",
            M.FLIPKART,
            "itm4d5e6f7a8b9c0",
            "https://www.flipkart.com/tata-salt-1-kg/p/itm4d5e6f7a8b9c0",
        ),
        # BigBasket / Blinkit / Zepto
        (
            "https://www.bigbasket.com/pd/241600/tata-salt-1-kg/?nc=x",
            M.BIGBASKET,
            "241600",
            "https://www.bigbasket.com/pd/241600/",
        ),
        (
            "https://blinkit.com/prn/tata-salt/prid/10372",
            M.BLINKIT,
            "10372",
            "https://blinkit.com/prn/tata-salt/prid/10372",
        ),
        (
            f"https://www.zeptonow.com/pn/tata-salt/pvid/{ZEPTO_ID.upper()}",
            M.ZEPTO,
            ZEPTO_ID,
            f"https://www.zeptonow.com/pn/tata-salt/pvid/{ZEPTO_ID}",
        ),
    ],
)
def test_recognises_product_links(
    url: str, marketplace: M, external_id: str, canonical: str
) -> None:
    parsed = parse_product_url(url)
    assert parsed.marketplace is marketplace
    assert parsed.external_id == external_id
    assert parsed.canonical_url == canonical


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("", E.EMPTY),
        ("   ", E.EMPTY),
        ("https://www.amazon.in/dp/" + "A" * 3000, E.TOO_LONG),
        ("https://www.amazon.in/dp/B07JGF GW3V", E.INVALID),
        ("https://www.amazon.in/dp/B07\nJGFGW3V", E.INVALID),
        ("javascript:alert(1)//www.amazon.in/dp/B07JGFGW3V", E.SCHEME),
        ("ftp://www.amazon.in/dp/B07JGFGW3V", E.SCHEME),
        ("file:///etc/passwd", E.SCHEME),
        ("https://user:pw@www.amazon.in/dp/B07JGFGW3V", E.CREDENTIALS),
        ("https://www.amazon.in:8443/dp/B07JGFGW3V", E.PORT),
        ("https://www.amazon.in:99999/dp/B07JGFGW3V", E.INVALID),
        # look-alike and internal hosts never pass the exact allowlist
        ("https://amazon.in.evil.example/dp/B07JGFGW3V", E.UNSUPPORTED_SITE),
        ("https://evilamazon.in/dp/B07JGFGW3V", E.UNSUPPORTED_SITE),
        ("https://www.amazon.com/dp/B07JGFGW3V", E.UNSUPPORTED_SITE),
        ("http://localhost/dp/B07JGFGW3V", E.UNSUPPORTED_SITE),
        ("http://127.0.0.1/dp/B07JGFGW3V", E.UNSUPPORTED_SITE),
        ("http://169.254.169.254/latest/meta-data", E.UNSUPPORTED_SITE),
        ("https://" + chr(0x430) + "mazon.in/dp/B07JGFGW3V", E.INVALID),  # Cyrillic look-alike
        # short links need a network request (Phase 3)
        ("https://amzn.in/d/abc123", E.SHORT_LINK),
        ("https://amzn.to/3xyz", E.SHORT_LINK),
        # right site, not a single product
        ("https://www.amazon.in/s?k=salt", E.NOT_A_PRODUCT),
        ("https://www.amazon.in/dp/B07JGF", E.NOT_A_PRODUCT),
        ("https://www.flipkart.com/search?q=salt", E.NOT_A_PRODUCT),
        ("https://www.bigbasket.com/pc/foodgrains/", E.NOT_A_PRODUCT),
        ("https://blinkit.com/cn/salt/cid/1/2", E.NOT_A_PRODUCT),
        ("https://www.zeptonow.com/pn/salt/pvid/not-a-uuid", E.NOT_A_PRODUCT),
    ],
)
def test_rejects_with_specific_reason(url: str, code: E) -> None:
    with pytest.raises(UrlParseError) as exc:
        parse_product_url(url)
    assert exc.value.code is code
    assert exc.value.message  # always a human-readable explanation
