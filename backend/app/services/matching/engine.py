"""Deterministic product matching.

Rules, in order (the first that applies decides):
1. Same marketplace + same listing ID                       -> EXACT
2. Hard vetoes: brand, model, net quantity, pack count, colour,
   storage or RAM differ (when both sides state them)         -> MISMATCH (always wins)
3. Valid barcodes (GTIN/EAN/UPC, check digit verified) on both sides:
   different -> MISMATCH; equal -> EXACT, or PROBABLE if either side's
   attributes are ambiguous or the titles disagree badly
4. Same brand + same model number + no ambiguity            -> EXACT
5. Same brand + same size/pack/variant + similar titles      -> PROBABLE
6. Otherwise                                                 -> UNVERIFIED

Title similarity (RapidFuzz) only separates PROBABLE from UNVERIFIED. It never creates an
EXACT match and never overrides a veto. PROBABLE and UNVERIFIED results are never ranked.
"""

from dataclasses import dataclass
from decimal import Decimal

from pricescope_integrations.models import Listing

from app.models.enums import MatchClass
from app.services.matching.fuzzy import title_similarity
from app.services.matching.identifiers import (
    brand_in_title,
    brand_key,
    compact_model,
    normalize_gtin,
)
from app.services.normalization import NormalizedAttributes, normalize_attributes

PROBABLE_MIN_SIMILARITY = 85
BARCODE_TITLE_FLOOR = 40  # equal barcodes but titles this different -> suspect data
SOURCE_REASON = "the product you pasted"


@dataclass(frozen=True)
class MatchDecision:
    match_class: MatchClass
    reasons: tuple[str, ...]
    similarity: int | None = None

    @property
    def score(self) -> Decimal:
        """0-1 confidence shown to users; the class, not the score, drives ranking."""
        if self.match_class is MatchClass.EXACT:
            return Decimal("1.000")
        if self.match_class is MatchClass.MISMATCH:
            return Decimal("0.000")
        sim = Decimal(self.similarity or 0) / 100
        if self.match_class is MatchClass.PROBABLE:
            return (Decimal("0.6") + Decimal("0.3") * sim).quantize(Decimal("0.001"))
        return (Decimal("0.5") * sim).quantize(Decimal("0.001"))


def _norm(listing: Listing) -> NormalizedAttributes:
    return normalize_attributes(listing.title, listing.attributes)


def _same_brand(a: Listing, b: Listing) -> tuple[bool | None, str | None]:
    """(True/False when decidable, None when unknown; reason)."""
    ka, kb = brand_key(a.brand), brand_key(b.brand)
    if ka and kb:
        return ka == kb, None
    if ka and not kb and brand_in_title(a.brand, b.title):
        return True, "brand taken from title"
    if kb and not ka and brand_in_title(b.brand, a.title):
        return True, "brand taken from title"
    return None, None


def _vetoes(
    a: Listing, b: Listing, na: NormalizedAttributes, nb: NormalizedAttributes
) -> list[str]:
    out = []
    same_brand, _ = _same_brand(a, b)
    if same_brand is False:
        out.append(f"brand differs: {a.brand} vs {b.brand}")
    ma, mb = compact_model(a.model), compact_model(b.model)
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


def _agreements(na: NormalizedAttributes, nb: NormalizedAttributes) -> list[str]:
    out = []
    if na.per_unit and na.per_unit == nb.per_unit:
        out.append(f"size {na.per_unit}")
    if na.pack_count == nb.pack_count and (na.pack_count_explicit or nb.pack_count_explicit):
        out.append(f"pack of {na.pack_count}")
    if na.colour and na.colour == nb.colour:
        out.append(f"colour {na.colour}")
    if na.storage_gb and na.storage_gb == nb.storage_gb:
        out.append(f"{na.storage_gb} GB storage")
    return out


def _variant_agrees(na: NormalizedAttributes, nb: NormalizedAttributes) -> bool:
    """Enough of the variant is stated, and everything stated agrees."""
    if na.per_unit:
        return na.variant_key() == nb.variant_key()
    stated = [
        (na.colour, nb.colour),
        (na.storage_gb, nb.storage_gb),
        (na.ram_gb, nb.ram_gb),
    ]
    known = [(x, y) for x, y in stated if x is not None or y is not None]
    return bool(known) and all(x == y for x, y in known)


def classify(source: Listing, candidate: Listing) -> MatchDecision:
    if source.marketplace == candidate.marketplace and (
        source.external_id.casefold() == candidate.external_id.casefold()
    ):
        return MatchDecision(MatchClass.EXACT, (SOURCE_REASON,), 100)

    ns, nc = _norm(source), _norm(candidate)
    vetoes = _vetoes(source, candidate, ns, nc)
    if vetoes:
        return MatchDecision(MatchClass.MISMATCH, tuple(vetoes))

    similarity = title_similarity(source.title, candidate.title, source.brand, candidate.brand)
    sim_reason = f"title similarity {similarity}%"
    ga, wa = normalize_gtin(source.gtin)
    gb, wb = normalize_gtin(candidate.gtin)
    warnings = [f"ambiguous: {w}" for w in (*ns.warnings, *nc.warnings)]
    warnings += [w for w in (wa, wb) if w]

    if ga and gb:
        if ga != gb:
            return MatchDecision(MatchClass.MISMATCH, ("barcode differs",), similarity)
        reasons = ["barcode matches", *_agreements(ns, nc)]
        if warnings:
            return MatchDecision(MatchClass.PROBABLE, (*reasons, *warnings, sim_reason), similarity)
        if similarity < BARCODE_TITLE_FLOOR:
            return MatchDecision(
                MatchClass.PROBABLE,
                (*reasons, f"titles disagree ({similarity}%): barcode data may be wrong"),
                similarity,
            )
        return MatchDecision(MatchClass.EXACT, tuple(reasons), similarity)

    same_brand, brand_note = _same_brand(source, candidate)
    brand_reasons = [brand_note] if brand_note else []
    ma, mb = compact_model(source.model), compact_model(candidate.model)
    if same_brand and ma and ma == mb and not warnings:
        return MatchDecision(
            MatchClass.EXACT,
            ("brand and model match", *brand_reasons, *_agreements(ns, nc)),
            similarity,
        )

    if same_brand and _variant_agrees(ns, nc):
        if similarity >= PROBABLE_MIN_SIMILARITY:
            return MatchDecision(
                MatchClass.PROBABLE,
                (
                    "brand and variant match",
                    *brand_reasons,
                    sim_reason,
                    "no barcode or model number to confirm",
                    *warnings,
                ),
                similarity,
            )
        return MatchDecision(
            MatchClass.UNVERIFIED,
            ("brand and variant match", f"but titles differ ({similarity}%)", *warnings),
            similarity,
        )
    return MatchDecision(
        MatchClass.UNVERIFIED, ("not enough identifying details", sim_reason, *warnings), similarity
    )
