"""Deterministic product matching (Phase 4 rules; Phase 5 adds fuzzy titles + LLM review).

Order of rules:
1. Same marketplace + same listing ID            -> EXACT
2. Hard vetoes (brand, model, net quantity, pack count, colour, storage, RAM differ
   when both sides state them)                    -> MISMATCH, even if barcodes agree
3. Barcodes (GTIN/EAN/UPC) both present: equal -> EXACT (PROBABLE if either side's
   attributes are ambiguous); different         -> MISMATCH
4. Brand + model both equal, size equal          -> EXACT
5. Brand + size/pack/variant equal, no barcode   -> PROBABLE (never ranked by default)
6. Anything else                                 -> UNVERIFIED
"""

from dataclasses import dataclass
from decimal import Decimal

from pricescope_integrations.models import Listing

from app.models.enums import MatchClass
from app.services.normalization import NormalizedAttributes, normalize_attributes, normalize_brand

SCORES = {
    MatchClass.EXACT: Decimal("1.000"),
    MatchClass.PROBABLE: Decimal("0.800"),
    MatchClass.UNVERIFIED: Decimal("0.400"),
    MatchClass.MISMATCH: Decimal("0.000"),
}


@dataclass(frozen=True)
class MatchDecision:
    match_class: MatchClass
    reasons: tuple[str, ...]

    @property
    def score(self) -> Decimal:
        return SCORES[self.match_class]


def _norm(listing: Listing) -> NormalizedAttributes:
    return normalize_attributes(listing.title, listing.attributes)


def _model(listing: Listing) -> str | None:
    return listing.model.strip().casefold() if listing.model else None


def _gtin(listing: Listing) -> str | None:
    """Digits only, zero-padded to GTIN-14 so EAN-13 and UPC-A forms compare equal."""
    if not listing.gtin:
        return None
    digits = "".join(c for c in listing.gtin if c.isdigit())
    return digits.zfill(14) if 8 <= len(digits) <= 14 else None


def _vetoes(
    a: Listing, b: Listing, na: NormalizedAttributes, nb: NormalizedAttributes
) -> list[str]:
    out = []
    ba, bb = normalize_brand(a.brand), normalize_brand(b.brand)
    if ba and bb and ba != bb:
        out.append(f"brand differs: {a.brand} vs {b.brand}")
    ma, mb = _model(a), _model(b)
    if ma and mb and ma != mb:
        out.append(f"model differs: {a.model} vs {b.model}")
    if na.per_unit and nb.per_unit and na.per_unit != nb.per_unit:
        out.append(f"size differs: {na.per_unit} vs {nb.per_unit}")
    if na.pack_count != nb.pack_count:
        out.append(f"pack count differs: {na.pack_count} vs {nb.pack_count}")
    if na.colour and nb.colour and na.colour != nb.colour:
        out.append(f"colour differs: {na.colour} vs {nb.colour}")
    if na.storage_gb and nb.storage_gb and na.storage_gb != nb.storage_gb:
        out.append(f"storage differs: {na.storage_gb} GB vs {nb.storage_gb} GB")
    if na.ram_gb and nb.ram_gb and na.ram_gb != nb.ram_gb:
        out.append(f"RAM differs: {na.ram_gb} GB vs {nb.ram_gb} GB")
    return out


def classify(source: Listing, candidate: Listing) -> MatchDecision:
    if source.marketplace == candidate.marketplace and (
        source.external_id.casefold() == candidate.external_id.casefold()
    ):
        return MatchDecision(MatchClass.EXACT, ("the product you pasted",))

    ns, nc = _norm(source), _norm(candidate)
    vetoes = _vetoes(source, candidate, ns, nc)
    if vetoes:
        return MatchDecision(MatchClass.MISMATCH, tuple(vetoes))

    warnings = [f"ambiguous: {w}" for w in (*ns.warnings, *nc.warnings)]
    ga, gb = _gtin(source), _gtin(candidate)
    if ga and gb:
        if ga != gb:
            return MatchDecision(MatchClass.MISMATCH, ("barcode differs",))
        reasons = ["barcode matches", *_agreements(ns, nc)]
        if warnings:
            return MatchDecision(MatchClass.PROBABLE, (*reasons, *warnings))
        return MatchDecision(MatchClass.EXACT, tuple(reasons))

    same_brand = bool(normalize_brand(source.brand)) and normalize_brand(
        source.brand
    ) == normalize_brand(candidate.brand)
    ma, mb = _model(source), _model(candidate)
    if same_brand and ma and ma == mb and not warnings:
        return MatchDecision(MatchClass.EXACT, ("brand and model match", *_agreements(ns, nc)))

    if same_brand and ns.per_unit and ns.variant_key() == nc.variant_key():
        return MatchDecision(
            MatchClass.PROBABLE,
            ("brand, size and pack count match", "no barcode to confirm", *warnings),
        )
    return MatchDecision(MatchClass.UNVERIFIED, ("not enough identifying details", *warnings))


def _agreements(na: NormalizedAttributes, nb: NormalizedAttributes) -> list[str]:
    out = []
    if na.per_unit and na.per_unit == nb.per_unit:
        out.append(f"size {na.per_unit}")
    if na.pack_count == nb.pack_count and (na.pack_count_explicit or nb.pack_count_explicit):
        out.append(f"pack of {na.pack_count}")
    if na.colour and na.colour == nb.colour:
        out.append(f"colour {na.colour}")
    return out
