"""Identifier normalisation: barcodes, model numbers and brand names."""

import json
import re
from functools import cache
from pathlib import Path

from app.services.normalization import normalize_brand


def gtin_check_digit_ok(digits: str) -> bool:
    """GS1 mod-10 check for GTIN-8/12/13/14."""
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def normalize_gtin(raw: str | None) -> tuple[str | None, str | None]:
    """(GTIN-14 or None, warning or None). EAN-13 and UPC-A forms compare equal.

    A barcode with a wrong check digit is ignored (a typo would otherwise force a
    MISMATCH or a false EXACT); the warning says so.
    """
    if not raw:
        return None, None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) not in (8, 12, 13, 14):
        return None, f"ignored malformed barcode {raw!r}"
    if not gtin_check_digit_ok(digits):
        return None, f"ignored barcode {raw!r} with an invalid check digit"
    return digits.zfill(14), None


def compact_model(raw: str | None) -> str | None:
    """'NX2-8128', 'nx2 8128' and 'NX2/8128' all become 'nx28128'."""
    if not raw:
        return None
    out = re.sub(r"[^0-9a-z]", "", raw.casefold())
    return out or None


@cache
def _aliases() -> dict[str, str]:
    path = Path(__file__).with_name("brand_aliases.json")
    data: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))["aliases"]
    table: dict[str, str] = {}
    for canonical, variants in data.items():
        key = _compact(canonical)
        table[key] = key
        for v in variants:
            table[_compact(v)] = key
    return table


def _compact(brand: str) -> str:
    return re.sub(r"\s+", "", normalize_brand(brand) or "")


def brand_key(brand: str | None) -> str | None:
    """Canonical brand key: case, punctuation, spacing and known aliases folded."""
    if not brand:
        return None
    key = _compact(brand)
    if not key:
        return None
    return _aliases().get(key, key)


def brand_in_title(brand: str | None, title: str) -> bool:
    """True if the brand's words appear at the start of the title (brand field missing)."""
    words = (normalize_brand(brand) or "").split()
    if not words:
        return False
    title_words = (normalize_brand(title) or "").split()
    return title_words[: len(words)] == words
