"""Short links through the lookup API, with the network faked."""

import httpx
from fastapi.testclient import TestClient

from app.api.v1.lookup import get_link_resolver, get_pincode_directory
from app.core.config import Environment, Settings
from app.main import create_app
from app.services.pincode import PincodeDirectory
from app.services.safe_http import SafeRedirectResolver
from app.services.url_parser import all_link_hosts

PUBLIC = "52.95.120.1"


def _client(
    routes: dict[tuple[str, str], httpx.Response], dns: dict[str, list[str]] | None = None
) -> tuple[TestClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return routes.get(
            (request.headers["host"], request.url.raw_path.decode()), httpx.Response(404)
        )

    resolver = SafeRedirectResolver(
        all_link_hosts(),
        resolver=lambda h: (dns or {}).get(h, [PUBLIC]),
        transport=httpx.MockTransport(handler),
    )
    app = create_app(Settings(env=Environment.TEST, log_level="WARNING"))
    app.dependency_overrides[get_link_resolver] = lambda: resolver
    app.dependency_overrides[get_pincode_directory] = lambda: PincodeDirectory()
    return TestClient(app), seen


def _post(client: TestClient, url: str) -> httpx.Response:
    return client.post("/api/v1/lookups/validate", json={"url": url, "pincode": "560001"})


def test_amazon_short_link_resolves_without_fetching_product_page() -> None:
    client, seen = _client(
        {
            ("amzn.in", "/d/7xYz"): httpx.Response(
                301,
                headers={"Location": "https://www.amazon.in/Tata-Salt/dp/B07JGFGW3V?ref_=x"},
            )
        }
    )
    r = _post(client, "amzn.in/d/7xYz")
    assert r.status_code == 200
    product = r.json()["product"]
    assert product["external_id"] == "B07JGFGW3V"
    assert product["canonical_url"] == "https://www.amazon.in/dp/B07JGFGW3V"
    assert product["resolved_from"] == "https://amzn.in/d/7xYz"
    assert [q.headers["host"] for q in seen] == ["amzn.in"]


def test_flipkart_share_short_link() -> None:
    client, _ = _client(
        {
            ("dl.flipkart.com", "/s/AbC123"): httpx.Response(
                302,
                headers={
                    "Location": "https://www.flipkart.com/tata-salt/p/itm4d5e6f7a8b9c0"
                    "?pid=SALFYZ8HZZQGZ9YK&affid=x"
                },
            )
        }
    )
    r = _post(client, "https://dl.flipkart.com/s/AbC123")
    assert r.status_code == 200
    assert r.json()["product"]["external_id"] == "SALFYZ8HZZQGZ9YK"


def test_full_links_make_no_network_request() -> None:
    client, seen = _client({})
    assert _post(client, "https://www.amazon.in/dp/B07JGFGW3V").status_code == 200
    assert seen == []


def test_short_link_to_non_marketplace_is_refused() -> None:
    client, _ = _client(
        {("amzn.to", "/x"): httpx.Response(301, headers={"Location": "http://169.254.169.254/"})}
    )
    r = _post(client, "https://amzn.to/x")
    assert r.status_code == 422
    assert r.json()["error"]["details"]["fields"][0]["code"] == "short_link_unsafe"


def test_short_link_resolving_to_private_ip_is_refused() -> None:
    client, seen = _client({}, dns={"amzn.in": ["10.1.2.3"]})
    r = _post(client, "https://amzn.in/d/x")
    assert r.status_code == 422
    assert r.json()["error"]["details"]["fields"][0]["code"] == "short_link_unsafe"
    assert seen == []


def test_dead_short_link_explains_what_to_do() -> None:
    client, _ = _client({})  # every request -> 404
    r = _post(client, "https://amzn.in/d/gone")
    assert r.status_code == 422
    field = r.json()["error"]["details"]["fields"][0]
    assert field["code"] == "short_link_failed"
    assert "paste the full product link" in field["message"]


def test_short_link_to_non_product_page() -> None:
    client, _ = _client(
        {
            ("amzn.in", "/d/s"): httpx.Response(
                301, headers={"Location": "https://www.amazon.in/s?k=salt"}
            ),
            ("www.amazon.in", "/s?k=salt"): httpx.Response(200),
        }
    )
    r = _post(client, "https://amzn.in/d/s")
    assert r.status_code == 422
    assert r.json()["error"]["details"]["fields"][0]["code"] == "not_a_product_page"
