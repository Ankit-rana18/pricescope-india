"""Request and response models for product-link and PIN-code checks."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import MarketplaceCode
from app.services.pincode import DirectoryStatus


class PincodeRequest(BaseModel):
    pincode: str = Field(max_length=16, examples=["560001"])


class LookupRequest(BaseModel):
    url: str = Field(max_length=4096, examples=["https://www.amazon.in/dp/B0EXAMPLE1"])
    pincode: str = Field(max_length=16, examples=["560001"])


class PincodeResult(BaseModel):
    pincode: str
    postal_region: str
    directory_status: DirectoryStatus = Field(
        description="VERIFIED: found in the India Post directory. UNAVAILABLE: the directory "
        "is not loaded, so only the format was checked."
    )
    district: str | None = None
    state: str | None = None
    post_offices: int = 0
    delivery_note: str


class ProductLinkResult(BaseModel):
    marketplace: MarketplaceCode
    marketplace_name: str
    external_id: str
    id_type: str
    canonical_url: str
    resolved_from: str | None = Field(
        default=None, description="The short link that was followed to find this product."
    )


class LookupResult(BaseModel):
    product: ProductLinkResult
    location: PincodeResult
    comparison_available: Literal[False] = Field(
        default=False,
        description="Price comparison is not built yet. The only outbound request is "
        "following a short link's redirects; product pages are never fetched.",
    )


class FieldError(BaseModel):
    field: Literal["url", "pincode"]
    code: str
    message: str
