"""Prepare the Google spreadsheet: one tab per table, header row, seed data.

Safe to run repeatedly. It creates missing tabs, appends missing columns to the right of
existing headers, and never deletes or rewrites data.

    uv run python -m app.storage.bootstrap
"""

import sys
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.storage import schema
from app.storage.errors import StorageError, StorageSchemaError
from app.storage.seed import seed_marketplaces
from app.storage.sheets.client import GspreadSheetClient, SheetClient
from app.storage.sheets.store import SheetsTableStore


@dataclass
class BootstrapReport:
    created_tabs: list[str] = field(default_factory=list)
    added_columns: dict[str, list[str]] = field(default_factory=dict)
    seeded_marketplaces: int = 0


def ensure_layout(client: SheetClient) -> BootstrapReport:
    report = BootstrapReport()
    titles = set(client.worksheet_titles())
    problems = []
    for name in sorted(schema.tables()):
        expected = list(schema.info(name).columns)
        if name not in titles:
            client.create_worksheet(name, expected)
            report.created_tabs.append(name)
            continue
        values = client.get_values(name)
        headers = [h.strip() for h in values[0]] if values else []
        unknown = [h for h in headers if h and h not in expected]
        if unknown:
            problems.append(f"{name}: unexpected columns {unknown}")
            continue
        if any(h == "" for h in headers):
            problems.append(f"{name}: blank header cell in row 1")
            continue
        missing = [c for c in expected if c not in headers]
        if missing:
            client.set_headers(name, headers + missing)
            report.added_columns[name] = missing
    if problems:
        raise StorageSchemaError("Spreadsheet layout problems: " + "; ".join(problems))
    return report


def bootstrap(client: SheetClient, cache_ttl_seconds: float = 0.0) -> BootstrapReport:
    report = ensure_layout(client)
    store = SheetsTableStore(client, cache_ttl_seconds=cache_ttl_seconds)
    report.seeded_marketplaces = seed_marketplaces(store)
    return report


def main() -> int:
    settings = get_settings()
    try:
        client = GspreadSheetClient(settings)
        print(f"Service account: {client.service_account_email}")
        report = bootstrap(client)
    except StorageError as exc:
        print(f"Bootstrap failed: {exc.message}", file=sys.stderr)
        return 1
    print(f"Tabs created: {', '.join(report.created_tabs) or 'none'}")
    for tab, cols in report.added_columns.items():
        print(f"Columns added to {tab}: {', '.join(cols)}")
    print(f"Marketplaces seeded: {report.seeded_marketplaces}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
