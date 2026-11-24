"""Integration credential references, health logs and the PIN-code directory."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk, str_enum
from app.models.comparison import PINCODE_CHECK
from app.models.enums import IntegrationStatus


class IntegrationCredential(UUIDPk, Timestamps, Base):
    """Pointer to where a secret lives. NEVER the secret itself.

    `secret_ref` is an environment variable name (``env:AMAZON_CREATORS_CREDENTIAL_SECRET``)
    or a secrets-manager reference (``aws-sm:arn:...``). Not exposed by any API.
    """

    __tablename__ = "integration_credentials"
    __table_args__ = (
        UniqueConstraint("marketplace_id", "key_name"),
        CheckConstraint(
            "secret_ref ~ '^(env:[A-Z][A-Z0-9_]*|aws-sm:.+|gcp-sm:.+)$'",
            name="secret_ref_is_reference",
        ),
    )

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplaces.id", ondelete="CASCADE")
    )
    key_name: Mapped[str] = mapped_column(String(80))
    secret_ref: Mapped[str] = mapped_column(String(500))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationHealthLog(UUIDPk, Base):
    __tablename__ = "integration_health_logs"
    __table_args__ = (
        Index("ix_integration_health_logs_mkt_occurred", "marketplace_id", "occurred_at"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_non_negative"),
    )

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplaces.id", ondelete="CASCADE")
    )
    status: Mapped[IntegrationStatus] = mapped_column(
        str_enum(IntegrationStatus, "integration_status")
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PincodeDirectory(Base):
    """India Post office directory (open data). One row per post office."""

    __tablename__ = "pincode_directory"
    __table_args__ = (CheckConstraint(PINCODE_CHECK, name="pincode_format"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pincode: Mapped[str] = mapped_column(String(6), index=True)
    office_name: Mapped[str] = mapped_column(String(200))
    district: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(120))
