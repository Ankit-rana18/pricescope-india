"""Quantity, pack-count and variant normalization: the facts exact matching relies on."""

from decimal import Decimal

import pytest

from app.models.enums import QuantityUnit
from app.services.normalization import (
    Quantity,
    normalize_attributes,
    normalize_brand,
    normalize_colour,
)

G, ML, U = QuantityUnit.GRAM, QuantityUnit.MILLILITRE, QuantityUnit.UNIT


def q(value: str, unit: QuantityUnit) -> Quantity:
    return Quantity(Decimal(value), unit)


@pytest.mark.parametrize(
    ("title", "per_unit", "pack"),
    [
        # mass, all the spellings
        ("Tata Salt Iodised, 1 kg", q("1000", G), 1),
        ("Tata Salt 1kg", q("1000", G), 1),
        ("Tata Salt 1 KG", q("1000", G), 1),
        ("Aashirvaad Atta 5 Kgs", q("5000", G), 1),
        ("Amul Butter 500g", q("500", G), 1),
        ("Amul Butter 500 gm", q("500", G), 1),
        ("Amul Butter 500 gms", q("500", G), 1),
        ("Amul Butter 500 grams", q("500", G), 1),
        ("Saffola Oats 0.5 kg", q("500.0", G), 1),
        ("Kurkure .5 kg", q("500", G), 1),
        ("Cadbury Dairy Milk 13.2 g", q("13.2", G), 1),
        # volume
        ("Fortune Sunflower Oil 1 L", q("1000", ML), 1),
        ("Fortune Oil 1 Ltr Pouch", q("1000", ML), 1),
        ("Fortune Oil 1 litre", q("1000", ML), 1),
        ("Coca-Cola 1.25 Liter", q("1250", ML), 1),
        ("Bisleri 1,000 ml", q("1000", ML), 1),
        ("Dettol Liquid 200ml", q("200", ML), 1),
        # counts
        ("Eggs 6 pcs", q("6", U), 1),
        ("Tetley Green Tea 100 Tea Bags", q("100", U), 1),
        ("Himalaya Ashvagandha 60 Tablets", q("60", U), 1),
        ("Classmate Notebook 6 N", q("6", U), 1),
        # pack counts
        ("Amul Butter 500g (Pack of 2)", q("500", G), 2),
        ("Amul Butter 500g pack of 2", q("500", G), 2),
        ("Maggi Noodles 70 g Set of 12", q("70", G), 12),
        ("Lays 52g Combo of 5", q("52", G), 5),
        ("Surf Excel 1.5 kg Twin Pack", q("1500", G), 2),
        ("Colgate Toothpaste 150g 3-pack", q("150", G), 3),
        # multipacks
        ("Dove Soap 3 x 100 g", q("100", G), 3),
        ("Dove Soap 3x100g", q("100", G), 3),
        ("Dove Soap 3 \u00d7 100 g", q("100", G), 3),
        ("Cadbury Dairy Milk 13.2 g x 12", q("13.2", G), 12),
        ("Coca-Cola 750 ml x 6", q("750", ML), 6),
        # a total that agrees with the multipack is fine
        ("Dove Cream Bar 3 x 100 g (300 g)", q("100", G), 3),
        ("Amul Butter 500g (Pack of 2) 1 kg", q("500", G), 2),
        # full-width digits (NFKC)
        ("Tata Salt \uff11 kg", q("1000", G), 1),
    ],
)
def test_quantity_and_pack(title: str, per_unit: Quantity, pack: int) -> None:
    attrs = normalize_attributes(title)
    assert attrs.per_unit == per_unit
    assert attrs.pack_count == pack
    assert attrs.warnings == ()


def test_total_and_variant_key() -> None:
    attrs = normalize_attributes("Amul Butter 500g (Pack of 2)")
    assert attrs.total == q("1000", G)
    assert attrs.variant_key() == "500g|x2|-|-|-"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Tata Salt 1 kg", "Tata Salt 500 g"),  # different size
        ("Amul Butter 500g", "Amul Butter 500g (Pack of 2)"),  # pack count
        ("Amul Butter 500g (Pack of 2)", "Amul Butter 1 kg"),  # same total, not same variant
        ("Fortune Oil 1 L", "Fortune Oil 1 kg"),  # volume vs mass
        ("iPhone 15 (128 GB) - Black", "iPhone 15 (256 GB) - Black"),
        ("iPhone 15 (128 GB) - Black", "iPhone 15 (128 GB) - Blue"),
    ],
)
def test_different_variants_get_different_keys(a: str, b: str) -> None:
    assert normalize_attributes(a).variant_key() != normalize_attributes(b).variant_key()


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Tata Salt 1 kg", "TATA SALT 1000g"),
        ("Fortune Oil 1 L", "Fortune Oil 1000 ml"),
        ("Dove Soap 3 x 100 g", "Dove Soap 100g (Pack of 3)"),
        ("Coca-Cola 750 ml x 6", "Coca-Cola 6 x 750ml"),
    ],
)
def test_same_variant_written_differently_gets_same_key(a: str, b: str) -> None:
    assert normalize_attributes(a).variant_key() == normalize_attributes(b).variant_key()


# ------------------------------------------------------------------ traps


def test_network_generation_is_not_grams() -> None:
    attrs = normalize_attributes("Redmi 13 5G (Orchid Pink, 8GB RAM, 128GB Storage)")
    assert attrs.per_unit is None
    assert (attrs.ram_gb, attrs.storage_gb) == (8, 128)
    assert (attrs.colour, attrs.colour_family) == ("orchid pink", "pink")


def test_gigabytes_are_not_grams() -> None:
    assert normalize_attributes("SanDisk 64GB Pen Drive").per_unit is None


def test_strength_is_not_net_quantity() -> None:
    attrs = normalize_attributes("Himalaya Ashvagandha 250 mg, 60 Tablets")
    assert attrs.per_unit == q("60", U)
    assert attrs.strength_mg == Decimal("250")


@pytest.mark.parametrize(
    "title",
    [
        "Catch Black Pepper Powder 100g",
        "Tetley Green Tea 100 Tea Bags",
        "Brooke Bond Red Label 500 g",
    ],
)
def test_colour_words_in_product_names_are_not_colours(title: str) -> None:
    assert normalize_attributes(title).colour is None


@pytest.mark.parametrize(
    ("title", "warning_fragment"),
    [
        ("Aashirvaad Atta 5kg + 1kg free", "do not agree"),
        ("Amul Butter 500g (Pack of 2) (Pack of 3)", "pack count"),
        ("Protein Bar 60 g 12 pcs", "several quantity kinds"),
        ("Phone 128 GB / 256 GB", "storage"),
        ("Amul Butter 500g (Pack of 2000)", "implausible pack count"),
    ],
)
def test_ambiguity_is_reported_not_guessed(title: str, warning_fragment: str) -> None:
    attrs = normalize_attributes(title)
    assert any(warning_fragment in w for w in attrs.warnings), attrs.warnings


def test_no_quantity_is_none_not_zero() -> None:
    attrs = normalize_attributes("Prestige Pressure Cooker")
    assert attrs.per_unit is None
    assert attrs.total is None
    assert attrs.pack_count == 1
    assert attrs.pack_count_explicit is False


# ------------------------------------------------------------------ structured attributes


def test_structured_attributes_win_and_disagreement_is_flagged() -> None:
    attrs = normalize_attributes(
        "Tata Salt 1 kg", {"net_quantity": "500", "net_quantity_unit": "g", "pack_count": 1}
    )
    assert attrs.per_unit == q("500", G)
    assert any("title says 1000g" in w for w in attrs.warnings)


def test_colour_attribute() -> None:
    attrs = normalize_attributes("Boat Airdopes 141", {"colour": "Bold Black"})
    assert (attrs.colour, attrs.colour_family) == ("bold black", "black")


# ------------------------------------------------------------------ helpers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tata", "tata"),
        ("TATA®", "tata"),
        ("Johnson & Johnson", "johnson and johnson"),
        ("  L'Oréal  Paris ", "l oréal paris"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_brand(raw: str | None, expected: str | None) -> None:
    assert normalize_brand(raw) == expected


def test_unknown_colour_keeps_exact_without_family() -> None:
    assert normalize_colour("Cosmic Sparkle") == ("cosmic sparkle", None)
    assert normalize_colour("Black/White") == ("black/white", None)  # two families: no guess
