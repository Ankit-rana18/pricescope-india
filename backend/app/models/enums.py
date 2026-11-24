"""Domain enumerations shared by models, schemas and services."""

from enum import StrEnum


class MarketplaceCode(StrEnum):
    AMAZON_IN = "AMAZON_IN"
    FLIPKART = "FLIPKART"
    BLINKIT = "BLINKIT"
    ZEPTO = "ZEPTO"
    BIGBASKET = "BIGBASKET"


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class IdentifierType(StrEnum):
    GTIN8 = "GTIN8"
    GTIN12 = "GTIN12"  # UPC-A
    GTIN13 = "GTIN13"  # EAN-13
    GTIN14 = "GTIN14"
    ASIN = "ASIN"
    FSN = "FSN"  # Flipkart serial number
    SKU = "SKU"
    MPN = "MPN"  # manufacturer part / model number


class QuantityUnit(StrEnum):
    """Canonical base units after normalization."""

    GRAM = "g"
    MILLILITRE = "ml"
    UNIT = "unit"


class DataMode(StrEnum):
    LIVE = "LIVE"
    DEMO = "DEMO"


class ComparisonStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"  # some marketplaces failed; others returned results
    FAILED = "FAILED"


class ResultStatus(StrEnum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class MatchClass(StrEnum):
    EXACT = "EXACT"
    PROBABLE = "PROBABLE"
    MISMATCH = "MISMATCH"
    UNVERIFIED = "UNVERIFIED"


class Availability(StrEnum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"


class ChargeStatus(StrEnum):
    """Status of one price component. UNKNOWN is never treated as zero."""

    KNOWN = "KNOWN"
    ESTIMATED = "ESTIMATED"  # from a published fee policy, not confirmed for the cart
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class LocationVerification(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIABLE = "UNVERIFIABLE"  # adapter cannot check location at all
    UNAVAILABLE = "UNAVAILABLE"  # checked: not serviceable
    NEEDS_PRECISE_LOCATION = "NEEDS_PRECISE_LOCATION"  # PIN alone is insufficient


class FeeType(StrEnum):
    DELIVERY = "DELIVERY"
    HANDLING = "HANDLING"
    PLATFORM = "PLATFORM"
    SMALL_CART = "SMALL_CART"
    OTHER = "OTHER"


class FeeSource(StrEnum):
    API = "API"
    PUBLISHED_POLICY = "PUBLISHED_POLICY"


class IntegrationStatus(StrEnum):
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    UNSUPPORTED = "UNSUPPORTED"
    DEMO = "DEMO"
