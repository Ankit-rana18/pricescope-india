"""estimated charge status

Allows ESTIMATED in the four fee-status columns of comparison_results: a fee filled in
from an admin-entered published policy (with source link and dates), never confirmed for
the shopper's cart. Enum CHECK constraints are not detected by autogenerate, so this
migration is written by hand.

Revision ID: c7e2a90d4f11
Revises: 24111efb78b7
Create Date: 2026-11-24 18:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7e2a90d4f11"
down_revision: str | None = "24111efb78b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("delivery_fee", "handling_fee", "platform_fee", "other_fees")
OLD = ("KNOWN", "UNKNOWN", "NOT_APPLICABLE")
NEW = ("KNOWN", "ESTIMATED", "UNKNOWN", "NOT_APPLICABLE")


def _replace(values: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{v}'" for v in values)
    for col in COLUMNS:
        name = f"ck_comparison_results_{col}_status"
        op.drop_constraint(op.f(name), "comparison_results", type_="check")
        op.create_check_constraint(
            op.f(name), "comparison_results", f"{col}_status IN ({allowed})"
        )


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    # Fails if ESTIMATED rows exist, which is the safe outcome.
    _replace(OLD)
