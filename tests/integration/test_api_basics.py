from fastapi.testclient import TestClient


def test_liveness(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_request_id_and_security_headers(client: TestClient) -> None:
    r = client.get("/api/v1/health", headers={"X-Request-ID": "abcdef12-3456"})
    assert r.headers["X-Request-ID"] == "abcdef12-3456"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_malformed_request_id_is_replaced(client: TestClient) -> None:
    r = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(r.headers["X-Request-ID"]) == 32


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == r.headers["X-Request-ID"]


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    ok = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_openapi_docs_available(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "PriceScope India API"
