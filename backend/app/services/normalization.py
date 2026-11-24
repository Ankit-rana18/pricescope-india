"""Normalise product attributes so identical variants compare equal.

Extracts from a product title (plus any structured attributes a marketplace provides):

* net quantity per unit, in base units: grams (g), millilitres (ml) or units;
* pack count ("Pack of 2", "2 x 200 g", "200 g x 2", "Twin pack");
* total quantity (per unit x pack count);
* electronics storage / RAM in GB;
* colour (exact phrase + colour family), only from explicit attributes, a parenthesised
  variant group or a trailing " - Colour" suffix; never from free title words
  ("Black Pepper", "Green Tea").

Exact arithmetic (Decimal) throughout. The parser never guesses: anything ambiguous is
reported in ``warnings``, and the matching engine treats warned attributes as unverified.
"""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.enums import QuantityUnit

# --------------------------------------------------------------------------- units

_MASS = {
    "kg": Decimal(1000), "kgs": Decimal(1000), "kilo": Decimal(1000), "kilos": Decimal(1000),
    "kilogram": Decimal(1000), "kilograms": Decimal(1000),
    "g": Decimal(1), "gm": Decimal(1), "gms": Decimal(1), "gr": Decimal(1), "grm": Decimal(1),
    "grms": Decimal(1), "gram": Decimal(1), "grams": Decimal(1), "gramme": Decimal(1),
    "grammes": Decimal(1),
}  # fmt: skip
_VOLUME = {
    "l": Decimal(1000), "lt": Decimal(1000), "ltr": Decimal(1000), "ltrs": Decimal(1000),
    "litre": Decimal(1000), "litres": Decimal(1000), "liter": Decimal(1000),
    "liters": Decimal(1000),
    "ml": Decimal(1), "mls": Decimal(1), "millilitre": Decimal(1), "millilitres": Decimal(1),
    "milliliter": Decimal(1), "milliliters": Decimal(1),
}  # fmt: skip
_COUNT = {
    "pc", "pcs", "piece", "pieces", "n", "nos", "no", "unit", "units", "count", "ct",
    "tablet", "tablets", "capsule", "capsules", "sachet", "sachets",
    "tea bags", "tea bag", "teabags", "bags",
}  # fmt: skip

_UNIT_ALT = "|".join(sorted([*_MASS, *_VOLUME, *_COUNT], key=len, reverse=True))
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|\.\d+)"
# A number followed by a unit, not glued to surrounding letters/digits.
_QTY = re.compile(rf"(?<![\w.]){_NUM}\s*({_UNIT_ALT})(?![a-z0-9])", re.I)
# "2 x 200 g" / "200 g x 2" multipacks (clean_text has already turned the sign into x).
_MULTI_PREFIX = re.compile(
    rf"(?<![\w.])(\d{{1,4}})\s*[x*]\s*{_NUM}\s*({_UNIT_ALT})(?![a-z0-9])", re.I
)
_MULTI_SUFFIX = re.compile(rf"(?<![\w.]){_NUM}\s*({_UNIT_ALT})\s*[x*]\s*(\d{{1,4}})(?![\w.])", re.I)
_PACK_OF = re.compile(r"\b(?:pack|set|combo|pk|box|bundle)\s*of\s*(\d{1,4})\b", re.I)
_N_PACK = re.compile(r"(?<![\w.])(\d{1,4})\s*-?\s*(?:pack|pk)\b(?!\s*of)", re.I)
_WORD_PACK = {"twin pack": 2, "pack of two": 2, "duo pack": 2, "triple pack": 3, "pack of three": 3}
# Mobile network generation ("5G"), not grams. Case-sensitive, glued.
_NETWORK = re.compile(r"(?<![\w.])[2-6]G(?![a-zA-Z0-9])")
# Strength ("500 mg") is not a net quantity.
_STRENGTH = re.compile(rf"(?<![\w.]){_NUM}\s*mg(?![a-z0-9])", re.I)

# "+ 1 kg free", "free 100 g", "20% extra": a bonus changes what you actually get.
_BONUS = re.compile(
    rf"\+\s*{_NUM}\s*(?:{_UNIT_ALT})\s*(?:free|extra|bonus)\b"
    rf"|\b(?:free|extra|bonus)\s*{_NUM}\s*(?:{_UNIT_ALT})(?![a-z0-9])"
    r"|\b\d{1,3}\s*%\s*(?:extra|more|free)\b",
    re.I,
)
_RAM = re.compile(r"(\d{1,3})\s*GB\s*RAM\b", re.I)
_RAM_STORAGE_PAIR = re.compile(r"\b(\d{1,2})\s*(?:GB)?\s*[/+|]\s*(\d{2,4})\s*(GB|TB)\b", re.I)
_STORAGE = re.compile(r"(\d{1,4})\s*(GB|TB)\b(?!\s*RAM)", re.I)

# --------------------------------------------------------------------------- colours

COLOUR_FAMILIES = {
    "black": "black", "jet black": "black", "midnight": "black", "onyx": "black",
    "graphite": "grey", "grey": "grey", "gray": "grey", "space grey": "grey",
    "space gray": "grey", "charcoal": "grey",
    "white": "white", "ivory": "white", "pearl white": "white", "starlight": "white",
    "silver": "silver", "gold": "gold", "rose gold": "gold",
    "blue": "blue", "navy": "blue", "navy blue": "blue", "sky blue": "blue", "teal": "blue",
    "red": "red", "maroon": "red", "crimson": "red",
    "green": "green", "olive": "green", "mint": "green",
    "yellow": "yellow", "orange": "orange", "pink": "pink", "purple": "purple",
    "violet": "purple", "lavender": "purple", "brown": "brown", "beige": "brown",
    "multicolor": "multicolour", "multicolour": "multicolour",
}  # fmt: skip
_COLOUR_WORDS = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, COLOUR_FAMILIES), key=len, reverse=True)) + r")\b",
    re.I,
)
_PARENS = re.compile(r"\(([^()]{1,120})\)")
_TRAILING = re.compile(r"\s[-\u2013|]\s([^-\u2013|()]{1,40})$")


@dataclass(frozen=True)
class Quantity:
    value: Decimal  # in base unit
    unit: QuantityUnit

    def __mul__(self, n: int) -> "Quantity":
        return Quantity(self.value * n, self.unit)

    def __str__(self) -> str:
        return f"{format(self.value.normalize(), 'f')}{self.unit.value}"


@dataclass(frozen=True)
class NormalizedAttributes:
    per_unit: Quantity | None = None
    pack_count: int = 1
    pack_count_explicit: bool = False
    storage_gb: int | None = None
    ram_gb: int | None = None
    colour: str | None = None
    colour_family: str | None = None
    strength_mg: Decimal | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total(self) -> Quantity | None:
        return self.per_unit * self.pack_count if self.per_unit else None

    def variant_key(self) -> str:
        """Deterministic key: equal keys mean the same variant, e.g. '500g|x2|-|-|-'."""
        parts = [
            str(self.per_unit) if self.per_unit else "-",
            f"x{self.pack_count}",
            self.colour or "-",
            f"s{self.storage_gb}" if self.storage_gb else "-",
            f"r{self.ram_gb}" if self.ram_gb else "-",
        ]
        return "|".join(parts)


# --------------------------------------------------------------------------- helpers


def clean_text(text: str) -> str:
    """NFKC (full-width digits, ligatures), unify multiplication signs and spaces."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("\u00a0", " ").replace("\u00d7", " x ")
    return re.sub(r"\s+", " ", t).strip()


def _decimal(raw: str) -> Decimal | None:
    try:
        d = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    return d if d.is_finite() and d > 0 else None


def to_quantity(number: str, unit: str) -> Quantity | None:
    value = _decimal(number)
    u = unit.lower()
    if value is None:
        return None
    if u in _MASS:
        return Quantity(value * _MASS[u], QuantityUnit.GRAM)
    if u in _VOLUME:
        return Quantity(value * _VOLUME[u], QuantityUnit.MILLILITRE)
    if u in _COUNT:
        if value != value.to_integral_value():
            return None
        return Quantity(value, QuantityUnit.UNIT)
    return None


def normalize_brand(brand: str | None) -> str | None:
    if not brand:
        return None
    t = clean_text(brand).casefold()
    t = re.sub(r"[™®©]", "", t).replace("&", " and ")
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def normalize_colour(value: str | None) -> tuple[str | None, str | None]:
    """('midnight black', 'black') from 'Midnight Black'; family None if unknown."""
    if not value:
        return None, None
    exact = re.sub(r"\s+", " ", clean_text(value).casefold()).strip(" -,")
    if not exact:
        return None, None
    words = _COLOUR_WORDS.findall(exact)
    families = {COLOUR_FAMILIES[w.lower()] for w in words}
    return exact, (families.pop() if len(families) == 1 else None)


def _pack_from_words(t: str) -> int | None:
    low = t.casefold()
    for phrase, n in _WORD_PACK.items():
        if phrase in low:
            return n
    return None


# --------------------------------------------------------------------------- main entry


def normalize_attributes(
    title: str, attributes: Mapping[str, Any] | None = None
) -> NormalizedAttributes:
    """Parse a title plus optional structured attributes (which take precedence)."""
    attrs = dict(attributes or {})
    text = clean_text(title)
    warnings: list[str] = []
    scan = _NETWORK.sub(" ", text)  # "Redmi 13 5G" must not read as 5 grams

    if _BONUS.search(scan):
        warnings.append("includes a free or bonus quantity")

    strength = None
    if m := _STRENGTH.search(scan):
        strength = _decimal(m.group(1))
        scan = _STRENGTH.sub(" ", scan)

    # ---- explicit multipacks: "2 x 200 g", "200 g x 2"
    per_unit: Quantity | None = None
    pack: int | None = None
    multi_hits: list[tuple[Quantity, int]] = []
    for m in _MULTI_PREFIX.finditer(scan):
        q = to_quantity(m.group(2), m.group(3))
        if q:
            multi_hits.append((q, int(m.group(1))))
    for m in _MULTI_SUFFIX.finditer(scan):
        q = to_quantity(m.group(1), m.group(2))
        if q:
            multi_hits.append((q, int(m.group(3))))
    if multi_hits:
        per_unit, pack = multi_hits[0]
        if len(set(multi_hits)) > 1:
            warnings.append("conflicting multipack expressions")
        scan = _MULTI_SUFFIX.sub(" ", _MULTI_PREFIX.sub(" ", scan))

    # ---- "Pack of 3", "3-pack", "Twin pack"
    pack_mentions = [int(n) for n in _PACK_OF.findall(scan)] + [
        int(n) for n in _N_PACK.findall(scan)
    ]
    if (word := _pack_from_words(scan)) is not None:
        pack_mentions.append(word)
    pack_mentions = [n for n in pack_mentions if n >= 1]
    if pack_mentions:
        distinct = set(pack_mentions)
        if pack is not None and distinct != {pack}:
            warnings.append("pack count stated inconsistently")
        elif pack is None:
            if len(distinct) > 1:
                warnings.append("pack count stated inconsistently")
            pack = pack_mentions[0]
    scan = _N_PACK.sub(" ", _PACK_OF.sub(" ", scan))

    # ---- single quantities
    quantities = [q for m in _QTY.finditer(scan) if (q := to_quantity(m.group(1), m.group(2)))]
    if per_unit is None and quantities:
        per_unit = quantities[0]
        others = quantities[1:]
    else:
        others = quantities
    effective_pack = pack or 1
    for q in others:
        if per_unit is None:
            break
        if q == per_unit or q == per_unit * effective_pack:
            continue  # repeats the unit size or states the total: consistent
        if q.unit is not per_unit.unit:
            # e.g. "60 tablets" alongside "120 g": keep the first, flag it
            warnings.append(f"several quantity kinds ({per_unit} and {q})")
        else:
            warnings.append(f"quantities {per_unit} and {q} do not agree")

    # ---- structured attributes override title parsing
    if attrs.get("net_quantity") is not None and attrs.get("net_quantity_unit"):
        q = to_quantity(str(attrs["net_quantity"]), str(attrs["net_quantity_unit"]))
        if q is None:
            warnings.append("unparseable net_quantity attribute")
        else:
            if per_unit is not None and q != per_unit:
                warnings.append(f"title says {per_unit} but attributes say {q}")
            per_unit = q
    if attrs.get("pack_count") is not None:
        try:
            explicit_pack = int(attrs["pack_count"])
        except (TypeError, ValueError):
            warnings.append("unparseable pack_count attribute")
        else:
            if pack is not None and explicit_pack != pack:
                warnings.append(f"title says pack of {pack} but attributes say {explicit_pack}")
            pack = explicit_pack

    if pack is not None and not 1 <= pack <= 1000:
        warnings.append(f"implausible pack count {pack}")
        pack = None

    # ---- electronics
    ram = storage = None
    if m := _RAM_STORAGE_PAIR.search(text):
        ram, storage = (
            int(m.group(1)),
            int(m.group(2)) * (1024 if m.group(3).upper() == "TB" else 1),
        )
    if m := _RAM.search(text):
        ram = int(m.group(1))
    if storage is None:
        sizes = [
            int(n) * (1024 if u.upper() == "TB" else 1)
            for n, u in _STORAGE.findall(_RAM.sub(" ", text))
        ]
        sizes = [s for s in sizes if s != ram]
        if sizes:
            storage = max(sizes)
            if len(set(sizes)) > 1:
                warnings.append("several storage sizes mentioned")

    # ---- colour: explicit attribute, else a parenthesised group or trailing " - X"
    colour, family = normalize_colour(attrs.get("colour") or attrs.get("color"))
    if colour is None:
        groups = _PARENS.findall(text)
        if m := _TRAILING.search(text):
            groups.append(m.group(1))
        for group in groups:
            for piece in group.split(","):
                piece = piece.strip()
                if _COLOUR_WORDS.fullmatch(piece) or (
                    _COLOUR_WORDS.search(piece)
                    and len(piece.split()) <= 3
                    and not re.search(r"\d", piece)
                ):
                    colour, family = normalize_colour(piece)
                    break
            if colour:
                break

    return NormalizedAttributes(
        per_unit=per_unit,
        pack_count=pack or 1,
        pack_count_explicit=pack is not None,
        storage_gb=storage,
        ram_gb=ram,
        colour=colour,
        colour_family=family,
        strength_mg=strength,
        warnings=tuple(dict.fromkeys(warnings)),
    )
