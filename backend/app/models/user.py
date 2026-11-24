"""Users, saved products, price alerts and audit log."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk, str_enum
from app.models.comparison import PINCODE_CHECK
from app.models.enums import UserRole


class User(Timestamps, Base):
    """Application profile. `id` equals the Supabase auth user id (no server default)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            f"default_pincode IS NULL OR {PINCODE_CHECK.replace('pincode', 'default_pincode')}",
            name="default_pincode_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(
        str_enum(UserRole, "user_role"),
        default=UserRole.USER,
        server_default=UserRole.USER.value,
    )
    default_pincode: Mapped[str | None] = mapped_column(String(6))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SavedProduct(UUIDPk, Timestamps, Base):
    __tablename__ = "saved_products"
    __table_args__ = (UniqueConstraint("user_id", "variant_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    note: Mapped[str | None] = mapped_column(String(500))


class PriceAlert(UUIDPk, Timestamps, Base):
    __tablename__ = "price_alerts"
    __table_args__ = (
        Index("ix_price_alerts_active_variant", "is_active", "variant_id"),
        Index("ix_price_alerts_user", "user_id"),
        CheckConstraint("target_price > 0", name="target_price_positive"),
        CheckConstraint(PINCODE_CHECK, name="pincode_format"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    pincode: Mapped[str] = mapped_column(String(6))
    target_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDPk, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_occurred", "occurred_at"),)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str | None] = mapped_column(Text)
    # Salted hash only; raw IPs are never stored.
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
