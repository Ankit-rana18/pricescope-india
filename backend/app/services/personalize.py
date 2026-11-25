"""Per-viewer adjustments to a comparison, applied when it is shown (never stored or shared).

Card offers: if the viewer has saved which banks' cards they hold, the "best card offer"
on each marketplace, and overall, only considers those banks. The offer list itself is
unchanged, so other offers stay visible.
"""

from decimal import Decimal
from typing import Any

from app.schemas.comparison import CardOfferView, ComparisonView
from app.services.comparison.evaluate import rank_and_summarize


def _norm(bank: str) -> str:
    return " ".join(bank.casefold().replace("bank", "").split())


def card_preferences(preferences: dict[str, Any]) -> tuple[set[str], set[str]]:
    banks = {
        _norm(b) for b in preferences.get("card_banks", []) if isinstance(b, str) and b.strip()
    }
    types = {t for t in preferences.get("card_types", []) if t in ("CREDIT", "DEBIT")}
    return banks, types


def _usable(offer: CardOfferView, banks: set[str], types: set[str]) -> bool:
    if _norm(offer.bank) not in banks:
        return False
    return not types or offer.card_type == "ANY" or offer.card_type in types


def personalize(view: ComparisonView, preferences: dict[str, Any]) -> ComparisonView:
    banks, types = card_preferences(preferences)
    if not banks:
        return view
    out = view.model_copy(deep=True)
    for r in out.results:
        mine = [
            c
            for c in r.card_offers
            if c.discount is not None and c.discount > 0 and _usable(c, banks, types)
        ]
        # card_offers are already ordered best-first (regular offers before EMI-only).
        best = mine[0] if mine else None
        r.best_card = best
        if best is not None and r.price and r.price.final_price_complete and r.price.final_price:
            assert best.discount is not None
            r.price_after_best_card = max(Decimal(0), r.price.final_price - best.discount)
        else:
            r.price_after_best_card = None
    out.results, out.summary = rank_and_summarize(out.results)
    out.cards_personalized = True
    return out
