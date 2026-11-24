"""Low-level spreadsheet access: the only module that talks to the Google Sheets API.

Row numbers are 1-based sheet rows; row 1 is the header row.
"""

import json
from pathlib import Path
from typing import Any, Protocol

import gspread
from gspread.http_client import BackOffHTTPClient
from gspread.utils import ValueInputOption, rowcol_to_a1

from app.core.config import Settings
from app.storage.errors import StorageError, StorageNotConfigured

# Least privilege: spreadsheets only, no Drive access.
SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


class SheetClient(Protocol):
    def ping(self) -> None: ...
    def worksheet_titles(self) -> list[str]: ...
    def create_worksheet(self, title: str, headers: list[str]) -> None: ...
    def set_headers(self, title: str, headers: list[str]) -> None: ...
    def get_values(self, title: str) -> list[list[str]]: ...
    def get_column(self, title: str, col: int) -> list[str]: ...
    def append_rows(self, title: str, rows: list[list[str]]) -> None: ...
    def update_row(self, title: str, row_number: int, values: list[str]) -> None: ...
    def delete_row(self, title: str, row_number: int) -> None: ...


def load_service_account_info(settings: Settings) -> dict[str, Any]:
    if settings.google_service_account_json is not None:
        raw = settings.google_service_account_json.get_secret_value().strip()
        if raw:
            try:
                info: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                raise StorageNotConfigured(
                    "PRICESCOPE_GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON"
                ) from None
            return info
    if settings.google_service_account_file:
        path = Path(settings.google_service_account_file)
        if not path.is_file():
            raise StorageNotConfigured(f"Service-account file not found: {path}")
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    raise StorageNotConfigured("Google service-account credentials are not configured")


class GspreadSheetClient:
    """SheetClient backed by gspread, with automatic backoff on 429/5xx responses."""

    def __init__(self, settings: Settings) -> None:
        if not settings.google_sheets_spreadsheet_id:
            raise StorageNotConfigured("PRICESCOPE_GOOGLE_SHEETS_SPREADSHEET_ID is not set")
        self._spreadsheet_id = settings.google_sheets_spreadsheet_id
        self._info = load_service_account_info(settings)
        self._spreadsheet: gspread.Spreadsheet | None = None
        self._worksheets: dict[str, gspread.Worksheet] = {}

    @property
    def service_account_email(self) -> str:
        return str(self._info.get("client_email", ""))

    def _book(self) -> gspread.Spreadsheet:
        if self._spreadsheet is None:
            try:
                gc = gspread.service_account_from_dict(
                    self._info, scopes=list(SCOPES), http_client=BackOffHTTPClient
                )
                self._spreadsheet = gc.open_by_key(self._spreadsheet_id)
            except gspread.exceptions.SpreadsheetNotFound:
                raise StorageNotConfigured(
                    "Spreadsheet not found. Share it (Editor) with the service account "
                    f"{self.service_account_email or '(unknown email)'}."
                ) from None
            except (gspread.exceptions.APIError, ValueError) as exc:
                raise StorageError(f"Google Sheets error: {type(exc).__name__}") from exc
        return self._spreadsheet

    def _ws(self, title: str) -> gspread.Worksheet:
        ws = self._worksheets.get(title)
        if ws is None:
            ws = self._book().worksheet(title)
            self._worksheets[title] = ws
        return ws

    def ping(self) -> None:
        self._book().fetch_sheet_metadata()

    def worksheet_titles(self) -> list[str]:
        sheets = self._book().worksheets()
        self._worksheets.update({w.title: w for w in sheets})
        return [w.title for w in sheets]

    def create_worksheet(self, title: str, headers: list[str]) -> None:
        ws = self._book().add_worksheet(title=title, rows=100, cols=max(len(headers), 1))
        ws.update([headers], range_name="A1", value_input_option=ValueInputOption.raw)
        ws.freeze(rows=1)
        self._worksheets[title] = ws

    def set_headers(self, title: str, headers: list[str]) -> None:
        ws = self._ws(title)
        if ws.col_count < len(headers):
            ws.add_cols(len(headers) - ws.col_count)
        ws.update([headers], range_name="A1", value_input_option=ValueInputOption.raw)

    def get_values(self, title: str) -> list[list[str]]:
        return [[str(v) for v in row] for row in self._ws(title).get_all_values()]

    def get_column(self, title: str, col: int) -> list[str]:
        return ["" if v is None else str(v) for v in self._ws(title).col_values(col)]

    def append_rows(self, title: str, rows: list[list[str]]) -> None:
        # RAW: values are stored literally, so user text can never become a formula.
        self._ws(title).append_rows(rows, value_input_option=ValueInputOption.raw, table_range="A1")

    def update_row(self, title: str, row_number: int, values: list[str]) -> None:
        start = rowcol_to_a1(row_number, 1)
        end = rowcol_to_a1(row_number, len(values))
        self._ws(title).update(
            [values], range_name=f"{start}:{end}", value_input_option=ValueInputOption.raw
        )

    def delete_row(self, title: str, row_number: int) -> None:
        self._ws(title).delete_rows(row_number)
