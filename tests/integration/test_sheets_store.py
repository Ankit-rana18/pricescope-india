"""Behaviour specific to the Google Sheets backend (layout, safety, API usage)."""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from gspread.utils import ValueInputOption
from support.fake_sheets import FakeSheetClient

from app.core.config import Settings
from app.storage import schema
from app.storage.bootstrap import bootstrap, ensure_layout
from app.storage.errors import StorageDataError, StorageSchemaError
from app.storage.sheets.client import GspreadSheetClient
from app.storage.sheets.store import SheetsTableStore


@pytest.fixture
def client() -> FakeSheetClient:
    c = FakeSheetClient()
    bootstrap(c)
    return c


@pytest.fixture
def store(client: FakeSheetClient) -> SheetsTableStore:
    return SheetsTableStore(client, cache_ttl_seconds=60)


# ------------------------------------------------------------------ bootstrap


def test_bootstrap_creates_every_tab_with_pk_first_and_is_idempotent() -> None:
    c = FakeSheetClient()
    first = bootstrap(c)
    assert sorted(first.created_tabs) == sorted(schema.tables())
    assert first.seeded_marketplaces == 5
    for name in schema.tables():
        assert c.tabs[name][0][0] == "id"

    second = bootstrap(c)
    assert second.created_tabs == []
    assert second.added_columns == {}
    assert second.seeded_marketplaces == 0
    assert len(c.tabs["marketplaces"]) == 1 + 5


def test_bootstrap_appends_missing_columns_without_touching_data(client: FakeSheetClient) -> None:
    client.tabs["products"][0].remove("image_url")
    report = ensure_layout(client)
    assert report.added_columns == {"products": ["image_url"]}
    assert client.tabs["products"][0][-1] == "image_url"


def test_bootstrap_refuses_unknown_columns(client: FakeSheetClient) -> None:
    client.tabs["users"][0].append("password")
    with pytest.raises(StorageSchemaError, match="unexpected columns"):
        ensure_layout(client)


# ------------------------------------------------------------------ layout robustness


def test_columns_are_mapped_by_header_name_not_position(
    client: FakeSheetClient, store: SheetsTableStore
) -> None:
    p = store.insert("products", {"slug": "amul-butter", "title": "Amul Butter"})
    # Someone reorders the columns in the sheet UI.
    tab = client.tabs["products"]
    order = list(reversed(range(len(tab[0]))))
    client.tabs["products"] = [[row[i] for i in order] for row in tab]

    fresh = SheetsTableStore(client, cache_ttl_seconds=0)
    assert fresh.get("products", p["id"])["slug"] == "amul-butter"
    fresh.update("products", p["id"], {"title": "Amul Butter 500 g"})
    assert fresh.get("products", p["id"])["title"] == "Amul Butter 500 g"
    assert fresh.get("products", p["id"])["slug"] == "amul-butter"


def test_update_targets_the_right_row_after_rows_shift(
    client: FakeSheetClient, store: SheetsTableStore
) -> None:
    a = store.insert("products", {"slug": "a", "title": "A"})
    b = store.insert("products", {"slug": "b", "title": "B"})
    store.get("products", b["id"])  # cache the current layout
    # Another writer inserts a row above ours after we cached the tab.
    blank = [""] * len(client.tabs["products"][0])
    client.insert_raw_row("products", 2, blank)

    store.update("products", b["id"], {"title": "B2"})
    titles = dict(
        zip(
            client.column_values("products", "slug"),
            client.column_values("products", "title"),
            strict=True,
        )
    )
    assert titles["a"] == "A"
    assert titles["b"] == "B2"
    assert store.get("products", a["id"])["title"] == "A"


def test_extra_columns_added_by_hand_are_preserved_on_update(
    client: FakeSheetClient, store: SheetsTableStore
) -> None:
    p = store.insert("products", {"slug": "x", "title": "X"})
    tab = client.tabs["products"]
    tab[0].append("ops_note")
    tab[1].append("checked by hand")
    fresh = SheetsTableStore(client, cache_ttl_seconds=0)
    fresh.update("products", p["id"], {"title": "X2"})
    assert client.tabs["products"][1][-1] == "checked by hand"


def test_hand_edited_bad_cell_is_skipped_in_lists_and_reported_on_get(
    client: FakeSheetClient, store: SheetsTableStore
) -> None:
    product = store.insert("products", {"slug": "p", "title": "P"})
    good = store.insert("product_variants", {"product_id": product["id"], "variant_key": "good"})
    bad = store.insert("product_variants", {"product_id": product["id"], "variant_key": "bad"})
    client.set_cell("product_variants", 3, "pack_count", "two")

    fresh = SheetsTableStore(client, cache_ttl_seconds=0)
    assert [r["id"] for r in fresh.find("product_variants")] == [good["id"]]
    with pytest.raises(StorageDataError) as exc_info:
        fresh.get("product_variants", bad["id"])
    assert exc_info.value.details == {"table": "product_variants", "row": 3, "column": "pack_count"}


# ------------------------------------------------------------------ encoding and safety


def test_cells_are_written_as_exact_text(client: FakeSheetClient, store: SheetsTableStore) -> None:
    formula = '=IMPORTXML("https://evil.example","//a")'
    store.insert("products", {"slug": "f", "title": formula})
    assert formula in client.column_values("products", "title")

    cmp = store.insert(
        "comparisons",
        {"source_url": "https://www.amazon.in/dp/B0", "pincode": "400001", "data_mode": "DEMO"},
    )
    mkt = store.find("marketplaces", {"code": "BLINKIT"})[0]["id"]
    store.insert(
        "comparison_results",
        {
            "comparison_id": cmp["id"],
            "marketplace_id": mkt,
            "status": "OK",
            "item_price": Decimal("0.1") + Decimal("0.2"),
            "final_price": Decimal("12345.675"),
            "final_price_complete": True,
        },
    )
    assert client.column_values("comparison_results", "item_price") == ["0.30"]
    assert client.column_values("comparison_results", "final_price") == ["12345.68"]
    assert client.column_values("comparison_results", "delivery_fee") == [""]
    assert client.column_values("comparison_results", "delivery_fee_status") == ["UNKNOWN"]
    assert client.column_values("comparison_results", "final_price_complete") == ["TRUE"]


def test_gspread_client_always_writes_raw_values() -> None:
    settings = Settings(
        google_sheets_spreadsheet_id="sheet-id",
        google_service_account_json='{"client_email": "svc@example.iam.gserviceaccount.com"}',  # type: ignore[arg-type]
    )
    client = GspreadSheetClient(settings)
    ws = MagicMock()
    client._worksheets["products"] = ws

    client.append_rows("products", [["=1+1"]])
    client.update_row("products", 3, ["a", "=2+2"])

    assert ws.append_rows.call_args.kwargs["value_input_option"] == ValueInputOption.raw
    assert ws.update.call_args.kwargs["value_input_option"] == ValueInputOption.raw
    assert ws.update.call_args.kwargs["range_name"] == "A3:B3"


def test_service_account_json_never_appears_in_settings_repr() -> None:
    settings = Settings(
        google_service_account_json='{"private_key": "-----BEGIN PRIVATE KEY-----abc"}',  # type: ignore[arg-type]
    )
    assert "PRIVATE KEY" not in repr(settings)


# ------------------------------------------------------------------ API usage


def test_reads_are_cached_and_own_writes_invalidate(
    client: FakeSheetClient, store: SheetsTableStore
) -> None:
    p = store.insert("products", {"slug": "c", "title": "C"})
    client.calls.clear()
    store.get("products", p["id"])
    store.get("products", p["id"])
    store.find("products")
    assert client.calls["get_values"] == 1

    store.update("products", p["id"], {"title": "C2"})
    client.calls.clear()
    assert store.get("products", p["id"])["title"] == "C2"
    assert client.calls["get_values"] == 1


def test_integer_primary_keys_are_assigned_sequentially(store: SheetsTableStore) -> None:
    a = store.insert(
        "pincode_directory",
        {
            "pincode": "560001",
            "office_name": "Bangalore GPO",
            "district": "Bengaluru",
            "state": "Karnataka",
        },
    )
    b = store.insert(
        "pincode_directory",
        {
            "pincode": "110001",
            "office_name": "New Delhi GPO",
            "district": "New Delhi",
            "state": "Delhi",
        },
    )
    assert (a["id"], b["id"]) == (1, 2)


def test_uuid_primary_key_lookup_accepts_string(store: SheetsTableStore) -> None:
    p = store.insert("products", {"slug": "s", "title": "S"})
    assert store.get("products", str(p["id"]))["id"] == p["id"]
    assert isinstance(p["id"], uuid.UUID)
