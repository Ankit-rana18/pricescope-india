"""TableStore on PostgreSQL (SQLAlchemy Core). Same validation as the Sheets store;
the database's own constraints remain as a backstop."""

from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DataError, IntegrityError

from app.storage import schema
from app.storage.errors import ConstraintViolation, RowNotFound

Row = dict[str, Any]


def _as_violation(table: str, exc: Exception) -> ConstraintViolation:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", None) or "database"
    return ConstraintViolation(table, constraint, f"{table}: rejected by database ({constraint})")


class SqlTableStore:
    backend_name = "postgres"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ping(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))

    def _pk(self, table: str, pk: Any) -> tuple[sa.Table, sa.Column[Any], Any]:
        tbl = schema.table(table)
        col = tbl.c[schema.info(table).pk]
        try:
            return tbl, col, schema.normalize_value(table, col, pk)
        except ConstraintViolation:
            raise RowNotFound(table, pk) from None

    def _prepare(self, table: str, values: Mapping[str, Any]) -> Row:
        pk_col = schema.table(table).c[schema.info(table).pk]
        row = schema.apply_insert_defaults(table, values)
        if row.get(pk_col.name) is None and schema.is_autoincrement_int_pk(pk_col):
            # Let the database sequence assign it; validate the rest.
            row[pk_col.name] = 1
            row = schema.normalize_row(table, row)
            del row[pk_col.name]
            return row
        return schema.normalize_row(table, row)

    def insert(self, table: str, values: Mapping[str, Any]) -> Row:
        return self.insert_many(table, [values])[0]

    def insert_many(self, table: str, rows: Sequence[Mapping[str, Any]]) -> list[Row]:
        if not rows:
            return []
        tbl = schema.table(table)
        prepared = [self._prepare(table, r) for r in rows]
        try:
            with self._engine.begin() as conn:
                return [
                    dict(
                        conn.execute(sa.insert(tbl).values(**r).returning(*tbl.c)).mappings().one()
                    )
                    for r in prepared
                ]
        except (IntegrityError, DataError) as exc:
            raise _as_violation(table, exc) from exc

    def get(self, table: str, pk: Any) -> Row:
        tbl, col, key = self._pk(table, pk)
        with self._engine.connect() as conn:
            found = conn.execute(sa.select(tbl).where(col == key)).mappings().first()
        if found is None:
            raise RowNotFound(table, pk)
        return dict(found)

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
        stmt = sa.select(tbl)
        for k, v in (where or {}).items():
            value = schema.normalize_value(table, tbl.c[k], v)
            stmt = stmt.where(tbl.c[k].is_(None) if value is None else tbl.c[k] == value)
        if order_by is not None:
            if order_by not in tbl.c:
                raise ConstraintViolation(table, "unknown_column", f"Unknown column {order_by}")
            c = tbl.c[order_by]
            stmt = stmt.order_by(c.desc().nulls_last() if descending else c.asc().nulls_last())
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._engine.connect() as conn:
            return [dict(r) for r in conn.execute(stmt).mappings()]

    def update(self, table: str, pk: Any, changes: Mapping[str, Any]) -> Row:
        tbl, col, key = self._pk(table, pk)
        if col.name in changes and changes[col.name] != key:
            raise ConstraintViolation(table, "primary_key", "The primary key cannot change")
        current = self.get(table, key)
        row = schema.normalize_row(
            table, schema.apply_update_defaults(table, {**current, **changes})
        )
        try:
            with self._engine.begin() as conn:
                result = conn.execute(
                    sa.update(tbl).where(col == key).values(**row).returning(*tbl.c)
                ).mappings()
                return dict(result.one())
        except (IntegrityError, DataError) as exc:
            raise _as_violation(table, exc) from exc

    def delete(self, table: str, pk: Any) -> None:
        tbl, col, key = self._pk(table, pk)
        try:
            with self._engine.begin() as conn:
                if conn.execute(sa.delete(tbl).where(col == key)).rowcount == 0:
                    raise RowNotFound(table, pk)
        except IntegrityError as exc:
            raise _as_violation(table, exc) from exc
