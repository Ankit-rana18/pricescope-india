"""Published fee policies: when they apply, how they're labelled, and what they never do."""

from datetime import date
from decimal import Decimal

import pytest
from pricescope_integrations.models import (
    Charge,
    ChargeStatus,
    Coupon,
    CouponEligibility,
    DataSource,
    Offer,
)

from app.models.enums import FeeType, MarketplaceCode
from app.services.fee_policies import FeePolicy, StaticFeePolicies, apply_policies, demo_policies
from app.services.pricing import price_offer

D = Decimal
TODAY = date(2026, 11, 24)
FK = MarketplaceCode.FLIPKART


def policy(**kw: object) -> FeePolicy:
    base: dict[str, object] = {
        "marketplace": FK,
        "fee_type": FeeType.DELIVERY,
        "amount": D("40"),
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
        "source_url": "https://www.example.com/shipping-policy",
        "conditions": {"below_order_value": "500"},
    }
    base.update(kw)
    return FeePolicy(**base)  # type: ignore[arg-type]


def offer(price: str = "300", **kw: object) -> Offer:
    base: dict[str, object] = {
        "item_price": D(price),
        "delivery_fee": Charge.unknown(),
        "handling_fee": Charge.not_applicable(),
        "platform_fee": Charge.known(3),
        "other_fees": Charge.not_applicable(),
        "data_source": DataSource.LIVE,
    }
    base.update(kw)
    return Offer(**base)  # type: ignore[arg-type]


def test_fills_unknown_fee_as_estimated_with_source() -> None:
    out = apply_policies(offer(), [policy()], "560001", TODAY)
    assert out.delivery_fee.status is ChargeStatus.ESTIMATED
    assert out.delivery_fee.amount == D("40")
    assert "per published policy" in (out.delivery_fee.note or "")
    assert "not confirmed for your cart" in (out.delivery_fee.note or "")


def test_threshold_makes_fee_zero_above_it() -> None:
    out = apply_policies(offer("600"), [policy()], "560001", TODAY)
    assert (out.delivery_fee.status, out.delivery_fee.amount) == (ChargeStatus.ESTIMATED, D("0"))


def test_threshold_uses_order_value_after_verified_coupons() -> None:
    coupons = (Coupon(description="X", amount=D("150"), eligibility=CouponEligibility.VERIFIED),)
    out = apply_policies(offer("600", coupons=coupons), [policy()], "560001", TODAY)
    assert out.delivery_fee.amount == D("40")  # 600 - 150 = 450 < 500


def test_never_overrides_a_reported_fee() -> None:
    out = apply_policies(offer(delivery_fee=Charge.known(0)), [policy()], "560001", TODAY)
    assert out.delivery_fee.status is ChargeStatus.KNOWN


@pytest.mark.parametrize(
    "p",
    [
        policy(effective_from=date(2027, 1, 1)),  # not yet in effect
        policy(effective_to=date(2026, 6, 30)),  # expired
        policy(conditions={"members_only": True}),  # unknown condition: never guessed
        policy(source_url="http://insecure.example"),  # live policy needs https source
        policy(source_url=None),
        policy(conditions={"pincode_prefixes": ["110"]}),  # other region
    ],
)
def test_policies_that_must_not_apply(p: FeePolicy) -> None:
    out = apply_policies(offer(), [p], "560001", TODAY)
    assert out.delivery_fee.status is ChargeStatus.UNKNOWN


def test_conflicting_policies_leave_fee_unknown() -> None:
    out = apply_policies(offer(), [policy(), policy(amount=D("60"))], "560001", TODAY)
    assert out.delivery_fee.status is ChargeStatus.UNKNOWN


def test_agreeing_policies_apply() -> None:
    out = apply_policies(
        offer(), [policy(), policy(source_url="https://www.example.com/faq")], "560001", TODAY
    )
    assert out.delivery_fee.amount == D("40")


def test_estimated_price_is_complete_but_flagged() -> None:
    b = price_offer(apply_policies(offer(), [policy()], "560001", TODAY))
    assert b.final_price == D("343.00")
    assert b.final_price_complete is True
    assert b.final_price_estimated is True
    assert any("Estimated delivery ₹40" in a for a in b.assumptions)


def test_estimated_charge_must_name_its_source() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Charge(status=ChargeStatus.ESTIMATED, amount=D("40"))


def test_demo_policies_are_labelled_fictional() -> None:
    source = demo_policies(
        [
            {
                "marketplace": "FLIPKART",
                "fee_type": "DELIVERY",
                "amount": "40",
                "effective_from": "2026-01-01",
                "conditions": {"below_order_value": "500"},
            }
        ]
    )
    out = apply_policies(offer(), source.for_marketplace(FK), "560001", TODAY)
    assert "demo published policy (fictional)" in (out.delivery_fee.note or "")


def test_static_source_filters_by_marketplace() -> None:
    src = StaticFeePolicies([policy(), policy(marketplace=MarketplaceCode.ZEPTO)])
    assert len(src.for_marketplace(FK)) == 1
