"""SSRF protection for short-link resolution. No real network: DNS and HTTP are faked."""

from collections.abc import Callable

import httpx
import pytest

from app.services.safe_http import (
    ResolveError,
    SafeRedirectResolver,
    UnsafeUrlError,
    is_public_ip,
)

PUBLIC = "52.95.120.1"
ALLOWED = {"amzn.in", "www.amazon.in", "amazon.in"}
Route = dict[tuple[str, str], httpx.Response]


def redirect(location: str, status: int = 301) -> httpx.Response:
    return httpx.Response(status, headers={"Location": location})


def make(
    routes: Route,
    dns: dict[str, list[str]] | None = None,
    seen: list[httpx.Request] | None = None,
    **kwargs: object,
) -> SafeRedirectResolver:
    dns = dns or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        key = (request.headers["host"], request.url.raw_path.decode())
        if key not in routes:
            return httpx.Response(404)
        return routes[key]

    def resolver(host: str) -> list[str]:
        return dns.get(host, [PUBLIC])

    return SafeRedirectResolver(
        ALLOWED,
        resolver=resolver,
        transport=httpx.MockTransport(handler),
        **kwargs,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ address checks


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "127.8.8.8", "10.0.0.5", "172.16.0.1", "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # noqa: S104 - a test input, nothing binds to it
        "255.255.255.255", "224.0.0.1",
        "::1", "fe80::1", "fc00::1", "fd00:ec2::254",  # AWS IPv6 metadata
        "::ffff:127.0.0.1", "::ffff:169.254.169.254",  # IPv4-mapped
        "2002:7f00:1::",  # 6to4 wrapping 127.0.0.1
        "not-an-ip",
    ],
)  # fmt: skip
def test_non_public_addresses_rejected(address: str) -> None:
    assert not is_public_ip(address)


@pytest.mark.parametrize("address", ["52.95.120.1", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_allowed(address: str) -> None:
    assert is_public_ip(address)


# ------------------------------------------------------------------ resolution


def test_follows_redirects_to_product_and_pins_ip_with_sni() -> None:
    seen: list[httpx.Request] = []
    r = make(
        {
            ("amzn.in", "/d/abc"): redirect("https://www.amazon.in/gp/r?x=1"),
            ("www.amazon.in", "/gp/r?x=1"): redirect("/dp/B07JGFGW3V?ref=x", 302),
        },
        seen=seen,
    )
    final, hops = r.resolve("https://amzn.in/d/abc", is_final=lambda u: "/dp/" in u)
    assert final == "https://www.amazon.in/dp/B07JGFGW3V?ref=x"
    assert [h.status for h in hops] == [301, 302]
    # Product page itself was never requested; each hop went to the checked IP.
    assert len(seen) == 2
    for req in seen:
        assert req.url.host == PUBLIC
        assert req.extensions["sni_hostname"] == req.headers["host"]
        assert req.method == "HEAD"
        assert "cookie" not in req.headers


def test_http_location_is_upgraded_to_https() -> None:
    seen: list[httpx.Request] = []
    r = make({("amzn.in", "/d/x"): redirect("http://www.amazon.in/dp/B07JGFGW3V")}, seen=seen)
    final, _ = r.resolve("https://amzn.in/d/x", is_final=lambda u: "/dp/" in u)
    assert final == "https://www.amazon.in/dp/B07JGFGW3V"
    assert [req.headers["host"] for req in seen] == ["amzn.in"]


def test_head_refused_falls_back_to_get_without_reading_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "HEAD":
            return httpx.Response(405)
        return redirect("https://www.amazon.in/dp/B07JGFGW3V")

    r = SafeRedirectResolver(
        ALLOWED, resolver=lambda h: [PUBLIC], transport=httpx.MockTransport(handler)
    )
    final, _ = r.resolve("https://amzn.in/d/x", is_final=lambda u: "/dp/" in u)
    assert final.endswith("/dp/B07JGFGW3V")
    assert [q.method for q in seen] == ["HEAD", "GET"]


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("http://127.0.0.1/admin", "host_not_allowed"),
        ("http://169.254.169.254/latest/meta-data/", "host_not_allowed"),
        ("http://localhost:8000/", "port"),
        ("https://evil.example/", "host_not_allowed"),
        ("https://www.amazon.in.evil.example/dp/x", "host_not_allowed"),
        ("https://user:pw@www.amazon.in/dp/x", "credentials"),
        ("https://www.amazon.in:8443/dp/x", "port"),
        ("file:///etc/passwd", "scheme"),
        ("gopher://www.amazon.in/", "scheme"),
    ],
)
def test_unsafe_redirect_targets_blocked(location: str, reason: str) -> None:
    r = make({("amzn.in", "/d/x"): redirect(location)})
    with pytest.raises(UnsafeUrlError) as exc:
        r.resolve("https://amzn.in/d/x")
    assert exc.value.reason == reason


@pytest.mark.parametrize(
    "addresses",
    [["10.0.0.1"], ["169.254.169.254"], ["::1"], [PUBLIC, "127.0.0.1"]],  # mixed = refused
)
def test_allowed_host_resolving_to_private_address_blocked(addresses: list[str]) -> None:
    """DNS rebinding / poisoned records: an allowlisted name is not enough."""
    r = make(
        {("amzn.in", "/d/x"): redirect("https://www.amazon.in/dp/B07JGFGW3V")},
        dns={"www.amazon.in": addresses},
    )
    with pytest.raises(UnsafeUrlError) as exc:
        r.resolve("https://amzn.in/d/x")
    assert exc.value.reason == "private_address"


def test_first_hop_private_address_blocked_before_any_request() -> None:
    seen: list[httpx.Request] = []
    r = make({}, dns={"amzn.in": ["127.0.0.1"]}, seen=seen)
    with pytest.raises(UnsafeUrlError):
        r.resolve("https://amzn.in/d/x")
    assert seen == []


def test_redirect_loop_stops_after_max_hops() -> None:
    r = make(
        {
            ("amzn.in", "/a"): redirect("https://amzn.in/b"),
            ("amzn.in", "/b"): redirect("https://amzn.in/a"),
        },
        max_hops=4,
    )
    with pytest.raises(ResolveError) as exc:
        r.resolve("https://amzn.in/a")
    assert exc.value.reason == "too_many_redirects"


@pytest.mark.parametrize(
    ("make_error", "reason"),
    [
        (lambda: httpx.ConnectTimeout("slow"), "timeout"),
        (lambda: httpx.ConnectError("refused"), "network"),
    ],
)
def test_network_failures_become_resolve_errors(
    make_error: Callable[[], Exception], reason: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise make_error()

    r = SafeRedirectResolver(
        ALLOWED, resolver=lambda h: [PUBLIC], transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ResolveError) as exc:
        r.resolve("https://amzn.in/d/x")
    assert exc.value.reason == reason


def test_dns_failure_and_error_status() -> None:
    def failing(host: str) -> list[str]:
        raise OSError("nxdomain")

    r = SafeRedirectResolver(
        ALLOWED, resolver=failing, transport=httpx.MockTransport(lambda q: httpx.Response(200))
    )
    with pytest.raises(ResolveError) as exc:
        r.resolve("https://amzn.in/d/x")
    assert exc.value.reason == "dns"

    r2 = make({("amzn.in", "/d/x"): httpx.Response(404)})
    with pytest.raises(ResolveError) as exc2:
        r2.resolve("https://amzn.in/d/x")
    assert exc2.value.reason == "http_status"


def test_redirect_without_location_rejected() -> None:
    r = make({("amzn.in", "/d/x"): httpx.Response(302)})
    with pytest.raises(ResolveError) as exc:
        r.resolve("https://amzn.in/d/x")
    assert exc.value.reason == "no_location"
