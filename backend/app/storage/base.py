"""The storage interface every backend implements.

Rows are plain dicts keyed by column name, holding canonical Python types (UUID, Decimal,
aware datetime, enum members, JSON-compatible dicts/lists). Feature code depends on this
interface only, so the backend can move from Google Sheets to PostgreSQL by configuration.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

Row = dict[str, Any]


class TableStore(Protocol):
    backend_name: str

    def ping(self) -> None:
        """Raise if the backend is unreachable or misconfigured."""

    def insert(self, table: str, values: Mapping[str, Any]) -> Row:
        """Validate, apply defaults, enforce keys; return the stored row."""

    def insert_many(self, table: str, rows: Sequence[Mapping[str, Any]]) -> list[Row]:
        """Insert several rows atomically (one round trip where the backend allows)."""

    def get(self, table: str, pk: Any) -> Row:
        """Return one row by primary key or raise RowNotFound."""

    def find(
        self,
        table: str,
        where: Mapping[str, Any] | None = None,
        *,
        order_by: str | None = None,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[Row]:
        """Rows whose columns equal every value in ``where``."""

    def update(self, table: str, pk: Any, changes: Mapping[str, Any]) -> Row:
        """Apply changes to one row; the whole row is re-validated."""

    def delete(self, table: str, pk: Any) -> None:
        """Delete one row, honouring ON DELETE rules of referencing tables."""
