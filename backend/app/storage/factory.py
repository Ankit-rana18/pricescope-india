"""Select the storage backend from settings (dependency-injection entry point)."""

from functools import lru_cache

from app.core.config import Settings, StorageBackendName, get_settings
from app.storage.base import TableStore
from app.storage.errors import StorageNotConfigured


def build_store(settings: Settings) -> TableStore:
    if settings.storage_backend is StorageBackendName.POSTGRES:
        from app.db.session import get_engine
        from app.storage.sql_store import SqlTableStore

        return SqlTableStore(get_engine())

    if not settings.sheets_configured:
        raise StorageNotConfigured(
            "Google Sheets storage is selected but not configured: set "
            "PRICESCOPE_GOOGLE_SHEETS_SPREADSHEET_ID and service-account credentials"
        )
    from app.storage.sheets.client import GspreadSheetClient
    from app.storage.sheets.store import SheetsTableStore

    return SheetsTableStore(
        GspreadSheetClient(settings), cache_ttl_seconds=settings.sheets_cache_ttl_seconds
    )


@lru_cache
def _cached_store() -> TableStore:
    return build_store(get_settings())


def get_store() -> TableStore:
    """FastAPI dependency. Raises StorageNotConfigured (503) until storage is set up."""
    return _cached_store()
