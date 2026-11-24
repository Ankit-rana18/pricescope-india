"""Schema-driven row handling shared by every storage backend.

The SQLAlchemy models stay the single source of truth for tables, columns, types, defaults,
unique keys and foreign keys. This module turns them into:

* ``normalize_row``: type coercion + NOT NULL + enum + length + CHECK-rule validation, so
  Google Sheets rows obey exactly the same rules as PostgreSQL rows;
* ``apply_insert_defaults`` / ``apply_update_defaults``: Python versions of server defaults;
* ``encode_cell`` / ``decode_cell``: lossless text form for spreadsheet cells.
"""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from functools import cache
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import functions

from app.models import Base
from app.storage.errors import ConstraintViolation, StorageSchemaError
from app.storage.rules import RULES

Row = dict[str, Any]

# Google Sheets hard limit per cell.
MAX_CELL_CHARS = 50_000


def tables() -> Mapping[str, sa.Table]:
    return Base.metadata.tables


def table(name: str) -> sa.Table:
    try:
        return tables()[name]
    except KeyError:
        raise StorageSchemaError(f"Unknown table {name!r}") from None


@dataclass(frozen=True)
class TableInfo:
    name: str
    pk: str
    columns: tuple[str, ...]  # primary key first
    unique_sets: tuple[tuple[str, ...], ...]  # includes the primary key
    foreign_keys: tuple[tuple[str, str, str], ...]  # (column, parent_table, parent_column)
    checks: tuple[str, ...]  # named, non-enum CHECK constraints


@cache
def info(name: str) -> TableInfo:
    t = table(name)
    pk_cols = [c.name for c in t.primary_key.columns]
    if len(pk_cols) != 1:
        raise StorageSchemaError(f"{name}: exactly one primary-key column is required")
    pk = pk_cols[0]
    uniques: list[tuple[str, ...]] = [(pk,)]
    for c in t.columns:
        if c.unique:
            uniques.append((c.name,))
    for con in t.constraints:
        if isinstance(con, sa.UniqueConstraint):
            uniques.append(tuple(c.name for c in con.columns))
    fks = tuple((fk.parent.name, fk.column.table.name, fk.column.name) for fk in t.foreign_keys)
    return TableInfo(
        name=name,
        pk=pk,
        columns=(pk, *(c.name for c in t.columns if c.name != pk)),
        unique_sets=tuple(dict.fromkeys(uniques)),
        foreign_keys=fks,
        checks=tuple(sorted(check_constraint_names(t))),
    )


def check_constraint_names(t: sa.Table) -> set[str]:
    """Named CHECK constraints written by hand (enum-generated ones are handled by type).

    Returned without the naming-convention prefix: ``ck_comparisons_pincode_format`` ->
    ``pincode_format``.
    """
    prefix = f"ck_{t.name}_"
    return {
        str(c.name).removeprefix(prefix)
        for c in t.constraints
        if isinstance(c, sa.CheckConstraint) and not getattr(c, "_type_bound", False)
    }


def referencing(parent: str) -> list[tuple[str, str, str | None]]:
    """(child_table, child_column, ondelete) for every FK pointing at ``parent``."""
    out = []
    for t in tables().values():
        for fk in t.foreign_keys:
            if fk.column.table.name == parent:
                out.append((t.name, fk.parent.name, (fk.ondelete or "").upper() or None))
    return out


# --------------------------------------------------------------------------- normalization


def _violation(t: str, column: str, message: str, constraint: str = "type") -> ConstraintViolation:
    return ConstraintViolation(t, constraint, f"{t}.{column}: {message}", column=column)


def normalize_value(t: str, col: sa.Column[Any], value: Any) -> Any:
    """Coerce a Python value to the column's canonical type, or raise ConstraintViolation."""
    if value is None:
        return None
    typ = col.type
    name = col.name
    try:
        if isinstance(typ, sa.Enum):
            enum_cls = typ.enum_class
            if enum_cls is not None:
                return enum_cls(value.value if isinstance(value, Enum) else value)
            if value not in typ.enums:
                raise ValueError
            return value
        if isinstance(typ, sa.Uuid):
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if isinstance(typ, sa.Boolean):
            if not isinstance(value, bool):
                raise _violation(t, name, "expected a boolean")
            return value
        if isinstance(typ, sa.Integer):
            if isinstance(value, bool | float):
                raise _violation(t, name, "expected an integer")
            return int(value)
        if isinstance(typ, sa.Numeric):
            # Money is exact: floats are refused rather than silently rounded.
            if isinstance(value, bool | float):
                raise _violation(t, name, "expected Decimal, int or numeric string (not float)")
            d = Decimal(str(value))
            if not d.is_finite():
                raise ValueError
            if typ.scale is not None:
                d = d.quantize(Decimal(1).scaleb(-typ.scale), rounding=ROUND_HALF_UP)
            if typ.precision is not None and typ.scale is not None:
                int_digits = len(d.as_tuple().digits) - typ.scale
                if int_digits > typ.precision - typ.scale:
                    raise _violation(t, name, "numeric value out of range", "numeric_range")
            return d
        if isinstance(typ, sa.DateTime):
            dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
        if isinstance(typ, sa.Date):
            if isinstance(value, datetime):
                raise ValueError
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        if isinstance(typ, postgresql.ARRAY):
            if not isinstance(value, list | tuple):
                raise ValueError
            item_col = sa.Column(name, typ.item_type)
            return [normalize_value(t, item_col, v) for v in value]
        if isinstance(typ, sa.JSON):
            # Round-trip proves it is plain JSON (no Decimals, datetimes or NaN).
            return json.loads(json.dumps(value, allow_nan=False))
        if isinstance(typ, sa.String):
            if not isinstance(value, str):
                raise _violation(t, name, "expected a string")
            if value == "":
                return None  # empty text is treated as NULL by both backends
            limit = typ.length or MAX_CELL_CHARS
            if len(value) > min(limit, MAX_CELL_CHARS):
                raise _violation(t, name, f"longer than {limit} characters", "length")
            return value
    except ConstraintViolation:
        raise
    except (ValueError, TypeError, InvalidOperation, AttributeError):
        raise _violation(t, name, f"invalid value {value!r}") from None
    raise StorageSchemaError(f"{t}.{name}: unsupported column type {typ!r}")


def normalize_row(t: str, row: Mapping[str, Any]) -> Row:
    """Full validation of a complete row (after defaults are applied)."""
    tbl = table(t)
    unknown = set(row) - set(tbl.c.keys())
    if unknown:
        raise ConstraintViolation(t, "unknown_column", f"{t}: unknown columns {sorted(unknown)}")
    out: Row = {}
    for col in tbl.columns:
        value = normalize_value(t, col, row.get(col.name))
        if value is None and not col.nullable:
            raise _violation(t, col.name, "must not be null", "not_null")
        out[col.name] = value
    for constraint in info(t).checks:
        rule = RULES.get((t, constraint))
        if rule is None:
            raise StorageSchemaError(f"{t}: no Python rule for CHECK constraint {constraint!r}")
        if not rule(out):
            raise ConstraintViolation(t, constraint, f"{t}: check {constraint!r} failed")
    return out


# --------------------------------------------------------------------------- defaults


def _default_from_clause(t: str, col: sa.Column[Any], arg: Any) -> Any:
    if isinstance(arg, functions.now):
        return datetime.now(UTC)
    if isinstance(arg, sa.TextClause) and "gen_random_uuid" in arg.text:
        return uuid.uuid4()
    if isinstance(arg, str):
        if isinstance(col.type, sa.Boolean):
            return arg.lower() == "true"
        if isinstance(col.type, sa.JSON):
            return json.loads(arg)
        return normalize_value(t, col, arg)
    raise StorageSchemaError(f"{t}.{col.name}: unsupported server default {arg!r}")


def column_default(t: str, col: sa.Column[Any]) -> Any:
    """Python value for a column's default, or None if it has none."""
    if col.default is not None and getattr(col.default, "is_scalar", False):
        return col.default.arg  # type: ignore[attr-defined]
    server_default = col.server_default
    if isinstance(server_default, sa.DefaultClause):
        return _default_from_clause(t, col, server_default.arg)
    return None


def is_autoincrement_int_pk(col: sa.Column[Any]) -> bool:
    return bool(col.primary_key and isinstance(col.type, sa.Integer) and col.autoincrement)


def apply_insert_defaults(t: str, row: Mapping[str, Any]) -> Row:
    out = dict(row)
    for col in table(t).columns:
        if out.get(col.name) is None and not is_autoincrement_int_pk(col):
            default = column_default(t, col)
            if default is not None:
                out[col.name] = default
    return out


def apply_update_defaults(t: str, row: Mapping[str, Any]) -> Row:
    """``onupdate`` columns (``updated_at``) are refreshed on every update."""
    out = dict(row)
    for col in table(t).columns:
        if col.onupdate is not None:
            out[col.name] = datetime.now(UTC)
    return out


# --------------------------------------------------------------------------- cell codec


def encode_cell(col: sa.Column[Any], value: Any) -> str:
    """Lossless text for a spreadsheet cell. Written with RAW input, so never a formula."""
    if value is None:
        return ""
    typ = col.type
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(typ, sa.Boolean):
        return "TRUE" if value else "FALSE"
    if isinstance(typ, sa.DateTime):
        return str(value.astimezone(UTC).isoformat())
    if isinstance(typ, postgresql.ARRAY | sa.JSON):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def decode_cell(t: str, col: sa.Column[Any], raw: str) -> Any:
    if raw == "":
        return None
    typ = col.type
    if isinstance(typ, sa.Boolean):
        if raw not in ("TRUE", "FALSE"):
            raise ValueError(f"not a boolean: {raw!r}")
        return raw == "TRUE"
    if isinstance(typ, postgresql.ARRAY | sa.JSON):
        return normalize_value(t, col, json.loads(raw))
    return normalize_value(t, col, raw)
