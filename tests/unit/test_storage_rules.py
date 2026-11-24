"""Guards against the Sheets store silently drifting from the database schema."""

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AuthMode, Environment, Settings, StorageBackendName
from app.storage import schema
from app.storage.rules import RULES
from app.storage.seed import MARKETPLACES, UNVERIFIED_CAPABILITIES

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def test_every_check_constraint_has_a_python_rule() -> None:
    declared = {(t, c) for t in schema.tables() for c in schema.info(t).checks}
    assert declared - set(RULES) == set(), "add a rule in app/storage/rules.py"
    assert set(RULES) - declared == set(), "rule has no matching CHECK constraint"


def test_every_table_has_a_single_primary_key() -> None:
    for name in schema.tables():
        assert schema.info(name).columns[0] == schema.info(name).pk


def test_seed_matches_frozen_migration_copy() -> None:
    path = next((BACKEND / "alembic" / "versions").glob("*_seed_marketplaces.py"))
    spec = importlib.util.spec_from_file_location("seed_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def simplify(rows: list[dict[str, object]]) -> list[tuple[str, ...]]:
        return sorted(
            (str(r["code"]), str(r["name"]), str(r["integration"]), str(r["logo_path"]))
            for r in rows
        )

    assert simplify(module.MARKETPLACES) == simplify(MARKETPLACES)
    assert module._UNVERIFIED == UNVERIFIED_CAPABILITIES


def test_sheets_is_the_default_backend() -> None:
    assert Settings.model_fields["storage_backend"].default is StorageBackendName.SHEETS


def test_production_requires_sheets_configuration() -> None:
    base = {
        "env": Environment.PRODUCTION,
        "auth_mode": AuthMode.SUPABASE,
        "supabase_url": "https://x.supabase.co",
        "google_service_account_file": "",
        "google_service_account_json": None,
    }
    with pytest.raises(ValidationError, match="Google Sheets storage"):
        Settings(**base, google_sheets_spreadsheet_id="")  # type: ignore[arg-type]
    ok = Settings(
        **{**base, "google_service_account_json": '{"client_email": "a@b"}'},  # type: ignore[arg-type]
        google_sheets_spreadsheet_id="abc",
    )
    assert ok.sheets_configured
