"""Title similarity (RapidFuzz). A secondary signal only: it can separate PROBABLE from
UNVERIFIED, but never makes a match EXACT and never overrides a hard veto."""

import re

from rapidfuzz import fuzz

from app.services.normalization import clean_text

# Words that describe packaging or marketing, not the product's identity.
_NOISE = {
    "pack", "of", "combo", "set", "pouch", "jar", "bottle", "carton", "box", "the",
    "and", "with", "new", "free", "extra", "offer", "pcs", "pc", "n", "x",
}  # fmt: skip
_QUANTITY = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:kg|kgs|g|gm|gms|grams?|mg|l|ltr|litres?|liters?|ml|gb|tb|%)\b",
    re.I,
)


def core_title(title: str, brand: str | None = None) -> str:
    """Lower-case words that identify the product, minus sizes, packs and the brand."""
    text = clean_text(title).casefold()
    text = _QUANTITY.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if w not in _NOISE and not w.isdigit()]
    if brand:
        brand_words = set(re.sub(r"[^\w\s]", " ", brand.casefold()).split())
        words = [w for w in words if w not in brand_words]
    return " ".join(words)


def title_similarity(a: str, b: str, brand_a: str | None = None, brand_b: str | None = None) -> int:
    """0-100. Average of order-insensitive and subset-tolerant scores on core titles."""
    ca, cb = core_title(a, brand_a), core_title(b, brand_b)
    if not ca or not cb:
        return 0
    return round((fuzz.token_sort_ratio(ca, cb) + fuzz.token_set_ratio(ca, cb)) / 2)
