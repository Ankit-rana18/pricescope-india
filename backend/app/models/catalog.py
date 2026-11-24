"""Catalog: marketplaces, canonical products, variants, identifiers, listings."""

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
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk, str_enum
from app.models.enums import IdentifierType, MarketplaceCode, QuantityUnit


class Marketplace(UUIDPk, Timestamps, Base):
    __tablename__ = "marketplaces"

    code: Mapped[MarketplaceCode] = mapped_column(
        str_enum(MarketplaceCode, "marketplace_code"), unique=True
    )
    name: Mapped[str] = mapped_column(String(80))
    base_domains: Mapped[list[str]] = mapped_column(ARRAY(String(253)))
    logo_path: Mapped[str | None] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Declared adapter capabilities (search_by_gtin, location, fees, coupons ...).
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


class Product(UUIDPk, Timestamps, Base):
    """Canonical product, independent of any marketplace listing."""

    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_brand_model", "brand", "model"),
        Index(
            "ix_products_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    slug: Mapped[str] = mapped_column(String(200), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(120))
    manufacturer: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    image_url: Mapped[str | None] = mapped_column(Text)

    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product")


class ProductVariant(UUIDPk, Timestamps, Base):
    """A purchasable variant: exact size, colour, net quantity and pack count."""

    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("product_id", "variant_key"),
        CheckConstraint("pack_count >= 1", name="pack_count_positive"),
        CheckConstraint("quantity_value IS NULL OR quantity_value > 0", name="quantity_positive"),
        CheckConstraint(
            "(quantity_value IS NULL) = (quantity_unit IS NULL)", name="quantity_unit_pair"
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    # Deterministic key built from normalized attributes, e.g. "500g|x2|black".
    variant_key: Mapped[str] = mapped_column(String(200))
    size: Mapped[str | None] = mapped_column(String(60))
    colour: Mapped[str | None] = mapped_column(String(60))
    # Per-unit quantity in canonical base unit (g / ml / unit).
    quantity_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    quantity_unit: Mapped[QuantityUnit | None] = mapped_column(
        str_enum(QuantityUnit, "quantity_unit")
    )
    pack_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")

    product: Mapped[Product] = relationship(back_populates="variants")
    identifiers: Mapped[list["ProductIdentifier"]] = relationship(back_populates="variant")


class ProductIdentifier(UUIDPk, Timestamps, Base):
    __tablename__ = "product_identifiers"
    __table_args__ = (UniqueConstraint("type", "value"),)

    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[IdentifierType] = mapped_column(str_enum(IdentifierType, "identifier_type"))
    value: Mapped[str] = mapped_column(String(64), index=True)

    variant: Mapped[ProductVariant] = relationship(back_populates="identifiers")


class MarketplaceProduct(UUIDPk, Timestamps, Base):
    """A listing on one marketplace. variant_id is set once matched to a canonical variant."""

    __tablename__ = "marketplace_products"
    __table_args__ = (UniqueConstraint("marketplace_id", "external_id"),)

    marketplace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplaces.id", ondelete="RESTRICT")
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(128))
    # Nullable: demo listings have no real page, so no URL is stored or linked.
    url: Mapped[str | None] = mapped_column(Text)
    title_raw: Mapped[str] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    marketplace: Mapped[Marketplace] = relationship()
    variant: Mapped[ProductVariant | None] = relationship()
