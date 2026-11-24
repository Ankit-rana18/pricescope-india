"""Turn adapter results into scored, priced, ranked views (pure functions, no I/O)."""

from datetime import UTC, datetime
from decimal import Decimal

from pricescope_integrations.models import (
    CandidateOffer,
    FetchResult,
    FetchStatus,
    Listing,
    LocationVerification,
)

from app.models.enums import Availability, MarketplaceCode, MatchClass
from app.models.enums import LocationVerification as LocationState
from app.schemas.comparison import (
    BestCardView,
    CandidateView,
    CardOfferView,
    ChargeView,
    CheapestView,
    CouponView,
    ListingView,
    NormalizedView,
    PriceView,
    ResultView,
    SummaryView,
)
from app.services.matching import MatchDecision, classify
from app.services.normalization import normalize_attributes
from app.services.pricing import CardOfferValue, PriceBreakdown, money, price_offer
from app.services.url_parser import NAMES

MATCH_ORDER = {
    MatchClass.EXACT: 0,
    MatchClass.PROBABLE: 1,
    MatchClass.UNVERIFIED: 2,
    MatchClass.MISMATCH: 3,
}

LOCATION_NOTES = {
    LocationVerification.UNVERIFIABLE: "Delivery to your PIN code can't be verified here",
    LocationVerification.NEEDS_PRECISE_LOCATION: (
        "Needs a precise delivery address; a PIN code alone isn't enough to check"
    ),
    LocationVerification.UNAVAILABLE: "Not deliverable to your PIN code",
}


def name_of(code: MarketplaceCode | str) -> str:
    return NAMES[MarketplaceCode(code)]


def listing_view(listing: Listing) -> ListingView:
    n = normalize_attributes(listing.title, listing.attributes)
    return ListingView(
        marketplace=MarketplaceCode(listing.marketplace.value),
        marketplace_name=name_of(listing.marketplace.value),
        external_id=listing.external_id,
        title=listing.title,
        brand=listing.brand,
        model=listing.model,
        gtin=listing.gtin,
        url=listing.url,
        image_url=listing.image_url,
        normalized=NormalizedView(
            size=str(n.per_unit) if n.per_unit else None,
            pack_count=n.pack_count,
            total=str(n.total) if n.total else None,
            colour=n.colour,
            storage_gb=n.storage_gb,
            ram_gb=n.ram_gb,
            variant_key=n.variant_key(),
            warnings=list(n.warnings),
        ),
    )


def card_view(v: CardOfferValue) -> CardOfferView:
    o = v.offer
    return CardOfferView(
        bank=o.bank,
        card_type=o.card_type.value,
        card_network=o.card_network,
        kind=o.kind.value,
        value=o.value,
        max_discount=o.max_discount,
        min_order_value=o.min_order_value,
        emi_only=o.emi_only,
        terms=o.terms,
        discount=v.discount,
        note=v.note,
    )


def price_view(b: PriceBreakdown, coupons: list[CouponView]) -> PriceView:
    def cv(key: str) -> ChargeView:
        c = b.charges[key]
        amount = money(c.amount) if c.amount is not None else None
        return ChargeView(status=c.status.value, amount=amount, note=c.note)

    return PriceView(
        item_price=b.item_price,
        mrp=b.mrp,
        verified_discount=b.verified_discount,
        delivery_fee=cv("delivery_fee"),
        handling_fee=cv("handling_fee"),
        platform_fee=cv("platform_fee"),
        other_fees=cv("other_fees"),
        coupons=coupons,
        final_price=b.final_price,
        final_price_complete=b.final_price_complete,
        assumptions=list(b.assumptions),
    )


def _scored(source: Listing, cand: CandidateOffer) -> tuple[MatchDecision, PriceBreakdown | None]:
    decision = classify(source, cand.listing)
    if cand.offer is None:
        return decision, None
    note = LOCATION_NOTES.get(cand.offer.location.verification)
    return decision, price_offer(cand.offer, location_note=note)


def evaluate(source: Listing, fetch: FetchResult) -> ResultView:
    code = MarketplaceCode(fetch.marketplace.value)
    base = ResultView(
        marketplace=code,
        marketplace_name=name_of(code),
        status=fetch.status.value,
        status_reason=fetch.error_message,
        attempts=fetch.attempts,
        latency_ms=fetch.latency_ms,
        checked_at=datetime.now(UTC),
    )
    if fetch.status is not FetchStatus.OK or not fetch.candidates:
        if fetch.status is FetchStatus.FAILED and not fetch.error_message:
            base.status_reason = fetch.error_code
        return base

    scored = [(c, *_scored(source, c)) for c in fetch.candidates]

    def key(
        item: tuple[CandidateOffer, MatchDecision, PriceBreakdown | None],
    ) -> tuple[int, int, Decimal]:
        _, decision, b = item
        has_price = 0 if (b and b.final_price_complete) else 1
        price = b.final_price if (b and b.final_price is not None) else Decimal("9e15")
        return MATCH_ORDER[decision.match_class], has_price, price

    scored.sort(key=key)
    primary, decision, breakdown = scored[0]
    offer = primary.offer

    base.listing = listing_view(primary.listing)
    base.match_class = decision.match_class
    base.match_score = decision.score
    base.match_reasons = list(decision.reasons)
    base.is_source = decision.reasons == ("the product you pasted",)
    if offer is not None and breakdown is not None:
        coupons = [
            CouponView(description=c.description, amount=c.amount, eligibility=c.eligibility.value)
            for c in offer.coupons
        ]
        base.price = price_view(breakdown, coupons)
        base.card_offers = [card_view(v) for v in breakdown.card_offers]
        base.best_card = card_view(breakdown.best_card) if breakdown.best_card else None
        base.price_after_best_card = breakdown.price_after_best_card
        base.availability = Availability(offer.availability.value)
        base.location_verification = LocationState(offer.location.verification.value)
        base.eta_text = offer.location.eta_text
        base.checked_at = offer.checked_at
    elif primary.offer_error:
        base.status_reason = f"Price check failed ({primary.offer_error})"

    base.other_candidates = [
        CandidateView(
            external_id=c.listing.external_id,
            title=c.listing.title,
            match_class=d.match_class,
            match_reasons=list(d.reasons),
            final_price=b.final_price if b else None,
            final_price_complete=bool(b and b.final_price_complete),
        )
        for c, d, b in scored[1:]
    ]
    return base


def _ranking_blockers(r: ResultView) -> list[str]:
    reasons = []
    if r.status != "OK" or r.listing is None:
        return {
            "FAILED": ["check failed"],
            "NOT_FOUND": ["not sold here"],
            "PENDING": ["still checking"],
            "UNSUPPORTED": ["no data access"],
            "NOT_CONFIGURED": ["integration not configured"],
        }.get(r.status, ["no listing found"])
    if r.match_class is not MatchClass.EXACT:
        reasons.append(f"match is {r.match_class.value.lower() if r.match_class else 'unknown'}")
    if r.price is None or r.price.final_price is None:
        reasons.append("no price")
    elif not r.price.final_price_complete:
        reasons.append("some fees are unknown")
    if r.availability is not Availability.IN_STOCK:
        reasons.append(
            "out of stock" if r.availability is Availability.OUT_OF_STOCK else "stock unknown"
        )
    if r.location_verification == "UNAVAILABLE":
        reasons.append("not deliverable to your PIN code")
    return reasons


def rank_and_summarize(results: list[ResultView]) -> tuple[list[ResultView], SummaryView]:
    """Rank exact, in-stock, fully priced results by final price.

    Results whose delivery to the PIN is verified come first; those that can't be verified
    (but aren't known to be undeliverable) follow, flagged. Everything else is listed after,
    with the reasons it wasn't ranked.
    """
    for r in results:
        r.not_ranked_because = _ranking_blockers(r)
        r.ranked = not r.not_ranked_because
        r.delivery_verified = r.location_verification == "VERIFIED"
        r.rank = None
        r.is_cheapest = False

    ranked = sorted(
        (r for r in results if r.ranked),
        key=lambda r: (0 if r.delivery_verified else 1, r.price.final_price),  # type: ignore[union-attr]
    )
    for i, r in enumerate(ranked, start=1):
        r.rank = i
    rest = sorted(
        (r for r in results if not r.ranked),
        key=lambda r: (
            MATCH_ORDER.get(r.match_class, 9) if r.match_class else 9,
            {"OK": 0, "NOT_FOUND": 1, "PENDING": 2, "FAILED": 3}.get(r.status, 4),
            r.marketplace_name,
        ),
    )

    summary = SummaryView(
        exact_matches=sum(1 for r in results if r.match_class is MatchClass.EXACT),
        probable_matches=sum(
            1
            for r in results
            for m in [r.match_class, *[c.match_class for c in r.other_candidates]]
            if m is MatchClass.PROBABLE
        ),
        marketplaces_checked=sum(1 for r in results if r.status in ("OK", "NOT_FOUND")),
        marketplaces_failed=sum(1 for r in results if r.status == "FAILED"),
    )
    verified = [r for r in ranked if r.delivery_verified]
    if verified:
        best = verified[0]
        best.is_cheapest = True
        assert best.price and best.price.final_price is not None
        summary.cheapest = CheapestView(
            marketplace=best.marketplace,
            marketplace_name=best.marketplace_name,
            final_price=best.price.final_price,
        )
    unverified = [r for r in ranked if not r.delivery_verified]
    if unverified:
        u = unverified[0]
        assert u.price and u.price.final_price is not None
        if summary.cheapest is None or u.price.final_price < summary.cheapest.final_price:
            summary.cheaper_unverified = CheapestView(
                marketplace=u.marketplace,
                marketplace_name=u.marketplace_name,
                final_price=u.price.final_price,
            )
    source = next((r for r in results if r.is_source), None)
    if source and source.price and source.price.final_price_complete:
        summary.source_final_price = source.price.final_price
        if summary.cheapest and source.price.final_price is not None:
            summary.savings_vs_source = max(
                Decimal(0), source.price.final_price - summary.cheapest.final_price
            )

    with_card = [r for r in ranked if r.price_after_best_card is not None and r.best_card]
    if with_card:
        b = min(with_card, key=lambda r: r.price_after_best_card)  # type: ignore[arg-type,return-value]
        assert b.best_card and b.price and b.price.final_price is not None
        assert b.price_after_best_card is not None and b.best_card.discount is not None
        summary.best_with_card = BestCardView(
            marketplace=b.marketplace,
            marketplace_name=b.marketplace_name,
            price_after_card=b.price_after_best_card,
            final_price=b.price.final_price,
            discount=b.best_card.discount,
            card=b.best_card.note,
            delivery_verified=b.delivery_verified,
        )
    return ranked + rest, summary
