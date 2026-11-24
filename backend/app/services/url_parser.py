"""Recognise a supported marketplace product URL and extract its product identifier.

Pure parsing: this module never makes a network request. Only exact, allow-listed hosts
are accepted, and the canonical URL is rebuilt from the extracted parts, so tracking
parameters and anything else in the pasted URL are dropped.

The path patterns reflect the public URL formats these sites use today. They will be
re-checked against real responses once each marketplace's authorized adapter is live.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, urlsplit

from app.models.enums import MarketplaceCode

MAX_URL_LENGTH = 2048


class UrlErrorCode(StrEnum):
    EMPTY = "url_empty"
    TOO_LONG = "url_too_long"
    INVALID = "url_invalid"
    SCHEME = "url_scheme_not_allowed"
    CREDENTIALS = "url_has_credentials"
    PORT = "url_port_not_allowed"
    UNSUPPORTED_SITE = "unsupported_marketplace"
    SHORT_LINK = "short_link_not_supported"
    NOT_A_PRODUCT = "not_a_product_page"


class UrlParseError(ValueError):
    def __init__(self, code: UrlErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedProductUrl:
    marketplace: MarketplaceCode
    external_id: str
    id_type: str  # ASIN, FSN, ...
    canonical_url: str


HOSTS: dict[str, MarketplaceCode] = {
    "amazon.in": MarketplaceCode.AMAZON_IN,
    "www.amazon.in": MarketplaceCode.AMAZON_IN,
    "m.amazon.in": MarketplaceCode.AMAZON_IN,
    "flipkart.com": MarketplaceCode.FLIPKART,
    "www.flipkart.com": MarketplaceCode.FLIPKART,
    "dl.flipkart.com": MarketplaceCode.FLIPKART,
    "blinkit.com": MarketplaceCode.BLINKIT,
    "www.blinkit.com": MarketplaceCode.BLINKIT,
    "zeptonow.com": MarketplaceCode.ZEPTO,
    "www.zeptonow.com": MarketplaceCode.ZEPTO,
    "bigbasket.com": MarketplaceCode.BIGBASKET,
    "www.bigbasket.com": MarketplaceCode.BIGBASKET,
}

# Redirect-only short links. Resolving them needs an outbound request, which arrives
# with the SSRF-safe HTTP client in Phase 3; until then the full link is required.
SHORT_LINK_HOSTS = {"amzn.in", "amzn.to", "a.co"}

NAMES = {
    MarketplaceCode.AMAZON_IN: "Amazon India",
    MarketplaceCode.FLIPKART: "Flipkart",
    MarketplaceCode.BLINKIT: "Blinkit",
    MarketplaceCode.ZEPTO: "Zepto",
    MarketplaceCode.BIGBASKET: "BigBasket",
}

_BARE_SCHEME = re.compile(r"^([a-z][a-z0-9+.-]*):(?!\d)", re.I)
_ASIN = re.compile(r"/(?:dp|gp/product|gp/aw/d|gp/aw/dp)/([A-Z0-9]{10})(?:[/?]|$)", re.I)
_FLIPKART_PID = re.compile(r"^[A-Z0-9]{16}$")
_FLIPKART_ITEM = re.compile(r"^(?:/([a-z0-9-]{1,200}))?/p/(itm[a-z0-9]{6,32})/?$", re.I)
_BIGBASKET = re.compile(r"^/pd/(\d{1,12})(?:/|$)")
_BLINKIT = re.compile(r"^/prn/([a-z0-9-]{0,200})/prid/(\d{1,12})/?$", re.I)
_ZEPTO = re.compile(
    r"^/pn/([a-z0-9-]{0,200})/pvid/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.I,
)


def _not_product(name: str) -> UrlParseError:
    return UrlParseError(
        UrlErrorCode.NOT_A_PRODUCT,
        f"This {name} link doesn't point to a single product page. "
        "Open the product itself and copy its link.",
    )


def parse_product_url(raw: str) -> ParsedProductUrl:
    text = (raw or "").strip()
    if not text:
        raise UrlParseError(UrlErrorCode.EMPTY, "Paste a product link.")
    if len(text) > MAX_URL_LENGTH:
        raise UrlParseError(UrlErrorCode.TOO_LONG, "That link is too long.")
    if any(c.isspace() or ord(c) < 0x20 for c in text):
        raise UrlParseError(UrlErrorCode.INVALID, "That doesn't look like a valid link.")
    if "://" not in text:
        # "javascript:...", "data:...", "mailto:..." -- a scheme, not a bare host.
        scheme = _BARE_SCHEME.match(text)
        if scheme and "." not in scheme.group(1):
            raise UrlParseError(UrlErrorCode.SCHEME, "Only http(s) links are supported.")
        text = "https://" + text  # people often paste "www.amazon.in/dp/..."

    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise UrlParseError(UrlErrorCode.INVALID, "That doesn't look like a valid link.") from None
    if parts.scheme.lower() not in ("http", "https"):
        raise UrlParseError(UrlErrorCode.SCHEME, "Only http(s) links are supported.")
    if parts.username is not None or parts.password is not None:
        raise UrlParseError(
            UrlErrorCode.CREDENTIALS, "Links with a username or password are not allowed."
        )
    if port is not None and port not in (80, 443):
        raise UrlParseError(UrlErrorCode.PORT, "Links with a custom port are not supported.")

    host = (parts.hostname or "").rstrip(".").lower()
    if not host or not host.isascii():
        raise UrlParseError(UrlErrorCode.INVALID, "That doesn't look like a valid link.")
    if host in SHORT_LINK_HOSTS:
        raise UrlParseError(
            UrlErrorCode.SHORT_LINK,
            "Short links aren't supported yet. Open the link and paste the full product URL.",
        )
    marketplace = HOSTS.get(host)
    if marketplace is None:
        raise UrlParseError(
            UrlErrorCode.UNSUPPORTED_SITE,
            "Paste a link from Amazon India, Flipkart, Blinkit, Zepto or BigBasket.",
        )

    path = parts.path or "/"
    name = NAMES[marketplace]

    if marketplace is MarketplaceCode.AMAZON_IN:
        m = _ASIN.search(path)
        if not m:
            raise _not_product(name)
        asin = m.group(1).upper()
        return ParsedProductUrl(marketplace, asin, "ASIN", f"https://www.amazon.in/dp/{asin}")

    if marketplace is MarketplaceCode.FLIPKART:
        item = _FLIPKART_ITEM.match(path)
        pid = (parse_qs(parts.query).get("pid") or [""])[0].upper()
        if not item:
            raise _not_product(name)
        slug = f"/{item.group(1).lower()}" if item.group(1) else ""
        item_id = item.group(2).lower()
        base = f"https://www.flipkart.com{slug}/p/{item_id}"
        if _FLIPKART_PID.fullmatch(pid):
            return ParsedProductUrl(marketplace, pid, "FSN", f"{base}?pid={pid}")
        return ParsedProductUrl(marketplace, item_id, "FLIPKART_ITEM", base)

    if marketplace is MarketplaceCode.BIGBASKET:
        m = _BIGBASKET.match(path)
        if not m:
            raise _not_product(name)
        pid = m.group(1)
        return ParsedProductUrl(
            marketplace, pid, "BIGBASKET_ID", f"https://www.bigbasket.com/pd/{pid}/"
        )

    if marketplace is MarketplaceCode.BLINKIT:
        m = _BLINKIT.match(path)
        if not m:
            raise _not_product(name)
        slug, prid = m.group(1).lower() or "product", m.group(2)
        return ParsedProductUrl(
            marketplace, prid, "BLINKIT_PRID", f"https://blinkit.com/prn/{slug}/prid/{prid}"
        )

    m = _ZEPTO.match(path)  # MarketplaceCode.ZEPTO
    if not m:
        raise _not_product(name)
    slug, pvid = m.group(1).lower() or "product", m.group(2).lower()
    return ParsedProductUrl(
        marketplace, pvid, "ZEPTO_PVID", f"https://www.zeptonow.com/pn/{slug}/pvid/{pvid}"
    )
