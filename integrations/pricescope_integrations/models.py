"""Data exchanged with marketplace adapters.

Everything is JSON-serialisable (Decimal amounts travel as strings), so results can cross
a Celery boundary unchanged. Unknown values are explicit: a fee is ``UNKNOWN`` with no
amount, never 0; a location check that cannot be done is ``UNVERIFIABLE``, never "yes".
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Marketplace(StrEnum):
    AMAZON_IN = "AMAZON_IN"
    FLIPKART = "FLIPKART"
    BLINKIT = "BLINKIT"
    ZEPTO = "ZEPTO"
    BIGBASKET = "BIGBASKET"


class DataSource(StrEnum):
    LIVE = "LIVE"
    DEMO = "DEMO"


class AdapterState(StrEnum):
    LIVE = "LIVE"  # real credentials AND a verified live call
    DEGRADED = "DEGRADED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    UNSUPPORTED = "UNSUPPORTED"
    DEMO = "DEMO"


class LocationCapability(StrEnum):
    NONE = "NONE"
    PINCODE = "PINCODE"
    PRECISE_LOCATION = "PRECISE_LOCATION"
    STORE = "STORE"


class ChargeStatus(StrEnum):
    KNOWN = "KNOWN"  # reported by the marketplace for this offer
    ESTIMATED = "ESTIMATED"  # from a published fee policy; not confirmed for this cart
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CouponEligibility(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class Availability(StrEnum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"


class LocationVerification(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIABLE = "UNVERIFIABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NEEDS_PRECISE_LOCATION = "NEEDS_PRECISE_LOCATION"


class FetchStatus(StrEnum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Capabilities(_Model):
    search_by_gtin: bool = False
    search_by_text: bool = False
    location: LocationCapability = LocationCapability.NONE
    fees: bool = False
    coupons: bool = False


class AdapterStatus(_Model):
    marketplace: Marketplace
    state: AdapterState
    data_source: DataSource | None
    reason: str
    capabilities: Capabilities = Capabilities()


class Listing(_Model):
    marketplace: Marketplace
    external_id: str
    title: str
    # None for demo listings: they have no real page, so no link is shown.
    url: str | None = None
    image_url: str | None = None
    brand: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    gtin: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    data_source: DataSource


class ProductQuery(_Model):
    title: str
    brand: str | None = None
    model: str | None = None
    gtin: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Charge(_Model):
    status: ChargeStatus = ChargeStatus.UNKNOWN
    amount: Decimal | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status in (ChargeStatus.KNOWN, ChargeStatus.ESTIMATED):
            if self.amount is None or self.amount < 0:
                raise ValueError(f"a {self.status} charge needs a non-negative amount")
            if self.status is ChargeStatus.ESTIMATED and not self.note:
                raise ValueError("an ESTIMATED charge must say where the estimate comes from")
        elif self.amount is not None:
            raise ValueError(f"a {self.status} charge must not carry an amount")
        return self

    @classmethod
    def known(cls, amount: Decimal | int | str, note: str | None = None) -> "Charge":
        return cls(status=ChargeStatus.KNOWN, amount=Decimal(str(amount)), note=note)

    @classmethod
    def estimated(cls, amount: Decimal | int | str, note: str) -> "Charge":
        return cls(status=ChargeStatus.ESTIMATED, amount=Decimal(str(amount)), note=note)

    @classmethod
    def unknown(cls, note: str | None = None) -> "Charge":
        return cls(status=ChargeStatus.UNKNOWN, note=note)

    @classmethod
    def not_applicable(cls, note: str | None = None) -> "Charge":
        return cls(status=ChargeStatus.NOT_APPLICABLE, note=note)


class Coupon(_Model):
    description: str
    amount: Decimal = Field(gt=0)
    eligibility: CouponEligibility = CouponEligibility.UNVERIFIED


class CardType(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    ANY = "ANY"


class DiscountKind(StrEnum):
    PERCENT = "PERCENT"
    FLAT = "FLAT"


class CardOffer(_Model):
    """A bank / card offer as published by the marketplace for this listing.

    Whether it applies depends on the shopper's card, so it is never treated as a
    verified discount. ``max_discount`` and ``min_order_value`` are applied when computing
    the discount; ``emi_only`` offers need an EMI purchase.
    """

    bank: str
    card_type: CardType = CardType.CREDIT
    card_network: str | None = None  # e.g. "Visa", "RuPay"; None = any network
    kind: DiscountKind
    value: Decimal = Field(gt=0)  # percent (e.g. 10) or flat rupees
    max_discount: Decimal | None = Field(default=None, gt=0)
    min_order_value: Decimal | None = Field(default=None, ge=0)
    emi_only: bool = False
    terms: str | None = None


class LocationResult(_Model):
    verification: LocationVerification
    serviceable: bool | None = None  # None = not determined; never assumed
    eta_text: str | None = None


class Offer(_Model):
    item_price: Decimal | None = None
    mrp: Decimal | None = None
    delivery_fee: Charge = Charge()
    handling_fee: Charge = Charge()
    platform_fee: Charge = Charge()
    other_fees: Charge = Charge()
    coupons: tuple[Coupon, ...] = ()
    card_offers: tuple[CardOffer, ...] = ()
    availability: Availability = Availability.UNKNOWN
    location: LocationResult = LocationResult(verification=LocationVerification.UNVERIFIABLE)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data_source: DataSource


class CandidateOffer(_Model):
    listing: Listing
    offer: Offer | None = None
    offer_error: str | None = None


class FetchResult(_Model):
    marketplace: Marketplace
    status: FetchStatus
    candidates: tuple[CandidateOffer, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    data_source: DataSource | None = None
