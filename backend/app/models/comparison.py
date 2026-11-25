"""Comparisons, per-marketplace results, price history, location checks, fees."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import (
    Availability,
    ChargeStatus,
    ComparisonStatus,
    DataMode,
    FeeSource,
    FeeType,
    LocationVerification,
    MatchClass,
    ResultStatus,
)

PINCODE_CHECK = "pincode ~ '^[1-9][0-9]{5}$'"


class Comparison(UUIDPk, Timestamps, Base):
    __tablename__ = "comparisons"
    __table_args__ = (
        CheckConstraint(PINCODE_CHECK, name="pincode_format"),
        Index("ix_comparisons_user_created", "user_id", "created_at"),
    )

    # Nullable: anonymous comparisons are allowed.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source_url: Mapped[str] = mapped_column(Text)
    source_marketplace_product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketplace_products.id", ondelete="SET NULL")
    )
    pincode: Mapped[str] = mapped_column(String(6), index=True)
    status: Mapped[ComparisonStatus] = mapped_column(
        str_enum(ComparisonStatus, "comparison_status"),
        default=ComparisonStatus.PENDING,
        server_default=ComparisonStatus.PENDING.value,
    )
    data_mode: Mapped[DataMode] = mapped_column(str_enum(DataMode, "data_mode"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list["ComparisonResult"]] = relationship(
        back_populates="comparison", cascade="all, delete-orphan"
    )


def _charge(name: str) -> tuple[Mapped[Decimal | None], Mapped[ChargeStatus]]:
    """Amount + explicit status pair. A NULL amount is unknown, never zero."""
    amount: Mapped[Decimal | None] = mapped_column(name, Numeric(12, 2))
    status: Mapped[ChargeStatus] = mapped_column(
        f"{name}_status",
        str_enum(ChargeStatus, f"{name}_status"),
        nullable=False,
        default=ChargeStatus.UNKNOWN,
        server_default=ChargeStatus.UNKNOWN.value,
    )
    return amount, status


class ComparisonResult(UUIDPk, Timestamps, Base):
    __tablename__ = "comparison_results"
    __table_args__ = (
        UniqueConstraint("comparison_id", "marketplace_id"),
        CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="match_score_range",
        ),
        # A complete final price must actually have a value.
        CheckConstraint(
            "NOT final_price_complete OR final_price IS NOT NULL",
            name="complete_price_has_value",
        ),
    )

    comparison_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comparisons.id", ondelete="CASCADE"), index=True
    )
    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplaces.id", ondelete="RESTRICT")
    )
    marketplace_product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketplace_products.id", ondelete="SET NULL")
    )
    status: Mapped[ResultStatus] = mapped_column(str_enum(ResultStatus, "result_status"))
    match_class: Mapped[MatchClass | None] = mapped_column(str_enum(MatchClass, "match_class"))
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    match_reasons: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")

    mrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    item_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    verified_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    delivery_fee, delivery_fee_status = _charge("delivery_fee")
    handling_fee, handling_fee_status = _charge("handling_fee")
    platform_fee, platform_fee_status = _charge("platform_fee")
    other_fees, other_fees_status = _charge("other_fees")
    # Coupons shown separately; only subtracted when eligibility is verified.
    coupons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    assumptions: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    final_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    final_price_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    availability: Mapped[Availability] = mapped_column(
        str_enum(Availability, "availability"),
        default=Availability.UNKNOWN,
        server_default=Availability.UNKNOWN.value,
    )
    location_verification: Mapped[LocationVerification | None] = mapped_column(
        str_enum(LocationVerification, "location_verification")
    )
    eta_text: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    # Card / bank offers: shown separately, never part of final_price.
    card_offers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    best_card_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_after_best_card: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Notes per fee, e.g. {"other_fees": "Small-cart fee"}.
    charge_notes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    # Other listings found on this marketplace (probable matches, rejected variants).
    other_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    attempts: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    comparison: Mapped[Comparison] = relationship(back_populates="results")


class PriceHistory(UUIDPk, Base):
    __tablename__ = "price_history"
    __table_args__ = (
        Index("ix_price_history_listing_observed", "marketplace_product_id", "observed_at"),
        CheckConstraint(f"pincode IS NULL OR {PINCODE_CHECK}", name="pincode_format"),
    )

    marketplace_product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_products.id", ondelete="CASCADE")
    )
    pincode: Mapped[str | None] = mapped_column(String(6))
    item_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    final_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    final_price_complete: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Includes a fee estimated from a published policy (not confirmed for the cart).
    final_price_estimated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    data_mode: Mapped[DataMode] = mapped_column(str_enum(DataMode, "data_mode"))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LocationCheck(UUIDPk, Base):
    __tablename__ = "location_checks"
    __table_args__ = (
        Index(
            "ix_location_checks_listing_pin_checked",
            "marketplace_product_id",
            "pincode",
            "checked_at",
        ),
        CheckConstraint(PINCODE_CHECK, name="pincode_format"),
    )

    marketplace_product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_products.id", ondelete="CASCADE")
    )
    pincode: Mapped[str] = mapped_column(String(6))
    verification: Mapped[LocationVerification] = mapped_column(
        str_enum(LocationVerification, "location_verification")
    )
    # NULL = not determined. Never assume serviceable.
    serviceable: Mapped[bool | None] = mapped_column(Boolean)
    eta_text: Mapped[str | None] = mapped_column(String(120))
    data_mode: Mapped[DataMode] = mapped_column(str_enum(DataMode, "data_mode"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryFee(UUIDPk, Timestamps, Base):
    """Admin-entered published fee policy, always with a source URL and effective date."""

    __tablename__ = "delivery_fees"
    __table_args__ = (
        Index("ix_delivery_fees_lookup", "marketplace_id", "fee_type", "effective_from"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="effective_range"
        ),
    )

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplaces.id", ondelete="CASCADE")
    )
    fee_type: Mapped[FeeType] = mapped_column(str_enum(FeeType, "fee_type"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    source: Mapped[FeeSource] = mapped_column(str_enum(FeeSource, "fee_source"))
    source_url: Mapped[str] = mapped_column(Text)
    # e.g. {"min_cart_value": 199, "applies_below": true}
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
