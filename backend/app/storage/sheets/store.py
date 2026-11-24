"""TableStore on Google Sheets: one worksheet (tab) per table, one row per record.

Sheets has no transactions or constraints, so this store enforces them itself:
primary/unique keys (case-insensitive for CITEXT), foreign keys, ON DELETE rules,
types, NOT NULL and CHECK rules (via ``app.storage.schema``).

Limits (acceptable for the interim, documented in docs/STORAGE.md):
* Checks and writes are serialized per process only. Run a single API process while
  Sheets is the primary store; concurrent writers in other processes can race.
* Each read of a tab downloads the whole tab; contents are cached for
  ``sheets_cache_ttl_seconds`` and invalidated by this process's own writes.
"""

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import CITEXT

from app.storage import schema
from app.storage.errors import (
    ConstraintViolation,
    RowNotFound,
    StorageDataError,
    StorageSchemaError,
)
from app.storage.sheets.client import SheetClient

log = structlog.get_logger(__name__)
Row = dict[str, Any]


@dataclass
class _Snapshot:
    headers: list[str]
    rows: list[tuple[int, list[str]]]  # (sheet row number, raw cells aligned to headers)
    loaded_at: float


class SheetsTableStore:
    backend_name = "sheets"

    def __init__(self, client: SheetClient, cache_ttl_seconds: float = 10.0) -> None:
        self._client = client
        self._ttl = cache_ttl_seconds
        self._cache: dict[str, _Snapshot] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ reading

    def ping(self) -> None:
        self._client.ping()

    def _load(self, t: str, *, fresh: bool = False) -> _Snapshot:
        snap = self._cache.get(t)
        if snap and not fresh and time.monotonic() - snap.loaded_at < self._ttl:
            return snap
        values = self._client.get_values(t)
        if not values:
            raise StorageSchemaError(f"Tab {t!r} has no header row; run the storage bootstrap")
        headers = [h.strip() for h in values[0]]
        missing = set(schema.info(t).columns) - set(headers)
        if missing:
            raise StorageSchemaError(
                f"Tab {t!r} is missing columns {sorted(missing)}; run the storage bootstrap"
            )
        width = len(headers)
        rows = [
            (i, (r + [""] * width)[:width])
            for i, r in enumerate(values[1:], start=2)
            if any(cell != "" for cell in r)
        ]
        snap = _Snapshot(headers=headers, rows=rows, loaded_at=time.monotonic())
        self._cache[t] = snap
        return snap

    def _decode(self, t: str, headers: list[str], raw: list[str], row_number: int) -> Row:
        tbl = schema.table(t)
        out: Row = {}
        for name, cell in zip(headers, raw, strict=True):
            col = tbl.c.get(name)
            if col is None:
                continue  # extra columns added by hand are preserved but ignored
            try:
                out[name] = schema.decode_cell(t, col, cell)
            except Exception as exc:
                raise StorageDataError(
                    f"{t} row {row_number}, column {name}: cannot read value",
                    details={"table": t, "row": row_number, "column": name},
                ) from exc
        return out

    def _rows(self, t: str, *, fresh: bool = False) -> list[tuple[int, Row]]:
        """All decodable rows. Rows with bad cells are logged and skipped, not fatal."""
        snap = self._load(t, fresh=fresh)
        out = []
        for row_number, raw in snap.rows:
            try:
                out.append((row_number, self._decode(t, snap.headers, raw, row_number)))
            except StorageDataError as exc:
                log.error("sheets_row_invalid", table=t, row=row_number, error=exc.message)
        return out

    def get(self, table: str, pk: Any) -> Row:
        key = self._pk_value(table, pk)
        pk_name = schema.info(table).pk
        snap = self._load(table)
        target = schema.encode_cell(schema.table(table).c[pk_name], key)
        idx = snap.headers.index(pk_name)
        for row_number, raw in snap.rows:
            if raw[idx] == target:
                # A damaged row is reported as such, not as "not found".
                return self._decode(table, snap.headers, raw, row_number)
        raise RowNotFound(table, pk)

    def find(
        self,
        table: str,
        where: Mapping[str, Any] | None = None,
        *,
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[Row]:
        tbl = schema.table(table)
        filters = {k: schema.normalize_value(table, tbl.c[k], v) for k, v in (where or {}).items()}
        rows = [r for _, r in self._rows(table) if all(r.get(k) == v for k, v in filters.items())]
        if order_by is not None:
            if order_by not in tbl.c:
                raise ConstraintViolation(table, "unknown_column", f"Unknown column {order_by}")
            # NULLs sort last in both directions, matching typical API expectations.
            present = [r for r in rows if r[order_by] is not None]
            absent = [r for r in rows if r[order_by] is None]
            present.sort(key=lambda r: r[order_by], reverse=descending)
            rows = present + absent
        return rows[:limit] if limit is not None else rows

    # ------------------------------------------------------------------ writing

    def insert(self, table: str, values: Mapping[str, Any]) -> Row:
        with self._lock:
            row = schema.apply_insert_defaults(table, values)
            existing = self._rows(table, fresh=True)
            pk = schema.info(table).pk
            pk_col = schema.table(table).c[pk]
            if row.get(pk) is None and schema.is_autoincrement_int_pk(pk_col):
                row[pk] = max((r[pk] for _, r in existing), default=0) + 1
            row = schema.normalize_row(table, row)
            self._check_unique(table, row, existing, exclude_row=None)
            self._check_foreign_keys(table, row)
            snap = self._load(table)
            self._client.append_rows(table, [self._encode(table, snap.headers, row, None)])
            self._cache.pop(table, None)
            return row

    def update(self, table: str, pk: Any, changes: Mapping[str, Any]) -> Row:
        with self._lock:
            pk_name = schema.info(table).pk
            if pk_name in changes and changes[pk_name] != self._pk_value(table, pk):
                raise ConstraintViolation(table, "primary_key", "The primary key cannot change")
            existing = self._rows(table, fresh=True)
            snap = self._load(table)  # the snapshot `existing` was decoded from
            key = self._pk_value(table, pk)
            found = next(((n, r) for n, r in existing if r[pk_name] == key), None)
            if found is None:
                raise RowNotFound(table, pk)
            row_number, current = found
            merged = schema.apply_update_defaults(table, {**current, **changes})
            row = schema.normalize_row(table, merged)
            self._check_unique(table, row, existing, exclude_row=key)
            self._check_foreign_keys(table, row)
            raw_current = next(raw for n, raw in snap.rows if n == row_number)
            self._write_row(table, key, self._encode(table, snap.headers, row, raw_current))
            return row

    def delete(self, table: str, pk: Any) -> None:
        with self._lock:
            key = self._pk_value(table, pk)
            self.get(table, key)  # RowNotFound if absent
            # No transactions in Sheets: prove the whole delete is allowed before changing
            # anything, so a RESTRICT deep in a cascade can't leave a half-done delete.
            self._assert_deletable(table, key)
            self._apply_on_delete(table, key)
            row_number = self._locate(table, key)
            self._client.delete_row(table, row_number)
            self._cache.pop(table, None)

    def _assert_deletable(self, parent: str, key: Any) -> None:
        for child, column, ondelete in schema.referencing(parent):
            children = self.find(child, {column: key})
            if not children or ondelete == "SET NULL":
                continue
            if ondelete != "CASCADE":
                raise ConstraintViolation(
                    parent,
                    "foreign_key",
                    f"{parent} row is still referenced by {child}.{column}",
                    referenced_by=child,
                )
            child_pk = schema.info(child).pk
            for c in children:
                self._assert_deletable(child, c[child_pk])

    def _apply_on_delete(self, parent: str, key: Any) -> None:
        for child, column, ondelete in schema.referencing(parent):
            children = self.find(child, {column: key})
            if not children:
                continue
            child_pk = schema.info(child).pk
            if ondelete == "CASCADE":
                for c in children:
                    self.delete(child, c[child_pk])
            elif ondelete == "SET NULL":
                for c in children:
                    self.update(child, c[child_pk], {column: None})
            else:  # RESTRICT / NO ACTION
                raise ConstraintViolation(
                    parent,
                    "foreign_key",
                    f"{parent} row is still referenced by {child}.{column}",
                    referenced_by=child,
                )

    # ------------------------------------------------------------------ helpers

    def _pk_value(self, table: str, pk: Any) -> Any:
        col = schema.table(table).c[schema.info(table).pk]
        try:
            return schema.normalize_value(table, col, pk)
        except ConstraintViolation:
            raise RowNotFound(table, pk) from None

    def _locate(self, table: str, key: Any) -> int:
        """Find the row's *current* sheet row number by reading the key column fresh.

        Guards against rows shifting because another writer inserted or deleted rows.
        """
        snap = self._load(table)
        pk_name = schema.info(table).pk
        col_index = snap.headers.index(pk_name) + 1
        target = schema.encode_cell(schema.table(table).c[pk_name], key)
        column = self._client.get_column(table, col_index)
        matches = [i for i, v in enumerate(column, start=1) if i > 1 and v == target]
        if len(matches) != 1:
            raise StorageDataError(
                f"{table}: expected exactly one row with id {target}, found {len(matches)}"
            )
        return matches[0]

    def _write_row(self, table: str, key: Any, values: list[str]) -> None:
        self._client.update_row(table, self._locate(table, key), values)
        self._cache.pop(table, None)

    def _encode(
        self, table: str, headers: list[str], row: Row, raw_current: list[str] | None
    ) -> list[str]:
        tbl = schema.table(table)
        out = list(raw_current) if raw_current else [""] * len(headers)
        for i, name in enumerate(headers):
            col = tbl.c.get(name)
            if col is not None:
                out[i] = schema.encode_cell(col, row.get(name))
        return out

    def _check_unique(
        self, table: str, row: Row, existing: list[tuple[int, Row]], exclude_row: Any
    ) -> None:
        tbl = schema.table(table)
        pk_name = schema.info(table).pk

        def key_of(r: Row, cols: tuple[str, ...]) -> tuple[Any, ...] | None:
            parts = []
            for c in cols:
                v = r.get(c)
                if v is None:
                    return None  # NULLs never conflict, as in PostgreSQL
                parts.append(v.casefold() if isinstance(tbl.c[c].type, CITEXT) else v)
            return tuple(parts)

        for cols in schema.info(table).unique_sets:
            new_key = key_of(row, cols)
            if new_key is None:
                continue
            for _, other in existing:
                if exclude_row is not None and other[pk_name] == exclude_row:
                    continue
                if key_of(other, cols) == new_key:
                    raise ConstraintViolation(
                        table,
                        "unique",
                        f"{table}: a row with the same {', '.join(cols)} already exists",
                        columns=list(cols),
                    )

    def _check_foreign_keys(self, table: str, row: Row) -> None:
        for column, parent, parent_column in schema.info(table).foreign_keys:
            value = row.get(column)
            if value is None:
                continue
            if parent_column != schema.info(parent).pk:
                raise StorageSchemaError(f"{table}.{column}: FK must reference a primary key")
            try:
                self.get(parent, value)
            except RowNotFound:
                # Parent may have been added by another process since our cached read.
                self._cache.pop(parent, None)
                try:
                    self.get(parent, value)
                except RowNotFound:
                    raise ConstraintViolation(
                        table,
                        "foreign_key",
                        f"{table}.{column} refers to a missing {parent} row",
                        column=column,
                    ) from None
