"""Centralised price normalisation.

    final = item price
            - verified eligible discounts
            + delivery + handling + platform + other mandatory charges

* An UNKNOWN charge is never treated as zero: the result is marked incomplete and the
  known subtotal is shown as "₹X + unknown fees".
* Coupons are subtracted only when their eligibility is VERIFIED; others are listed.
* Card / bank offers depend on the shopper's card, so they are NEVER part of the final
  price. They are evaluated separately: the best applicable offer and the price after it.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pricescope_integrations.models import (
    CardOffer,
    Charge,
    ChargeStatus,
    CouponEligibility,
    DiscountKind,
    Offer,
)

PAISE = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def inr(value: Decimal) -> str:
    return f"₹{money(value):,.2f}".replace(".00", "")


@dataclass(frozen=True)
class CardOfferValue:
    offer: CardOffer
    discount: Decimal | None  # None = not applicable at this order value
    note: str


@dataclass(frozen=True)
class PriceBreakdown:
    item_price: Decimal | None
    mrp: Decimal | None
    verified_discount: Decimal
    charges: dict[str, Charge]
    final_price: Decimal | None  # complete total, or the known subtotal if incomplete
    final_price_complete: bool
    assumptions: tuple[str, ...]
    card_offers: tuple[CardOfferValue, ...]  # best first
    best_card: CardOfferValue | None

    @property
    def price_after_best_card(self) -> Decimal | None:
        if not self.final_price_complete or self.final_price is None or not self.best_card:
            return None
        assert self.best_card.discount is not None
        return money(max(Decimal(0), self.final_price - self.best_card.discount))


CHARGE_LABELS = {
    "delivery_fee": "Delivery fee",
    "handling_fee": "Handling fee",
    "platform_fee": "Platform fee",
    "other_fees": "Other charges",
}


def card_offer_value(offer: CardOffer, order_value: Decimal) -> CardOfferValue:
    if offer.min_order_value is not None and order_value < offer.min_order_value:
        return CardOfferValue(
            offer, None, f"Needs an order of at least {inr(offer.min_order_value)}"
        )
    if offer.kind is DiscountKind.PERCENT:
        discount = money(order_value * offer.value / 100)
        if offer.max_discount is not None:
            discount = min(discount, offer.max_discount)
    else:
        discount = min(offer.value, order_value)
    parts = [f"{offer.bank} {offer.card_type.value.lower()} card"]
    if offer.card_network:
        parts.append(f"({offer.card_network})")
    if offer.emi_only:
        parts.append("on EMI only")
    return CardOfferValue(offer, money(discount), " ".join(parts))


def evaluate_card_offers(
    offers: tuple[CardOffer, ...], order_value: Decimal
) -> tuple[tuple[CardOfferValue, ...], CardOfferValue | None]:
    values = [card_offer_value(o, order_value) for o in offers]
    applicable = [v for v in values if v.discount is not None and v.discount > 0]
    # Regular offers before EMI-only ones (EMI brings its own costs and conditions), then
    # highest saving first. An EMI-only offer is "best" only when nothing else applies.
    applicable.sort(key=lambda v: (v.offer.emi_only, -(v.discount or 0)))
    rest = [v for v in values if v not in applicable]
    return tuple(applicable + rest), (applicable[0] if applicable else None)


def price_offer(offer: Offer, *, location_note: str | None = None) -> PriceBreakdown:
    charges = {
        "delivery_fee": offer.delivery_fee,
        "handling_fee": offer.handling_fee,
        "platform_fee": offer.platform_fee,
        "other_fees": offer.other_fees,
    }
    assumptions: list[str] = []
    verified = money(
        sum(
            (c.amount for c in offer.coupons if c.eligibility is CouponEligibility.VERIFIED),
            Decimal(0),
        )
    )
    for c in offer.coupons:
        if c.eligibility is CouponEligibility.VERIFIED:
            assumptions.append(
                f"Includes verified discount: {c.description} (\u2212{inr(c.amount)})"
            )
        else:
            assumptions.append(
                f"Not applied: {c.description} (\u2212{inr(c.amount)}); eligibility not verified"
            )

    if offer.item_price is None:
        return PriceBreakdown(
            item_price=None,
            mrp=offer.mrp,
            verified_discount=verified,
            charges=charges,
            final_price=None,
            final_price_complete=False,
            assumptions=("Item price not available", *assumptions),
            card_offers=(),
            best_card=None,
        )

    order_value = max(Decimal(0), offer.item_price - verified)
    total = order_value
    complete = True
    for key, charge in charges.items():
        if charge.status is ChargeStatus.KNOWN:
            assert charge.amount is not None
            total += charge.amount
        elif charge.status is ChargeStatus.UNKNOWN:
            complete = False
            note = f" ({charge.note})" if charge.note else ""
            assumptions.append(f"{CHARGE_LABELS[key]} unknown{note}: not included")
    if location_note:
        assumptions.append(location_note)

    card_values, best = evaluate_card_offers(offer.card_offers, order_value)
    if offer.card_offers:
        assumptions.append("Card offers depend on your card and are not included in the price")

    return PriceBreakdown(
        item_price=money(offer.item_price),
        mrp=money(offer.mrp) if offer.mrp is not None else None,
        verified_discount=verified,
        charges=charges,
        final_price=money(total),
        final_price_complete=complete,
        assumptions=tuple(assumptions),
        card_offers=card_values,
        best_card=best,
    )
