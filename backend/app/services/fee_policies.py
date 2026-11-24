"""Published fee policies: fill in fees a marketplace didn't report, clearly as estimates.

Example: a marketplace's help page says "₹40 delivery on orders below ₹500". When an offer
comes back with an UNKNOWN delivery fee, that policy turns it into an ESTIMATED charge,
labelled with its source. Rules:

* Only UNKNOWN charges are filled. A value the marketplace reported always wins.
* A policy needs a source link (https), an effective date range, and conditions this
  module understands. Unknown condition keys -> the policy is skipped, never guessed.
* If two applicable policies disagree for the same fee, none is applied.
* Estimated prices are shown and can be ranked, but never count as a verified price.

Live policies are rows in the ``delivery_fees`` table (``source = PUBLISHED_POLICY``),
added by an admin; in Google Sheets they can be typed straight into that tab. Demo mode
uses the fictional policies in the demo catalog instead: demo and live never mix.
"""

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import structlog
from pricescope_integrations.models import Charge, ChargeStatus, CouponEligibility, Offer

from app.models.enums import FeeSource, FeeType, MarketplaceCode
from app.services.pricing import inr
from app.storage.base import TableStore

log = structlog.get_logger(__name__)

CHARGE_FOR_FEE = {
    FeeType.DELIVERY: "delivery_fee",
    FeeType.HANDLING: "handling_fee",
    FeeType.PLATFORM: "platform_fee",
    FeeType.SMALL_CART: "other_fees",
    FeeType.OTHER: "other_fees",
}
FEE_LABEL = {
    FeeType.DELIVERY: "delivery",
    FeeType.HANDLING: "handling",
    FeeType.PLATFORM: "platform fee",
    FeeType.SMALL_CART: "small-cart fee",
    FeeType.OTHER: "fee",
}
SUPPORTED_CONDITIONS = {"below_order_value", "pincode_prefixes"}


@dataclass(frozen=True)
class FeePolicy:
    marketplace: MarketplaceCode
    fee_type: FeeType
    amount: Decimal
    effective_from: date
    effective_to: date | None
    source_url: str | None  # None only for fictional demo policies
    conditions: dict[str, Any] = field(default_factory=dict)
    demo: bool = False

    def problems(self) -> list[str]:
        out = []
        unknown = set(self.conditions) - SUPPORTED_CONDITIONS
        if unknown:
            out.append(f"unsupported conditions {sorted(unknown)}")
        if not self.demo and not (self.source_url or "").startswith("https://"):
            out.append("needs an https source link")
        if self.amount < 0:
            out.append("negative amount")
        return out

    def in_effect(self, today: date) -> bool:
        return self.effective_from <= today and (
            self.effective_to is None or today <= self.effective_to
        )

    def amount_for(self, order_value: Decimal, pincode: str) -> Decimal | None:
        """The fee under this policy, or None if the policy doesn't cover this order."""
        prefixes = self.conditions.get("pincode_prefixes")
        if prefixes is not None and not any(pincode.startswith(str(p)) for p in prefixes):
            return None
        threshold = self.conditions.get("below_order_value")
        if threshold is not None:
            try:
                limit = Decimal(str(threshold))
            except InvalidOperation:
                return None
            return self.amount if order_value < limit else Decimal("0")
        return self.amount

    def describe(self, applied: Decimal) -> str:
        what = FEE_LABEL[self.fee_type]
        origin = "demo published policy (fictional)" if self.demo else "published policy"
        cond = ""
        if "below_order_value" in self.conditions:
            limit = Decimal(str(self.conditions["below_order_value"]))
            cond = f" ({inr(self.amount)} on orders below {inr(limit)})"
        return f"Estimated {what} {inr(applied)} per {origin}{cond}; not confirmed for your cart"


class FeePolicySource(Protocol):
    def for_marketplace(self, marketplace: MarketplaceCode) -> list[FeePolicy]: ...


class StaticFeePolicies:
    def __init__(self, policies: Iterable[FeePolicy] = ()) -> None:
        self._policies = list(policies)

    def for_marketplace(self, marketplace: MarketplaceCode) -> list[FeePolicy]:
        return [p for p in self._policies if p.marketplace == marketplace]


class StoreFeePolicies:
    """Reads live policies from storage, cached for a few minutes."""

    def __init__(self, store: TableStore, ttl_seconds: float = 300) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self._cached: list[FeePolicy] = []
        self._loaded_at = -1e9

    def _load(self) -> list[FeePolicy]:
        if time.monotonic() - self._loaded_at < self._ttl:
            return self._cached
        codes = {r["id"]: MarketplaceCode(r["code"]) for r in self._store.find("marketplaces")}
        policies = []
        for row in self._store.find("delivery_fees", {"source": FeeSource.PUBLISHED_POLICY}):
            policy = FeePolicy(
                marketplace=codes[row["marketplace_id"]],
                fee_type=FeeType(row["fee_type"]),
                amount=row["amount"],
                effective_from=row["effective_from"],
                effective_to=row.get("effective_to"),
                source_url=row.get("source_url"),
                conditions=row.get("conditions") or {},
            )
            if problems := policy.problems():
                log.warning("fee_policy_skipped", policy_id=str(row["id"]), problems=problems)
                continue
            policies.append(policy)
        self._cached, self._loaded_at = policies, time.monotonic()
        return policies

    def for_marketplace(self, marketplace: MarketplaceCode) -> list[FeePolicy]:
        try:
            return [p for p in self._load() if p.marketplace == marketplace]
        except Exception:  # policies are optional; never break a comparison over them
            log.exception("fee_policies_unavailable")
            return []


def demo_policies(raw: Iterable[dict[str, Any]]) -> StaticFeePolicies:
    return StaticFeePolicies(
        FeePolicy(
            marketplace=MarketplaceCode(p["marketplace"]),
            fee_type=FeeType(p["fee_type"]),
            amount=Decimal(p["amount"]),
            effective_from=date.fromisoformat(p["effective_from"]),
            effective_to=date.fromisoformat(p["effective_to"]) if p.get("effective_to") else None,
            source_url=None,
            conditions=p.get("conditions", {}),
            demo=True,
        )
        for p in raw
    )


def apply_policies(
    offer: Offer,
    policies: list[FeePolicy],
    pincode: str,
    today: date | None = None,
) -> Offer:
    """Return the offer with UNKNOWN charges estimated from applicable policies."""
    if not policies or offer.item_price is None:
        return offer
    today = today or date.today()
    verified = sum(
        (c.amount for c in offer.coupons if c.eligibility is CouponEligibility.VERIFIED),
        Decimal(0),
    )
    order_value = max(Decimal(0), offer.item_price - verified)

    updates: dict[str, Charge] = {}
    for fee_type, charge_key in CHARGE_FOR_FEE.items():
        current: Charge = getattr(offer, charge_key)
        if current.status is not ChargeStatus.UNKNOWN or charge_key in updates:
            continue
        candidates = [
            (p, amount)
            for p in policies
            if p.fee_type is fee_type and p.in_effect(today) and not p.problems()
            for amount in [p.amount_for(order_value, pincode)]
            if amount is not None
        ]
        if not candidates:
            continue
        if len({a for _, a in candidates}) > 1:
            log.info("fee_policies_conflict", charge=charge_key)
            continue  # disagreeing policies: leave it unknown
        policy, amount = candidates[0]
        updates[charge_key] = Charge.estimated(amount, policy.describe(amount))
    return offer.model_copy(update=updates) if updates else offer
