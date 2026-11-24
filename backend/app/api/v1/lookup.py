"""Product-link and PIN-code checks. No marketplace is contacted."""

from functools import lru_cache
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorResponse
from app.schemas.lookup import (
    FieldError,
    LookupRequest,
    LookupResult,
    PincodeRequest,
    PincodeResult,
    ProductLinkResult,
)
from app.services.pincode import (
    DELIVERY_NOTE,
    PincodeDirectory,
    PincodeError,
    PincodeInfo,
    load_directory,
    validate_pincode,
)
from app.services.safe_http import SafeRedirectResolver
from app.services.url_parser import (
    NAMES,
    ParsedProductUrl,
    UrlParseError,
    all_link_hosts,
    resolve_product_url,
)

router = APIRouter(tags=["lookup"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Invalid link or PIN code"}
}


class InvalidInput(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "invalid_input"

    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__(
            errors[0].message,
            details={"fields": [e.model_dump() for e in errors]},
        )


def get_pincode_directory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PincodeDirectory:
    return load_directory(settings.pincode_directory_file)


Directory = Annotated[PincodeDirectory, Depends(get_pincode_directory)]


@lru_cache
def get_link_resolver() -> SafeRedirectResolver:
    return SafeRedirectResolver(all_link_hosts())


LinkResolver = Annotated[SafeRedirectResolver, Depends(get_link_resolver)]


def _pincode_result(info: PincodeInfo) -> PincodeResult:
    return PincodeResult(
        pincode=info.pincode,
        postal_region=info.postal_region,
        directory_status=info.directory_status,
        district=info.district,
        state=info.state,
        post_offices=info.post_offices,
        delivery_note=DELIVERY_NOTE,
    )


def _product_result(parsed: ParsedProductUrl) -> ProductLinkResult:
    return ProductLinkResult(
        marketplace=parsed.marketplace,
        marketplace_name=NAMES[parsed.marketplace],
        external_id=parsed.external_id,
        id_type=parsed.id_type,
        canonical_url=parsed.canonical_url,
        resolved_from=parsed.resolved_from,
    )


@router.post(
    "/location/validate",
    response_model=PincodeResult,
    summary="Validate a 6-digit Indian PIN code",
    responses=_ERRORS,
)
def validate_location(body: PincodeRequest, directory: Directory) -> PincodeResult:
    try:
        return _pincode_result(validate_pincode(body.pincode, directory))
    except PincodeError as exc:
        raise InvalidInput(
            [FieldError(field="pincode", code=exc.code, message=exc.message)]
        ) from None


@router.post(
    "/lookups/validate",
    response_model=LookupResult,
    summary="Check a product link and PIN code before comparing",
    description="Recognises the marketplace and product ID from the link and validates the "
    "PIN code. Short links (amzn.in, amzn.to, dl.flipkart.com/s) are followed through an "
    "SSRF-safe resolver; no product page is fetched. Reports every invalid field at once.",
    responses=_ERRORS,
)
def validate_lookup(
    body: LookupRequest, directory: Directory, link_resolver: LinkResolver
) -> LookupResult:
    errors: list[FieldError] = []
    product = location = None
    try:
        product = _product_result(resolve_product_url(body.url, link_resolver))
    except UrlParseError as exc:
        errors.append(FieldError(field="url", code=exc.code, message=exc.message))
    try:
        location = _pincode_result(validate_pincode(body.pincode, directory))
    except PincodeError as exc:
        errors.append(FieldError(field="pincode", code=exc.code, message=exc.message))
    if errors or product is None or location is None:
        raise InvalidInput(errors)
    return LookupResult(product=product, location=location)
