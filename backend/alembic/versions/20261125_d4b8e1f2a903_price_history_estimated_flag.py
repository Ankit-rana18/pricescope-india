"""price history estimated flag

Records whether a saved final price includes a fee estimated from a published policy, so
history views never present an estimate as a confirmed price.

Revision ID: d4b8e1f2a903
Revises: c7e2a90d4f11
Create Date: 2026-11-25 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4b8e1f2a903"
down_revision: str | None = "c7e2a90d4f11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_history",
        sa.Column("final_price_estimated", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("price_history", "final_price_estimated")
