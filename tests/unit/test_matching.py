"""Exact-variant matching: what counts as the same product, and what is rejected."""

from typing import Any

import pytest
from pricescope_integrations.models import DataSource, Listing, Marketplace

from app.models.enums import MatchClass
from app.services.matching import classify


def L(title: str, m: Marketplace = Marketplace.FLIPKART, **kw: Any) -> Listing:
    kw.setdefault("external_id", title[:20])
    return Listing(marketplace=m, title=title, data_source=DataSource.DEMO, **kw)


SRC = L(
    "Saltwise Iodised Salt, 1 kg",
    Marketplace.AMAZON_IN,
    brand="Saltwise",
    gtin="2000000000015",
    external_id="DEMO000001",
)


def test_same_listing_is_exact() -> None:
    same = L("anything", Marketplace.AMAZON_IN, external_id="demo000001")
    assert classify(SRC, same).match_class is MatchClass.EXACT


def test_barcode_and_size_agree_is_exact() -> None:
    d = classify(SRC, L("Saltwise Iodised Salt (1000 g)", brand="Saltwise", gtin="2000000000015"))
    assert d.match_class is MatchClass.EXACT
    assert "barcode matches" in d.reasons
    assert d.score == 1


def test_ean13_and_gtin14_forms_compare_equal() -> None:
    d = classify(SRC, L("Saltwise Salt 1 kg", brand="Saltwise", gtin="02000000000015"))
    assert d.match_class is MatchClass.EXACT


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (L("Saltwise Iodised Salt, 500 g", brand="Saltwise", gtin="2000000000015"), "size differs"),
        (
            L("Saltwise Iodised Salt 1 kg (Pack of 2)", brand="Saltwise", gtin="2000000000015"),
            "pack count",
        ),
        (L("Saltmax Iodised Salt 1 kg", brand="Saltmax", gtin="2000000000015"), "brand differs"),
        (
            L("Saltwise Iodised Salt 1 kg", brand="Saltwise", gtin="2000000000022"),
            "barcode differs",
        ),
    ],
)
def test_conflicting_attributes_are_rejected_even_with_matching_barcode(
    candidate: Listing, reason: str
) -> None:
    d = classify(SRC, candidate)
    assert d.match_class is MatchClass.MISMATCH
    assert any(reason in r for r in d.reasons), d.reasons


def test_phone_colour_storage_and_ram_vetoes() -> None:
    src = L(
        "Nimbus X2 5G (Midnight Black, 8GB RAM, 128GB Storage)",
        Marketplace.AMAZON_IN,
        brand="Nimbus",
        model="NX2-8128",
        external_id="P1",
    )
    blue = L("Nimbus X2 5G (Ocean Blue, 128 GB) (8 GB RAM)", brand="Nimbus", model="NX2-8128")
    bigger = L("Nimbus X2 5G (Midnight Black, 256 GB) (8 GB RAM)", brand="Nimbus", model="NX2-8128")
    more_ram = L(
        "Nimbus X2 5G (Midnight Black, 12GB RAM, 128GB Storage)", brand="Nimbus", model="NX2-8128"
    )
    for cand, reason in ((blue, "colour"), (bigger, "storage"), (more_ram, "RAM")):
        d = classify(src, cand)
        assert d.match_class is MatchClass.MISMATCH
        assert any(reason in r for r in d.reasons)


def test_brand_and_model_without_barcode_is_exact() -> None:
    src = L(
        "Nimbus X2 5G (Midnight Black, 128 GB)",
        Marketplace.AMAZON_IN,
        brand="Nimbus",
        model="NX2-8128",
        external_id="P1",
    )
    cand = L("NIMBUS X2 5G (Midnight Black, 128GB)", brand="nimbus", model="nx2-8128")
    assert classify(src, cand).match_class is MatchClass.EXACT


def test_same_brand_and_size_without_identifier_is_only_probable() -> None:
    d = classify(SRC, L("Saltwise Iodised Salt 1 kg", brand="Saltwise"))
    assert d.match_class is MatchClass.PROBABLE
    assert "no barcode or model number to confirm" in d.reasons


def test_ambiguous_attributes_downgrade_barcode_match_to_probable() -> None:
    d = classify(SRC, L("Saltwise Salt 1 kg + 1 kg free", brand="Saltwise", gtin="2000000000015"))
    assert d.match_class is MatchClass.PROBABLE


def test_too_little_information_is_unverified() -> None:
    d = classify(SRC, L("Iodised salt", brand=None))
    assert d.match_class is MatchClass.UNVERIFIED
