"""seed marketplaces

Seeds the five supported marketplaces. Capabilities describe the *intended* legitimate
integration route only; every capability flag starts as "unverified" and is updated by
the adapter health probe once real credentials and real API calls have been verified.

Revision ID: a1c3e5f70002
Revises: 8b07851fa3b0
Create Date: 2026-11-21 13:10:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f70002"
down_revision: str | None = "8b07851fa3b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNVERIFIED = {
    "search_by_gtin": "unverified",
    "search_by_text": "unverified",
    "location": "unverified",
    "fees": "unverified",
    "coupons": "unverified",
}

MARKETPLACES = [
    {
        "code": "AMAZON_IN",
        "name": "Amazon India",
        "base_domains": ["amazon.in", "www.amazon.in", "amzn.in", "amzn.to"],
        "logo_path": "/marketplaces/amazon.svg",
        "integration": "Amazon Creators API (Associates eligibility required)",
    },
    {
        "code": "FLIPKART",
        "name": "Flipkart",
        "base_domains": ["flipkart.com", "www.flipkart.com", "dl.flipkart.com"],
        "logo_path": "/marketplaces/flipkart.svg",
        "integration": "Flipkart Affiliate API / product feeds (approval required)",
    },
    {
        "code": "BLINKIT",
        "name": "Blinkit",
        "base_domains": ["blinkit.com", "www.blinkit.com"],
        "logo_path": "/marketplaces/blinkit.svg",
        "integration": "No public API; licensed data provider or partnership required",
    },
    {
        "code": "ZEPTO",
        "name": "Zepto",
        "base_domains": ["zeptonow.com", "www.zeptonow.com"],
        "logo_path": "/marketplaces/zepto.svg",
        "integration": "No public API; licensed data provider or partnership required",
    },
    {
        "code": "BIGBASKET",
        "name": "BigBasket",
        "base_domains": ["bigbasket.com", "www.bigbasket.com"],
        "logo_path": "/marketplaces/bigbasket.svg",
        "integration": "No public API; licensed data provider or partnership required",
    },
]


def upgrade() -> None:
    stmt = sa.text(
        "INSERT INTO marketplaces (code, name, base_domains, logo_path, capabilities) "
        "VALUES (:code, :name, :base_domains, :logo_path, CAST(:capabilities AS jsonb)) "
        "ON CONFLICT (code) DO NOTHING"
    )
    conn = op.get_bind()
    for m in MARKETPLACES:
        conn.execute(
            stmt,
            {
                "code": m["code"],
                "name": m["name"],
                "base_domains": m["base_domains"],
                "logo_path": m["logo_path"],
                "capabilities": json.dumps({"integration": m["integration"], **_UNVERIFIED}),
            },
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM marketplaces WHERE code = ANY(:codes)"),
        {"codes": [m["code"] for m in MARKETPLACES]},
    )
