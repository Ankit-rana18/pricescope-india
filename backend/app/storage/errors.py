"""Storage errors. All are AppErrors, so the API returns them in the standard envelope."""

from http import HTTPStatus
from typing import Any

from app.core.errors import AppError, NotFoundError


class StorageError(AppError):
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "storage_error"


class StorageNotConfigured(StorageError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "storage_not_configured"


class StorageSchemaError(StorageError):
    """The spreadsheet layout does not match the application schema."""

    code = "storage_schema_error"


class StorageDataError(StorageError):
    """A stored value could not be decoded (e.g. a cell was edited by hand)."""

    code = "storage_data_error"


class ConstraintViolation(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "constraint_violation"

    def __init__(self, table: str, constraint: str, message: str, **extra: Any) -> None:
        super().__init__(message, details={"table": table, "constraint": constraint, **extra})
        self.table = table
        self.constraint = constraint


class RowNotFound(NotFoundError):
    def __init__(self, table: str, pk: object) -> None:
        super().__init__(f"No row in {table} with id {pk}", details={"table": table})
