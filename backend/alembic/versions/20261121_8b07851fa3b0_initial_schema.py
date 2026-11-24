"""initial schema

Revision ID: 8b07851fa3b0
Revises:
Create Date: 2026-11-21 12:58:04.040160
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8b07851fa3b0"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extensions: gen_random_uuid (pgcrypto), trigram title search, case-insensitive email.
    # Not dropped on downgrade: they may be shared with other schemas.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "marketplaces",
        sa.Column(
            "code",
            sa.Enum(
                "AMAZON_IN",
                "FLIPKART",
                "BLINKIT",
                "ZEPTO",
                "BIGBASKET",
                name="marketplace_code",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("base_domains", postgresql.ARRAY(sa.String(length=253)), nullable=False),
        sa.Column("logo_path", sa.String(length=255), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplaces")),
        sa.UniqueConstraint("code", name=op.f("uq_marketplaces_code")),
    )
    op.create_table(
        "pincode_directory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pincode", sa.String(length=6), nullable=False),
        sa.Column("office_name", sa.String(length=200), nullable=False),
        sa.Column("district", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=120), nullable=False),
        sa.CheckConstraint(
            "pincode ~ '^[1-9][0-9]{5}$'", name=op.f("ck_pincode_directory_pincode_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pincode_directory")),
    )
    op.create_index(
        op.f("ix_pincode_directory_pincode"), "pincode_directory", ["pincode"], unique=False
    )
    op.create_table(
        "products",
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=True),
        sa.Column("manufacturer", sa.String(length=200), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("slug", name=op.f("uq_products_slug")),
    )
    op.create_index("ix_products_brand_model", "products", ["brand", "model"], unique=False)
    op.create_index(op.f("ix_products_category"), "products", ["category"], unique=False)
    op.create_index(
        "ix_products_title_trgm",
        "products",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "admin",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="user",
            nullable=False,
        ),
        sa.Column("default_pincode", sa.String(length=6), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "default_pincode IS NULL OR default_pincode ~ '^[1-9][0-9]{5}$'",
            name=op.f("ck_users_default_pincode_format"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "audit_logs",
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False)
    op.create_index("ix_audit_logs_occurred", "audit_logs", ["occurred_at"], unique=False)
    op.create_table(
        "delivery_fees",
        sa.Column("marketplace_id", sa.UUID(), nullable=False),
        sa.Column(
            "fee_type",
            sa.Enum(
                "DELIVERY",
                "HANDLING",
                "PLATFORM",
                "SMALL_CART",
                "OTHER",
                name="fee_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "API",
                "PUBLISHED_POLICY",
                name="fee_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_delivery_fees_amount_non_negative")),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name=op.f("ck_delivery_fees_effective_range"),
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            name=op.f("fk_delivery_fees_marketplace_id_marketplaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_fees")),
    )
    op.create_index(
        "ix_delivery_fees_lookup",
        "delivery_fees",
        ["marketplace_id", "fee_type", "effective_from"],
        unique=False,
    )
    op.create_table(
        "integration_credentials",
        sa.Column("marketplace_id", sa.UUID(), nullable=False),
        sa.Column("key_name", sa.String(length=80), nullable=False),
        sa.Column("secret_ref", sa.String(length=500), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "secret_ref ~ '^(env:[A-Z][A-Z0-9_]*|aws-sm:.+|gcp-sm:.+)$'",
            name=op.f("ck_integration_credentials_secret_ref_is_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            name=op.f("fk_integration_credentials_marketplace_id_marketplaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_credentials")),
        sa.UniqueConstraint(
            "marketplace_id",
            "key_name",
            name=op.f("uq_integration_credentials_marketplace_id_key_name"),
        ),
    )
    op.create_table(
        "integration_health_logs",
        sa.Column("marketplace_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "LIVE",
                "DEGRADED",
                "DOWN",
                "NOT_CONFIGURED",
                "UNSUPPORTED",
                "DEMO",
                name="integration_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name=op.f("ck_integration_health_logs_latency_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            name=op.f("fk_integration_health_logs_marketplace_id_marketplaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_health_logs")),
    )
    op.create_index(
        "ix_integration_health_logs_mkt_occurred",
        "integration_health_logs",
        ["marketplace_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "product_variants",
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("variant_key", sa.String(length=200), nullable=False),
        sa.Column("size", sa.String(length=60), nullable=True),
        sa.Column("colour", sa.String(length=60), nullable=True),
        sa.Column("quantity_value", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column(
            "quantity_unit",
            sa.Enum(
                "g",
                "ml",
                "unit",
                name="quantity_unit",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("pack_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(quantity_value IS NULL) = (quantity_unit IS NULL)",
            name=op.f("ck_product_variants_quantity_unit_pair"),
        ),
        sa.CheckConstraint("pack_count >= 1", name=op.f("ck_product_variants_pack_count_positive")),
        sa.CheckConstraint(
            "quantity_value IS NULL OR quantity_value > 0",
            name=op.f("ck_product_variants_quantity_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_variants_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_variants")),
        sa.UniqueConstraint(
            "product_id", "variant_key", name=op.f("uq_product_variants_product_id_variant_key")
        ),
    )
    op.create_index(
        op.f("ix_product_variants_product_id"), "product_variants", ["product_id"], unique=False
    )
    op.create_table(
        "marketplace_products",
        sa.Column("marketplace_id", sa.UUID(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title_raw", sa.String(length=1000), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            name=op.f("fk_marketplace_products_marketplace_id_marketplaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_marketplace_products_variant_id_product_variants"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplace_products")),
        sa.UniqueConstraint(
            "marketplace_id",
            "external_id",
            name=op.f("uq_marketplace_products_marketplace_id_external_id"),
        ),
    )
    op.create_index(
        op.f("ix_marketplace_products_variant_id"),
        "marketplace_products",
        ["variant_id"],
        unique=False,
    )
    op.create_table(
        "price_alerts",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column("pincode", sa.String(length=6), nullable=False),
        sa.Column("target_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pincode ~ '^[1-9][0-9]{5}$'", name=op.f("ck_price_alerts_pincode_format")
        ),
        sa.CheckConstraint("target_price > 0", name=op.f("ck_price_alerts_target_price_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_price_alerts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_price_alerts_variant_id_product_variants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_alerts")),
    )
    op.create_index(
        "ix_price_alerts_active_variant", "price_alerts", ["is_active", "variant_id"], unique=False
    )
    op.create_index("ix_price_alerts_user", "price_alerts", ["user_id"], unique=False)
    op.create_table(
        "product_identifiers",
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "GTIN8",
                "GTIN12",
                "GTIN13",
                "GTIN14",
                "ASIN",
                "FSN",
                "SKU",
                "MPN",
                name="identifier_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_product_identifiers_variant_id_product_variants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_identifiers")),
        sa.UniqueConstraint("type", "value", name=op.f("uq_product_identifiers_type_value")),
    )
    op.create_index(
        op.f("ix_product_identifiers_value"), "product_identifiers", ["value"], unique=False
    )
    op.create_index(
        op.f("ix_product_identifiers_variant_id"),
        "product_identifiers",
        ["variant_id"],
        unique=False,
    )
    op.create_table(
        "saved_products",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_products_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_saved_products_variant_id_product_variants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_products")),
        sa.UniqueConstraint(
            "user_id", "variant_id", name=op.f("uq_saved_products_user_id_variant_id")
        ),
    )
    op.create_table(
        "comparisons",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_marketplace_product_id", sa.UUID(), nullable=True),
        sa.Column("pincode", sa.String(length=6), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "COMPLETE",
                "PARTIAL",
                "FAILED",
                name="comparison_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "data_mode",
            sa.Enum(
                "LIVE",
                "DEMO",
                name="data_mode",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pincode ~ '^[1-9][0-9]{5}$'", name=op.f("ck_comparisons_pincode_format")
        ),
        sa.ForeignKeyConstraint(
            ["source_marketplace_product_id"],
            ["marketplace_products.id"],
            name=op.f("fk_comparisons_source_marketplace_product_id_marketplace_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_comparisons_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comparisons")),
    )
    op.create_index(op.f("ix_comparisons_pincode"), "comparisons", ["pincode"], unique=False)
    op.create_index(
        "ix_comparisons_user_created", "comparisons", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "location_checks",
        sa.Column("marketplace_product_id", sa.UUID(), nullable=False),
        sa.Column("pincode", sa.String(length=6), nullable=False),
        sa.Column(
            "verification",
            sa.Enum(
                "VERIFIED",
                "UNVERIFIABLE",
                "UNAVAILABLE",
                "NEEDS_PRECISE_LOCATION",
                name="location_verification",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("serviceable", sa.Boolean(), nullable=True),
        sa.Column("eta_text", sa.String(length=120), nullable=True),
        sa.Column(
            "data_mode",
            sa.Enum(
                "LIVE",
                "DEMO",
                name="data_mode",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "pincode ~ '^[1-9][0-9]{5}$'", name=op.f("ck_location_checks_pincode_format")
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_product_id"],
            ["marketplace_products.id"],
            name=op.f("fk_location_checks_marketplace_product_id_marketplace_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_location_checks")),
    )
    op.create_index(
        "ix_location_checks_listing_pin_checked",
        "location_checks",
        ["marketplace_product_id", "pincode", "checked_at"],
        unique=False,
    )
    op.create_table(
        "price_history",
        sa.Column("marketplace_product_id", sa.UUID(), nullable=False),
        sa.Column("pincode", sa.String(length=6), nullable=True),
        sa.Column("item_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("mrp", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("final_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("final_price_complete", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "data_mode",
            sa.Enum(
                "LIVE",
                "DEMO",
                name="data_mode",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$'",
            name=op.f("ck_price_history_pincode_format"),
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_product_id"],
            ["marketplace_products.id"],
            name=op.f("fk_price_history_marketplace_product_id_marketplace_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_history")),
    )
    op.create_index(
        "ix_price_history_listing_observed",
        "price_history",
        ["marketplace_product_id", "observed_at"],
        unique=False,
    )
    op.create_table(
        "comparison_results",
        sa.Column("comparison_id", sa.UUID(), nullable=False),
        sa.Column("marketplace_id", sa.UUID(), nullable=False),
        sa.Column("marketplace_product_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "OK",
                "NOT_FOUND",
                "FAILED",
                "UNSUPPORTED",
                "NOT_CONFIGURED",
                name="result_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "match_class",
            sa.Enum(
                "EXACT",
                "PROBABLE",
                "MISMATCH",
                "UNVERIFIED",
                name="match_class",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("match_score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "match_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("mrp", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("item_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("verified_discount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("delivery_fee", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "delivery_fee_status",
            sa.Enum(
                "KNOWN",
                "UNKNOWN",
                "NOT_APPLICABLE",
                name="delivery_fee_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column("handling_fee", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "handling_fee_status",
            sa.Enum(
                "KNOWN",
                "UNKNOWN",
                "NOT_APPLICABLE",
                name="handling_fee_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column("platform_fee", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "platform_fee_status",
            sa.Enum(
                "KNOWN",
                "UNKNOWN",
                "NOT_APPLICABLE",
                name="platform_fee_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column("other_fees", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "other_fees_status",
            sa.Enum(
                "KNOWN",
                "UNKNOWN",
                "NOT_APPLICABLE",
                name="other_fees_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column(
            "coupons", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("final_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("final_price_complete", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "availability",
            sa.Enum(
                "IN_STOCK",
                "OUT_OF_STOCK",
                "UNKNOWN",
                name="availability",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column(
            "location_verification",
            sa.Enum(
                "VERIFIED",
                "UNVERIFIABLE",
                "UNAVAILABLE",
                "NEEDS_PRECISE_LOCATION",
                name="location_verification",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("eta_text", sa.String(length=120), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT final_price_complete OR final_price IS NOT NULL",
            name=op.f("ck_comparison_results_complete_price_has_value"),
        ),
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name=op.f("ck_comparison_results_match_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            ["comparisons.id"],
            name=op.f("fk_comparison_results_comparison_id_comparisons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            name=op.f("fk_comparison_results_marketplace_id_marketplaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_product_id"],
            ["marketplace_products.id"],
            name=op.f("fk_comparison_results_marketplace_product_id_marketplace_products"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comparison_results")),
        sa.UniqueConstraint(
            "comparison_id",
            "marketplace_id",
            name=op.f("uq_comparison_results_comparison_id_marketplace_id"),
        ),
    )
    op.create_index(
        op.f("ix_comparison_results_comparison_id"),
        "comparison_results",
        ["comparison_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_comparison_results_comparison_id"), table_name="comparison_results")
    op.drop_table("comparison_results")
    op.drop_index("ix_price_history_listing_observed", table_name="price_history")
    op.drop_table("price_history")
    op.drop_index("ix_location_checks_listing_pin_checked", table_name="location_checks")
    op.drop_table("location_checks")
    op.drop_index("ix_comparisons_user_created", table_name="comparisons")
    op.drop_index(op.f("ix_comparisons_pincode"), table_name="comparisons")
    op.drop_table("comparisons")
    op.drop_table("saved_products")
    op.drop_index(op.f("ix_product_identifiers_variant_id"), table_name="product_identifiers")
    op.drop_index(op.f("ix_product_identifiers_value"), table_name="product_identifiers")
    op.drop_table("product_identifiers")
    op.drop_index("ix_price_alerts_user", table_name="price_alerts")
    op.drop_index("ix_price_alerts_active_variant", table_name="price_alerts")
    op.drop_table("price_alerts")
    op.drop_index(op.f("ix_marketplace_products_variant_id"), table_name="marketplace_products")
    op.drop_table("marketplace_products")
    op.drop_index(op.f("ix_product_variants_product_id"), table_name="product_variants")
    op.drop_table("product_variants")
    op.drop_index("ix_integration_health_logs_mkt_occurred", table_name="integration_health_logs")
    op.drop_table("integration_health_logs")
    op.drop_table("integration_credentials")
    op.drop_index("ix_delivery_fees_lookup", table_name="delivery_fees")
    op.drop_table("delivery_fees")
    op.drop_index("ix_audit_logs_occurred", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_index(
        "ix_products_title_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_products_category"), table_name="products")
    op.drop_index("ix_products_brand_model", table_name="products")
    op.drop_table("products")
    op.drop_index(op.f("ix_pincode_directory_pincode"), table_name="pincode_directory")
    op.drop_table("pincode_directory")
    op.drop_table("marketplaces")
