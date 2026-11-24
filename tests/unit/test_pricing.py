"""Final price formula and card offers."""

from decimal import Decimal

from pricescope_integrations.models import (
    CardOffer,
    CardType,
    Charge,
    Coupon,
    CouponEligibility,
    DataSource,
    DiscountKind,
    Offer,
)

from app.services.pricing import card_offer_value, evaluate_card_offers, price_offer

D = Decimal


def offer(**kw: object) -> Offer:
    base: dict[str, object] = {
        "item_price": D("100"),
        "delivery_fee": Charge.known(20),
        "handling_fee": Charge.known(5),
        "platform_fee": Charge.not_applicable(),
        "other_fees": Charge.not_applicable(),
        "data_source": DataSource.DEMO,
    }
    base.update(kw)
    return Offer(**base)  # type: ignore[arg-type]


def test_formula_adds_known_mandatory_charges() -> None:
    b = price_offer(offer())
    assert b.final_price == D("125.00")
    assert b.final_price_complete is True


def test_unknown_fee_is_not_zero_and_marks_incomplete() -> None:
    b = price_offer(offer(delivery_fee=Charge.unknown("Depends on cart value")))
    assert b.final_price == D("105.00")  # known subtotal only
    assert b.final_price_complete is False
    assert any("Delivery fee unknown (Depends on cart value)" in a for a in b.assumptions)


def test_only_verified_coupons_are_subtracted() -> None:
    b = price_offer(
        offer(
            coupons=(
                Coupon(
                    description="BANK10", amount=D("10"), eligibility=CouponEligibility.VERIFIED
                ),
                Coupon(description="FIRST50", amount=D("50")),
            )
        )
    )
    assert b.verified_discount == D("10.00")
    assert b.final_price == D("115.00")
    assert any("Not applied: FIRST50" in a for a in b.assumptions)


def test_missing_item_price_gives_no_final_price() -> None:
    b = price_offer(offer(item_price=None))
    assert b.final_price is None
    assert b.final_price_complete is False


def test_charge_model_refuses_unknown_with_amount_and_known_without() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Charge(status="UNKNOWN", amount=D("0"))
    with pytest.raises(ValidationError):
        Charge(status="KNOWN")


# ------------------------------------------------------------------ card offers


def card(**kw: object) -> CardOffer:
    base: dict[str, object] = {
        "bank": "Demo Bank A",
        "kind": DiscountKind.PERCENT,
        "value": D("10"),
    }
    base.update(kw)
    return CardOffer(**base)  # type: ignore[arg-type]


def test_percent_offer_is_capped() -> None:
    v = card_offer_value(card(max_discount=D("1500")), D("20000"))
    assert v.discount == D("1500")


def test_percent_offer_below_cap_keeps_paise() -> None:
    v = card_offer_value(card(max_discount=D("1500")), D("14999"))
    assert v.discount == D("1499.90")


def test_minimum_order_value_respected() -> None:
    v = card_offer_value(
        card(kind=DiscountKind.FLAT, value=D("750"), min_order_value=D("12000")), D("11999")
    )
    assert v.discount is None
    assert "at least ₹12,000" in v.note


def test_flat_offer_never_exceeds_order_value() -> None:
    v = card_offer_value(card(kind=DiscountKind.FLAT, value=D("500")), D("300"))
    assert v.discount == D("300")


def test_best_offer_prefers_regular_over_bigger_emi_only() -> None:
    offers = (
        card(bank="Demo Bank B", kind=DiscountKind.FLAT, value=D("2000"), emi_only=True),
        card(bank="Demo Bank A", max_discount=D("1500")),
        card(bank="Demo Bank C", kind=DiscountKind.FLAT, value=D("750"), card_type=CardType.DEBIT),
    )
    ordered, best = evaluate_card_offers(offers, D("14999"))
    assert best is not None and best.offer.bank == "Demo Bank A"
    assert [v.offer.bank for v in ordered] == ["Demo Bank A", "Demo Bank C", "Demo Bank B"]


def test_emi_only_is_best_when_nothing_else_applies() -> None:
    offers = (card(kind=DiscountKind.FLAT, value=D("2000"), emi_only=True),)
    _, best = evaluate_card_offers(offers, D("15000"))
    assert best is not None and best.offer.emi_only
    assert "on EMI only" in best.note


def test_card_offers_never_change_final_price() -> None:
    b = price_offer(offer(card_offers=(card(max_discount=D("5")),)))
    assert b.final_price == D("125.00")
    assert b.best_card is not None and b.best_card.discount == D("5.00")
    assert b.price_after_best_card == D("120.00")
    assert any("depend on your card" in a for a in b.assumptions)


def test_no_price_after_card_when_final_price_incomplete() -> None:
    b = price_offer(offer(delivery_fee=Charge.unknown(), card_offers=(card(),)))
    assert b.best_card is not None
    assert b.price_after_best_card is None
