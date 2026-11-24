"""Readiness must report storage problems as 503 with a readable body, never crash."""

from collections.abc import Callable

from fastapi.testclient import TestClient
from support.fake_sheets import FakeSheetClient

from app.api.v1.health import storage_provider
from app.core.config import Environment, Settings
from app.main import create_app
from app.storage.base import TableStore
from app.storage.errors import StorageNotConfigured
from app.storage.sheets.store import SheetsTableStore


def _ready(provider: Callable[[], TableStore]) -> tuple[int, dict[str, object]]:
    app = create_app(Settings(env=Environment.TEST, log_level="WARNING"))
    app.dependency_overrides[storage_provider] = lambda: provider
    with TestClient(app) as c:
        r = c.get("/api/v1/health/ready")
    return r.status_code, r.json()


def test_ok_with_reachable_sheets_store() -> None:
    store = SheetsTableStore(FakeSheetClient())
    status, body = _ready(lambda: store)
    assert status == 200
    assert body["storage_backend"] == "sheets"
    assert body["checks"] == {"storage": "ok"}


def test_not_configured_is_reported_distinctly() -> None:
    def provider() -> TableStore:
        raise StorageNotConfigured("no spreadsheet id")

    status, body = _ready(provider)
    assert status == 503
    assert body["status"] == "error"
    assert body["checks"] == {"storage": "not_configured"}


def test_unreachable_storage_returns_503() -> None:
    class Broken(SheetsTableStore):
        def ping(self) -> None:
            raise ConnectionError("network down")

    store = Broken(FakeSheetClient())
    status, body = _ready(lambda: store)
    assert status == 503
    assert body["checks"] == {"storage": "error"}


def test_default_settings_without_credentials_report_not_configured() -> None:
    """The real factory path: Sheets selected, nothing configured -> not_configured."""
    from app.storage import factory

    settings = Settings(
        env=Environment.TEST,
        log_level="WARNING",
        google_sheets_spreadsheet_id="",
        google_service_account_file="",
        google_service_account_json=None,
    )
    try:
        factory.build_store(settings)
    except StorageNotConfigured as exc:
        assert "PRICESCOPE_GOOGLE_SHEETS_SPREADSHEET_ID" in exc.message
    else:
        raise AssertionError("expected StorageNotConfigured")
