"""SSRF-safe redirect resolution for short product links.

The only outbound request PriceScope makes for a user-supplied URL is following a
marketplace short link (e.g. ``amzn.in/d/…``) to the product page it points to. This
module makes that request without letting a URL reach anything internal:

* every hop's host must be on an explicit allowlist (short-link hosts + marketplaces);
* DNS is resolved here, and the hop is refused if *any* address is not public
  (loopback, private, link-local incl. cloud metadata 169.254.169.254, CGNAT, multicast,
  reserved, IPv6 ULA/link-local, IPv4-mapped forms of those);
* the connection goes to the IP that was checked, with the original hostname used for
  TLS SNI and certificate verification, so DNS cannot be swapped in between (rebinding);
* redirects are followed manually, one hop at a time, each re-checked; at most
  ``max_hops``; only https is requested (http Locations on allowed hosts are upgraded);
* HEAD first, GET only if HEAD is refused, and the response body is never read;
* no cookies, no credentials, short timeouts.
"""

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import structlog

log = structlog.get_logger(__name__)

Resolver = Callable[[str], list[str]]

USER_AGENT = "PriceScope-LinkResolver/0.1 (+redirect resolution only)"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class UnsafeUrlError(Exception):
    """The URL (or a redirect hop) points somewhere we must not connect to."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class ResolveError(Exception):
    """The short link could not be resolved (timeout, bad response, too many hops)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            return is_public_ip(str(mapped))
    return bool(ip.is_global) and not ip.is_multicast


@dataclass(frozen=True)
class Hop:
    url: str
    status: int


class SafeRedirectResolver:
    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.BaseTransport | None = None,
        max_hops: int = 5,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._allowed = frozenset(h.lower() for h in allowed_hosts)
        self._resolver = resolver
        self._max_hops = max_hops
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,  # never route through env-configured proxies
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ checks

    def _check_url(self, url: str) -> tuple[str, str, str]:
        """Return (https_url, host, path_and_query) or raise UnsafeUrlError."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise UnsafeUrlError("invalid", "Redirect target is not a valid URL") from None
        if parts.scheme not in ("http", "https"):
            raise UnsafeUrlError("scheme", f"Scheme {parts.scheme!r} is not allowed")
        if parts.username is not None or parts.password is not None:
            raise UnsafeUrlError("credentials", "URLs with credentials are not allowed")
        if port not in (None, 80, 443):
            raise UnsafeUrlError("port", "Non-standard ports are not allowed")
        host = (parts.hostname or "").rstrip(".").lower()
        if not host or not host.isascii():
            raise UnsafeUrlError("host", "Missing or non-ASCII host")
        if host not in self._allowed:
            raise UnsafeUrlError("host_not_allowed", f"Host {host!r} is not on the allowlist")
        path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        return urlunsplit(("https", host, parts.path or "/", parts.query, "")), host, path

    def _pin(self, host: str) -> str:
        try:
            addresses = self._resolver(host)
        except OSError:
            raise ResolveError("dns", f"Could not resolve {host}") from None
        if not addresses:
            raise ResolveError("dns", f"No addresses for {host}")
        unsafe = [a for a in addresses if not is_public_ip(a)]
        if unsafe:
            raise UnsafeUrlError("private_address", f"{host} resolves to a non-public address")
        return addresses[0]

    # ------------------------------------------------------------------ requests

    def _request(self, method: str, ip: str, host: str, path: str) -> httpx.Response:
        literal = f"[{ip}]" if ":" in ip else ip
        request = self._client.build_request(
            method,
            f"https://{literal}{path}",
            headers={"Host": host},
            # TLS SNI + certificate check use the real hostname, the socket uses the pinned IP.
            extensions={"sni_hostname": host},
        )
        response = self._client.send(request, stream=True)
        response.close()  # body is never read
        return response

    def resolve(
        self, url: str, *, is_final: Callable[[str], bool] | None = None
    ) -> tuple[str, list[Hop]]:
        """Follow redirects from ``url``; return the final URL and the hops taken.

        ``is_final`` lets the caller stop as soon as a redirect points at a URL it can use
        (e.g. a recognisable product page), so that page itself is never requested.
        """
        current = url
        hops: list[Hop] = []
        for _ in range(self._max_hops + 1):
            safe_url, host, path = self._check_url(current)
            if hops and is_final is not None and is_final(safe_url):
                return safe_url, hops
            ip = self._pin(host)
            try:
                response = self._request("HEAD", ip, host, path)
                if response.status_code in (403, 405, 501):
                    response = self._request("GET", ip, host, path)
            except httpx.TimeoutException:
                raise ResolveError("timeout", "The link took too long to respond") from None
            except httpx.HTTPError as exc:
                raise ResolveError(
                    "network", f"Could not open the link ({type(exc).__name__})"
                ) from None
            hops.append(Hop(safe_url, response.status_code))
            if response.status_code not in REDIRECT_STATUSES:
                if 200 <= response.status_code < 300:
                    return safe_url, hops
                raise ResolveError("http_status", f"The link returned HTTP {response.status_code}")
            location = response.headers.get("location")
            if not location:
                raise ResolveError("no_location", "Redirect without a Location header")
            current = urljoin(safe_url, location)
        raise ResolveError("too_many_redirects", "The link redirects too many times")
