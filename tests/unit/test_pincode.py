from pathlib import Path

import pytest

from app.services.pincode import (
    DirectoryStatus,
    PincodeDirectory,
    PincodeError,
    normalize_pincode,
    validate_pincode,
)

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "pincode_directory_sample.csv"


@pytest.fixture(scope="module")
def directory() -> PincodeDirectory:
    return PincodeDirectory.from_csv(SAMPLE)


@pytest.mark.parametrize(
    ("raw", "expected"), [("560001", "560001"), (" 560 001 ", "560001"), ("560-001", "560001")]
)
def test_normalizes_common_spacing(raw: str, expected: str) -> None:
    assert normalize_pincode(raw) == expected


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "pincode_empty"),
        ("   ", "pincode_empty"),
        ("56001", "pincode_format"),
        ("5600011", "pincode_format"),
        ("012345", "pincode_format"),
        ("56OO01", "pincode_format"),  # letter O
        ("५६०००१", "pincode_format"),  # non-ASCII digits are refused
        ("560001; DROP TABLE", "pincode_format"),
    ],
)
def test_rejects_malformed(raw: str, code: str) -> None:
    with pytest.raises(PincodeError) as exc:
        normalize_pincode(raw)
    assert exc.value.code == code


def test_without_directory_only_format_is_claimed() -> None:
    info = validate_pincode("560001", PincodeDirectory())
    assert info.directory_status is DirectoryStatus.UNAVAILABLE
    assert info.postal_region == "Southern"
    assert info.district is None and info.state is None


@pytest.mark.parametrize(
    ("pin", "region"),
    [
        ("110001", "Northern"),
        ("400001", "Western"),
        ("700001", "Eastern"),
        ("900001", "Army Postal Service"),
    ],
)
def test_postal_region_from_first_digit(pin: str, region: str) -> None:
    assert validate_pincode(pin, PincodeDirectory()).postal_region == region


def test_directory_lookup_verifies_and_names_the_district(directory: PincodeDirectory) -> None:
    info = validate_pincode("560001", directory)
    assert info.directory_status is DirectoryStatus.VERIFIED
    assert (info.district, info.state) == ("Bengaluru Urban", "Karnataka")
    assert info.post_offices == 2


def test_unknown_pin_is_rejected_when_directory_loaded(directory: PincodeDirectory) -> None:
    with pytest.raises(PincodeError) as exc:
        validate_pincode("560099", directory)
    assert exc.value.code == "pincode_not_found"


def test_malformed_rows_in_directory_are_ignored(directory: PincodeDirectory) -> None:
    assert "0ABCDE" not in directory.entries
    assert set(directory.entries) == {"560001", "110001", "400001"}


def test_directory_without_pincode_column_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("officename,district" + chr(10) + "X,Y" + chr(10), encoding="utf-8")
    with pytest.raises(ValueError, match="pincode"):
        PincodeDirectory.from_csv(bad)


def test_minimal_india_post_file_still_verifies_existence() -> None:
    """data.gov.in 'till last month' file: circle/region/division/office/pincode only."""
    minimal = PincodeDirectory.from_csv(SAMPLE.with_name("pincode_directory_minimal.csv"))
    info = validate_pincode("560001", minimal)
    assert info.directory_status is DirectoryStatus.VERIFIED
    assert (info.district, info.state) == (None, None)  # never guessed from the circle
    assert info.circle == "Karnataka Circle"
    assert info.division == "Bangalore GPO Division"
    assert info.post_offices == 2
    with pytest.raises(PincodeError):
        validate_pincode("560099", minimal)


def test_full_file_reports_division_and_circle_too(directory: PincodeDirectory) -> None:
    info = validate_pincode("560001", directory)
    assert info.circle == "Karnataka Circle"
