"""Rate limits, request-size cap and security headers on the real app."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.v1.lookup import get_pincode_directory
from app.core.auth import DevVerifier, get_user_directory, get_verifier
from app.core.config import AuthMode, Environment, Settings, StorageBackendName
from app.main import create_app
from app.services.pincode import PincodeDirectory

LOOKUP = "/api/v1/location/validate"
ORIGIN = "http://localhost:3000"


class StubDirectory:
    """Resolves any dev identity to a fixed user without touching storage."""

    def resolve(self, identity):  # type: ignore[no-untyped-def]
        from app.core.auth import CurrentUser
        from app.models.enums import UserRole

        return CurrentUser(
            id=identity.user_id,
            email=identity.email,
            role=UserRole.USER,
            display_name=None,
            default_pincode=None,
            preferences={},
        )


def _client(**overrides: object) -> TestClient:
    settings = Settings(env=Environment.TEST, log_level="WARNING", **overrides)  # type: ignore[arg-type]
    app = create_app(settings)
    app.dependency_overrides[get_pincode_directory] = lambda: PincodeDirectory()
    app.dependency_overrides[get_verifier] = lambda: DevVerifier()
    app.dependency_overrides[get_user_directory] = lambda: StubDirectory()
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client(rate_limit_lookup_anon=2, rate_limit_lookup_user=4) as c:
        yield c


def test_anonymous_callers_get_429_with_retry_after(client: TestClient) -> None:
    for _ in range(2):
        assert client.post(LOOKUP, json={"pincode": "560001"}).status_code == 200
    r = client.post(LOOKUP, json={"pincode": "560001"}, headers={"Origin": ORIGIN})
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    body = r.json()["error"]
    assert body["code"] == "rate_limited"
    assert body["details"] == {"bucket": "lookup", "limit_per_minute": 2}
    # The browser can read the error and the wait.
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "Retry-After" in r.headers["access-control-expose-headers"]


def test_signed_in_users_have_their_own_larger_bucket(client: TestClient) -> None:
    for _ in range(2):
        client.post(LOOKUP, json={"pincode": "560001"})
    asha = {"Authorization": "Bearer dev:asha@example.in"}
    ravi = {"Authorization": "Bearer dev:ravi@example.in"}
    codes = [
        client.post(LOOKUP, json={"pincode": "560001"}, headers=asha).status_code for _ in range(5)
    ]
    assert codes == [200, 200, 200, 200, 429]
    assert client.post(LOOKUP, json={"pincode": "560001"}, headers=ravi).status_code == 200


def test_reads_are_not_rate_limited(client: TestClient) -> None:
    for _ in range(5):
        assert client.get("/api/v1/health").status_code == 200


def test_rate_limits_can_be_switched_off() -> None:
    with _client(rate_limit_lookup_anon=1, rate_limit_enabled=False) as c:
        assert {c.post(LOOKUP, json={"pincode": "560001"}).status_code for _ in range(3)} == {200}


def test_oversized_bodies_are_refused_before_parsing() -> None:
    with _client(max_body_bytes=1024) as c:
        r = c.post(
            LOOKUP,
            content=b'{"pincode": "' + b"1" * 2000 + b'"}',
            headers={"Content-Type": "application/json", "Origin": ORIGIN},
        )
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "request_too_large"
        assert r.headers["access-control-allow-origin"] == ORIGIN


def test_chunked_bodies_without_a_length_are_counted() -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"pincode": "'
        for _ in range(10):
            yield b"1" * 200
        yield b'"}'

    with _client(max_body_bytes=1024) as c:
        r = c.post(LOOKUP, content=chunks(), headers={"Content-Type": "application/json"})
        assert r.status_code == 413


def test_security_headers(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "strict-transport-security" not in r.headers  # only in production
    assert "cache-control" not in r.headers
    # Swagger UI needs its scripts.
    assert "content-security-policy" not in client.get("/docs").headers


def test_per_user_responses_are_not_cacheable(client: TestClient) -> None:
    r = client.get("/api/v1/health", headers={"Authorization": "Bearer dev:asha@example.in"})
    assert r.headers["cache-control"] == "private, no-store"


def test_hsts_in_production() -> None:
    settings = Settings(
        env=Environment.PRODUCTION,
        auth_mode=AuthMode.SUPABASE,
        supabase_url="https://example.supabase.co",
        storage_backend=StorageBackendName.POSTGRES,
        log_level="WARNING",
    )
    with TestClient(create_app(settings)) as c:
        hsts = c.get("/api/v1/health").headers["strict-transport-security"]
    assert hsts.startswith("max-age=63072000")
