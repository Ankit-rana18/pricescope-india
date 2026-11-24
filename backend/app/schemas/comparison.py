"""API view of a comparison. Built identically from live state or from storage."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    Availability,
    ChargeStatus,
    ComparisonStatus,
    DataMode,
    LocationVerification,
    MarketplaceCode,
    MatchClass,
)

ResultState = Literal["PENDING", "OK", "NOT_FOUND", "FAILED", "UNSUPPORTED", "NOT_CONFIGURED"]


class NormalizedView(BaseModel):
    size: str | None = None
    pack_count: int = 1
    total: str | None = None
    colour: str | None = None
    storage_gb: int | None = None
    ram_gb: int | None = None
    variant_key: str
    warnings: list[str] = []


class ListingView(BaseModel):
    marketplace: MarketplaceCode
    marketplace_name: str
    external_id: str
    title: str
    brand: str | None = None
    model: str | None = None
    gtin: str | None = None
    url: str | None = Field(None, description="Real product page; always null for demo data.")
    image_url: str | None = None
    normalized: NormalizedView


class ChargeView(BaseModel):
    status: ChargeStatus
    amount: Decimal | None = None
    note: str | None = None


class CouponView(BaseModel):
    description: str
    amount: Decimal
    eligibility: Literal["VERIFIED", "UNVERIFIED"]


class PriceView(BaseModel):
    item_price: Decimal | None
    mrp: Decimal | None
    verified_discount: Decimal
    delivery_fee: ChargeView
    handling_fee: ChargeView
    platform_fee: ChargeView
    other_fees: ChargeView
    coupons: list[CouponView] = []
    final_price: Decimal | None = Field(
        description="Total if complete; otherwise the known subtotal (unknown fees excluded)."
    )
    final_price_complete: bool
    final_price_estimated: bool = Field(
        False, description="Includes a fee estimated from a published policy, not confirmed."
    )
    assumptions: list[str] = []


class CardOfferView(BaseModel):
    bank: str
    card_type: str
    card_network: str | None = None
    kind: Literal["PERCENT", "FLAT"]
    value: Decimal
    max_discount: Decimal | None = None
    min_order_value: Decimal | None = None
    emi_only: bool = False
    terms: str | None = None
    discount: Decimal | None = Field(
        description="Saving at this order value; null if not applicable."
    )
    note: str


class CandidateView(BaseModel):
    external_id: str
    title: str
    match_class: MatchClass
    match_reasons: list[str]
    final_price: Decimal | None = None
    final_price_complete: bool = False


class ResultView(BaseModel):
    marketplace: MarketplaceCode
    marketplace_name: str
    status: ResultState
    status_reason: str | None = None
    listing: ListingView | None = None
    match_class: MatchClass | None = None
    match_score: Decimal | None = None
    match_reasons: list[str] = []
    price: PriceView | None = None
    card_offers: list[CardOfferView] = []
    best_card: CardOfferView | None = None
    price_after_best_card: Decimal | None = None
    availability: Availability = Availability.UNKNOWN
    location_verification: LocationVerification | None = None
    eta_text: str | None = None
    other_candidates: list[CandidateView] = []
    is_source: bool = False
    ranked: bool = False
    rank: int | None = None
    delivery_verified: bool = False
    price_verified: bool = Field(
        False, description="Complete final price with every fee reported by the marketplace."
    )
    is_cheapest: bool = False
    not_ranked_because: list[str] = []
    attempts: int | None = None
    latency_ms: int | None = None
    checked_at: datetime | None = None


class CheapestView(BaseModel):
    marketplace: MarketplaceCode
    marketplace_name: str
    final_price: Decimal
    caveats: list[str] = []


class BestCardView(BaseModel):
    marketplace: MarketplaceCode
    marketplace_name: str
    price_after_card: Decimal
    final_price: Decimal
    discount: Decimal
    card: str
    delivery_verified: bool
    price_verified: bool = True


class SummaryView(BaseModel):
    cheapest: CheapestView | None = Field(
        None, description="Cheapest exact, in-stock, fully priced result with delivery verified."
    )
    cheaper_unverified: CheapestView | None = Field(
        None,
        description="A cheaper exact match whose delivery to the PIN code can't be verified.",
    )
    source_final_price: Decimal | None = None
    savings_vs_source: Decimal | None = None
    best_with_card: BestCardView | None = None
    exact_matches: int = 0
    probable_matches: int = 0
    marketplaces_checked: int = 0
    marketplaces_failed: int = 0


class LocationView(BaseModel):
    postal_region: str
    directory_status: Literal["VERIFIED", "NOT_FOUND", "UNAVAILABLE"]
    district: str | None = None
    state: str | None = None
    division: str | None = None
    circle: str | None = None


class ComparisonView(BaseModel):
    id: str
    status: ComparisonStatus
    data_mode: DataMode
    pincode: str
    location: LocationView | None = None
    source_url: str
    created_at: datetime
    completed_at: datetime | None = None
    source: ListingView
    results: list[ResultView]
    summary: SummaryView
    reused: bool = False
    storage_note: str | None = None


class ComparisonRequest(BaseModel):
    url: str = Field(max_length=4096, examples=["https://www.amazon.in/dp/DEMO000003"])
    pincode: str = Field(max_length=16, examples=["560001"])


class MarketplaceStatusView(BaseModel):
    marketplace: MarketplaceCode
    marketplace_name: str
    state: Literal["LIVE", "DEGRADED", "NOT_CONFIGURED", "UNSUPPORTED", "DEMO"]
    data_source: DataMode | None
    reason: str
    capabilities: dict[str, bool | str]


class MarketplacesView(BaseModel):
    data_mode: DataMode
    marketplaces: list[MarketplaceStatusView]


class DemoProductView(BaseModel):
    key: str
    title: str
    marketplace: MarketplaceCode
    url: str
