"""Python equivalents of the database CHECK constraints.

Google Sheets enforces nothing, so every named CHECK constraint in the SQLAlchemy models has
a rule here, keyed by (table, constraint name). Both storage backends run these rules before
writing, so behaviour is identical. `tests/unit/test_storage_rules.py` fails if a CHECK
constraint is added to the models without a matching rule.
"""

import re
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

Row = Mapping[str, Any]
Rule = Callable[[Row], bool]

PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")
SECRET_REF_RE = re.compile(r"^(env:[A-Z][A-Z0-9_]*|aws-sm:.+|gcp-sm:.+)$")


def _pincode(column: str, *, nullable: bool = False) -> Rule:
    def rule(row: Row) -> bool:
        value = row.get(column)
        if value is None:
            return nullable
        return bool(PINCODE_RE.fullmatch(str(value)))

    return rule


def _null_or(column: str, predicate: Callable[[Any], bool]) -> Rule:
    return lambda row: row.get(column) is None or predicate(row[column])


RULES: dict[tuple[str, str], Rule] = {
    # catalog
    ("product_variants", "pack_count_positive"): lambda r: r["pack_count"] >= 1,
    ("product_variants", "quantity_positive"): _null_or("quantity_value", lambda v: v > 0),
    ("product_variants", "quantity_unit_pair"): lambda r: (
        (r.get("quantity_value") is None) == (r.get("quantity_unit") is None)
    ),
    # comparisons
    ("comparisons", "pincode_format"): _pincode("pincode"),
    ("comparison_results", "match_score_range"): _null_or(
        "match_score", lambda v: Decimal(0) <= v <= Decimal(1)
    ),
    ("comparison_results", "complete_price_has_value"): lambda r: (
        not r.get("final_price_complete") or r.get("final_price") is not None
    ),
    ("price_history", "pincode_format"): _pincode("pincode", nullable=True),
    ("location_checks", "pincode_format"): _pincode("pincode"),
    ("delivery_fees", "amount_non_negative"): lambda r: r["amount"] >= 0,
    ("delivery_fees", "effective_range"): lambda r: (
        r.get("effective_to") is None or r["effective_to"] >= r["effective_from"]
    ),
    # users
    ("users", "default_pincode_format"): _pincode("default_pincode", nullable=True),
    ("price_alerts", "target_price_positive"): lambda r: r["target_price"] > 0,
    ("price_alerts", "pincode_format"): _pincode("pincode"),
    # integrations
    ("integration_credentials", "secret_ref_is_reference"): lambda r: bool(
        SECRET_REF_RE.fullmatch(str(r["secret_ref"]))
    ),
    ("integration_health_logs", "latency_non_negative"): _null_or("latency_ms", lambda v: v >= 0),
    ("pincode_directory", "pincode_format"): _pincode("pincode"),
}
