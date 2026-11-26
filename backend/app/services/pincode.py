"""Indian PIN-code validation.

1. Format: six digits, not starting with 0.
2. Postal region from the first digit (India Post's published zone scheme).
3. Existence: looked up in the India Post directory (open data CSV) when
   ``PRICESCOPE_PINCODE_DIRECTORY_FILE`` points at it. Without the file the result says
   the directory check is unavailable; it never claims a PIN exists.

A valid PIN never implies delivery: each marketplace is checked separately later.
"""

import csv
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.core.singleton import once

PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")

# First digit -> India Post postal zone.
POSTAL_REGIONS = {
    "1": "Northern",
    "2": "Northern",
    "3": "Western",
    "4": "Western",
    "5": "Southern",
    "6": "Southern",
    "7": "Eastern",
    "8": "Eastern",
    "9": "Army Postal Service",
}

DELIVERY_NOTE = (
    "A valid PIN code does not guarantee delivery. Each marketplace's serviceability is "
    "checked separately, and some need a more precise location."
)

# Accepted header spellings across published versions of the India Post dataset.
# Only pincode + office name are required; the "till last month" resource on data.gov.in
# lists circle/region/division/office/pincode, while older versions add district + state.
_REQUIRED = {
    "pincode": ("pincode", "pin code", "pin"),
    "office": ("officename", "office name", "office"),
}
_OPTIONAL = {
    "district": ("district", "districtname", "district name"),
    "state": ("statename", "state name", "state"),
    "division": ("divisionname", "division name", "division"),
    "circle": ("circlename", "circle name", "circle"),
}


class DirectoryStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


class PincodeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PostOffice:
    name: str
    district: str | None = None
    state: str | None = None
    division: str | None = None
    circle: str | None = None


@dataclass(frozen=True)
class PincodeInfo:
    pincode: str
    postal_region: str
    directory_status: DirectoryStatus
    district: str | None = None
    state: str | None = None
    division: str | None = None
    circle: str | None = None
    post_offices: int = 0


def _most_common(values: list[str | None]) -> str | None:
    present = [v for v in values if v]
    return max(set(present), key=present.count) if present else None


@dataclass
class PincodeDirectory:
    """In-memory index: about 165k post offices fit easily in memory."""

    entries: dict[str, list[PostOffice]] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.entries)

    @classmethod
    def from_csv(cls, path: Path) -> "PincodeDirectory":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            normalized = {(h or "").strip().lower(): h for h in reader.fieldnames or []}

            def find(aliases: tuple[str, ...]) -> str | None:
                return next((normalized[a] for a in aliases if a in normalized), None)

            columns: dict[str, str | None] = {}
            for key, aliases in _REQUIRED.items():
                found = find(aliases)
                if found is None:
                    raise ValueError(f"PIN directory CSV has no {key!r} column")
                columns[key] = found
            for key, aliases in _OPTIONAL.items():
                columns[key] = find(aliases)

            def cell(row: dict[str, str], key: str, title: bool = True) -> str | None:
                col = columns.get(key)
                value = (row.get(col) or "").strip() if col else ""
                if not value or value.upper() in ("NA", "N/A", "NULL"):
                    return None
                return value.title() if title else value

            entries: dict[str, list[PostOffice]] = {}
            for row in reader:
                pin = (row.get(columns["pincode"] or "") or "").strip()
                if not PINCODE_RE.fullmatch(pin):
                    continue
                entries.setdefault(pin, []).append(
                    PostOffice(
                        name=cell(row, "office", title=False) or "",
                        district=cell(row, "district"),
                        state=cell(row, "state"),
                        division=cell(row, "division", title=False),
                        circle=cell(row, "circle", title=False),
                    )
                )
        return cls(entries)

    def lookup(self, pincode: str) -> list[PostOffice]:
        return self.entries.get(pincode, [])


@once
def load_directory(path: str) -> PincodeDirectory:
    if not path:
        return PincodeDirectory()
    return PincodeDirectory.from_csv(Path(path))


def normalize_pincode(raw: str) -> str:
    """Accept common spacing like '560 001'; reject everything else."""
    text = re.sub(r"[\s-]", "", raw or "")
    if not text:
        raise PincodeError("pincode_empty", "Enter your 6-digit PIN code.")
    # ASCII digits only: str.isdigit() would also accept e.g. Devanagari numerals.
    if not re.fullmatch(r"[0-9]{6}", text):
        raise PincodeError("pincode_format", "A PIN code is exactly 6 digits.")
    if text[0] == "0":
        raise PincodeError("pincode_format", "Indian PIN codes don't start with 0.")
    return text


def validate_pincode(raw: str, directory: PincodeDirectory) -> PincodeInfo:
    pin = normalize_pincode(raw)
    region = POSTAL_REGIONS[pin[0]]
    if not directory.available:
        return PincodeInfo(pin, region, DirectoryStatus.UNAVAILABLE)
    offices = directory.lookup(pin)
    if not offices:
        raise PincodeError(
            "pincode_not_found", "We couldn't find this PIN code in the India Post directory."
        )
    # Most PINs sit in one district; report the most common values.
    return PincodeInfo(
        pin,
        region,
        DirectoryStatus.VERIFIED,
        district=_most_common([o.district for o in offices]),
        state=_most_common([o.state for o in offices]),
        division=_most_common([o.division for o in offices]),
        circle=_most_common([o.circle for o in offices]),
        post_offices=len(offices),
    )
