"""In-memory SheetClient that behaves like a Google spreadsheet for tests.

Cells are strings; row 1 is the header row; reads return rows up to the last non-empty
one, like the real API. Every method call is counted so tests can assert API usage.
"""

from collections import Counter


class FakeSheetClient:
    def __init__(self) -> None:
        self.tabs: dict[str, list[list[str]]] = {}
        self.calls: Counter[str] = Counter()

    # -- SheetClient protocol
    def ping(self) -> None:
        self.calls["ping"] += 1

    def worksheet_titles(self) -> list[str]:
        self.calls["worksheet_titles"] += 1
        return list(self.tabs)

    def create_worksheet(self, title: str, headers: list[str]) -> None:
        self.calls["create_worksheet"] += 1
        assert title not in self.tabs
        self.tabs[title] = [list(headers)]

    def set_headers(self, title: str, headers: list[str]) -> None:
        self.calls["set_headers"] += 1
        self.tabs[title][0] = list(headers)

    def get_values(self, title: str) -> list[list[str]]:
        self.calls["get_values"] += 1
        rows = [list(r) for r in self.tabs[title]]
        while rows and not any(rows[-1]):
            rows.pop()
        return rows

    def get_column(self, title: str, col: int) -> list[str]:
        self.calls["get_column"] += 1
        return [r[col - 1] if len(r) >= col else "" for r in self.tabs[title]]

    def append_rows(self, title: str, rows: list[list[str]]) -> None:
        self.calls["append_rows"] += 1
        for r in rows:
            assert all(isinstance(v, str) for v in r), "cells must be written as text"
        self.tabs[title].extend(list(r) for r in rows)

    def update_row(self, title: str, row_number: int, values: list[str]) -> None:
        self.calls["update_row"] += 1
        assert row_number >= 2, "the header row must never be overwritten"
        self.tabs[title][row_number - 1] = list(values)

    def delete_row(self, title: str, row_number: int) -> None:
        self.calls["delete_row"] += 1
        assert row_number >= 2, "the header row must never be deleted"
        del self.tabs[title][row_number - 1]

    # -- test helpers (simulate other writers / hand edits)
    def insert_raw_row(self, title: str, row_number: int, values: list[str]) -> None:
        self.tabs[title].insert(row_number - 1, list(values))

    def set_cell(self, title: str, row_number: int, column: str, value: str) -> None:
        idx = self.tabs[title][0].index(column)
        self.tabs[title][row_number - 1][idx] = value

    def column_values(self, title: str, column: str) -> list[str]:
        idx = self.tabs[title][0].index(column)
        return [r[idx] for r in self.tabs[title][1:]]
