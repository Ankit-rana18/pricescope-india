"""Import every model so Alembic autogenerate sees the full metadata."""

from app.models.base import Base
from app.models.catalog import (
    Marketplace,
    MarketplaceProduct,
    Product,
    ProductIdentifier,
    ProductVariant,
)
from app.models.comparison import (
    Comparison,
    ComparisonResult,
    DeliveryFee,
    LocationCheck,
    PriceHistory,
)
from app.models.integration import IntegrationCredential, IntegrationHealthLog, PincodeDirectory
from app.models.user import AuditLog, PriceAlert, SavedProduct, User

__all__ = [
    "AuditLog",
    "Base",
    "Comparison",
    "ComparisonResult",
    "DeliveryFee",
    "IntegrationCredential",
    "IntegrationHealthLog",
    "LocationCheck",
    "Marketplace",
    "MarketplaceProduct",
    "PincodeDirectory",
    "PriceAlert",
    "PriceHistory",
    "Product",
    "ProductIdentifier",
    "ProductVariant",
    "SavedProduct",
    "User",
]
