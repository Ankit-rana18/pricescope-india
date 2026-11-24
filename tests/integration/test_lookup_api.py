from pathlib import Path

from fastapi.testclient import TestClient

from app.api.v1.lookup import get_pincode_directory
from app.core.config import Environment, Settings
from app.main import create_app
from app.services.pincode import PincodeDirectory

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "pincode_directory_sample.csv"
URL = "https://www.amazon.in/Tata-Salt/dp/B07JGFGW3V?tag=abc"


def _client(directory: PincodeDirectory | None = None) -> TestClient:
    app = create_app(Settings(env=Environment.TEST, log_level="WARNING"))
    app.dependency_overrides[get_pincode_directory] = lambda: directory or PincodeDirectory()
    return TestClient(app)


def test_lookup_success_without_directory_is_honest() -> None:
    r = _client().post("/api/v1/lookups/validate", json={"url": URL, "pincode": "560 001"})
    assert r.status_code == 200
    body = r.json()
    assert body["product"] == {
        "marketplace": "AMAZON_IN",
        "marketplace_name": "Amazon India",
        "external_id": "B07JGFGW3V",
        "id_type": "ASIN",
        "canonical_url": "https://www.amazon.in/dp/B07JGFGW3V",
    }
    assert body["location"]["pincode"] == "560001"
    assert body["location"]["directory_status"] == "UNAVAILABLE"
    assert body["location"]["district"] is None
    assert "does not guarantee delivery" in body["location"]["delivery_note"]
    assert body["comparison_available"] is False


def test_lookup_with_directory_reports_district() -> None:
    client = _client(PincodeDirectory.from_csv(SAMPLE))
    r = client.post("/api/v1/lookups/validate", json={"url": URL, "pincode": "110001"})
    assert r.status_code == 200
    loc = r.json()["location"]
    assert (loc["directory_status"], loc["district"], loc["state"]) == (
        "VERIFIED",
        "New Delhi",
        "Delhi",
    )


def test_lookup_reports_every_invalid_field_at_once() -> None:
    r = _client().post(
        "/api/v1/lookups/validate",
        json={"url": "https://www.amazon.com/dp/B07JGFGW3V", "pincode": "12345"},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_input"
    fields = {f["field"]: f["code"] for f in err["details"]["fields"]}
    assert fields == {"url": "unsupported_marketplace", "pincode": "pincode_format"}
    assert err["request_id"]


def test_location_validate_endpoint() -> None:
    client = _client(PincodeDirectory.from_csv(SAMPLE))
    ok = client.post("/api/v1/location/validate", json={"pincode": "400001"})
    assert ok.status_code == 200
    assert ok.json()["postal_region"] == "Western"

    missing = client.post("/api/v1/location/validate", json={"pincode": "400099"})
    assert missing.status_code == 422
    assert missing.json()["error"]["details"]["fields"][0]["code"] == "pincode_not_found"


def test_oversized_and_wrong_typed_bodies_rejected_cleanly() -> None:
    client = _client()
    huge = client.post(
        "/api/v1/lookups/validate", json={"url": "https://a/" + "x" * 5000, "pincode": "560001"}
    )
    assert huge.status_code == 422
    assert huge.json()["error"]["code"] == "validation_error"

    wrong = client.post("/api/v1/lookups/validate", json={"url": 123, "pincode": None})
    assert wrong.status_code == 422


def test_cors_preflight_allows_post_from_frontend() -> None:
    r = _client().options(
        "/api/v1/lookups/validate",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
