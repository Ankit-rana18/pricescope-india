"""Authentication and authorization.

Two modes (``PRICESCOPE_AUTH_MODE``):

* ``supabase`` - the browser signs in with Supabase Auth and sends its access token
  (``Authorization: Bearer <jwt>``). The token is verified here: signature against the
  project's JWKS (or, for older projects, the shared HS256 secret), issuer, audience and
  expiry. Nothing about the user is trusted unless the token verifies.
* ``dev`` - local development only. ``Authorization: Bearer dev:<email>`` signs in as that
  email with no password. Refused at startup when ``PRICESCOPE_ENV=production``.

Roles live in our own ``users`` table, never in the token: admins are the emails listed in
``PRICESCOPE_ADMIN_EMAILS`` (granted on first sign-in) or users promoted by another admin.
"""

import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from http import HTTPStatus
from typing import Annotated, Any, ClassVar, Protocol

import jwt
import structlog
from fastapi import Depends, Request

from app.core.config import AuthMode, Settings, get_settings
from app.core.errors import AppError
from app.models.enums import UserRole
from app.storage.base import TableStore
from app.storage.errors import RowNotFound
from app.storage.factory import get_store

log = structlog.get_logger(__name__)

DEV_PREFIX = "dev:"
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$", re.I)
# Stable ids for dev users, so the same email is the same user across restarts.
_DEV_NAMESPACE = uuid.UUID("5d3b0f0e-9a51-4f0e-8c1e-7a3b1d2c4e5f")
LAST_SEEN_EVERY = timedelta(hours=1)  # limits writes (Google Sheets quota)


class Unauthenticated(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthenticated"


class Forbidden(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"


@dataclass(frozen=True)
class Identity:
    """Who the verified token says this is (before looking at our users table)."""

    user_id: uuid.UUID
    email: str
    name: str | None = None


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    role: UserRole
    display_name: str | None
    default_pincode: str | None
    preferences: dict[str, Any]

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Identity: ...


class SupabaseVerifier:
    """Verifies Supabase access tokens (asymmetric JWKS, or legacy HS256 secret)."""

    ALGORITHMS: ClassVar[list[str]] = ["ES256", "RS256", "EdDSA"]

    def __init__(self, settings: Settings, jwks_client: Any | None = None) -> None:
        base = settings.supabase_url.rstrip("/")
        self._issuer = f"{base}/auth/v1"
        self._audience = settings.supabase_jwt_audience
        self._secret = (
            settings.supabase_jwt_secret.get_secret_value()
            if settings.supabase_jwt_secret
            else None
        )
        self._jwks = jwks_client or jwt.PyJWKClient(
            f"{self._issuer}/.well-known/jwks.json", lifespan=600, timeout=5
        )

    def verify(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
            alg = header.get("alg")
            if alg == "HS256":
                if not self._secret:
                    raise Unauthenticated("This sign-in token type isn't accepted.")
                key: Any = self._secret
                algorithms = ["HS256"]
            else:
                key = self._jwks.get_signing_key_from_jwt(token).key
                algorithms = self.ALGORITHMS
            claims = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "iss", "aud"]},
                leeway=30,
            )
        except Unauthenticated:
            raise
        except jwt.ExpiredSignatureError:
            raise Unauthenticated("Your sign-in has expired. Please sign in again.") from None
        except (jwt.PyJWTError, ValueError) as exc:
            log.info("auth_token_rejected", reason=type(exc).__name__)
            raise Unauthenticated("Invalid sign-in token.") from None
        email = str(claims.get("email") or "").strip().lower()
        if not email:
            raise Unauthenticated("Your account has no email address.")
        meta = claims.get("user_metadata") or {}
        try:
            user_id = uuid.UUID(str(claims["sub"]))
        except ValueError:
            raise Unauthenticated("Invalid sign-in token.") from None
        return Identity(user_id, email, meta.get("full_name") or meta.get("name"))


class DevVerifier:
    """``dev:<email>`` tokens. Local development only (never enabled in production)."""

    def verify(self, token: str) -> Identity:
        if not token.startswith(DEV_PREFIX):
            raise Unauthenticated("Development sign-in expects a dev:<email> token.")
        email = token[len(DEV_PREFIX) :].strip().lower()
        if not _EMAIL.fullmatch(email):
            raise Unauthenticated("Enter a valid email address.")
        return Identity(uuid.uuid5(_DEV_NAMESPACE, email), email)


@lru_cache
def get_verifier() -> TokenVerifier:
    settings = get_settings()
    if settings.auth_mode is AuthMode.SUPABASE:
        return SupabaseVerifier(settings)
    return DevVerifier()


class UserDirectory:
    """Maps verified identities to our users table (creating users on first sign-in)."""

    def __init__(self, store: TableStore, admin_emails: list[str]) -> None:
        self._store = store
        self._admins = {e.strip().lower() for e in admin_emails}
        self._seen: dict[uuid.UUID, float] = {}

    def resolve(self, identity: Identity) -> CurrentUser:
        try:
            row = self._store.get("users", identity.user_id)
        except RowNotFound:
            row = self._store.insert(
                "users",
                {
                    "id": identity.user_id,
                    "email": identity.email,
                    "display_name": identity.name,
                    "role": UserRole.ADMIN if identity.email in self._admins else UserRole.USER,
                    "last_seen_at": datetime.now(UTC),
                },
            )
            log.info("user_created", user_id=str(identity.user_id), role=str(row["role"]))
        else:
            self._touch(row)
        return to_current_user(row)

    def _touch(self, row: dict[str, Any]) -> None:
        last = row.get("last_seen_at")
        now = time.monotonic()
        if self._seen.get(row["id"], -1e9) > now - 60:
            return
        self._seen[row["id"]] = now
        if last is None or datetime.now(UTC) - last > LAST_SEEN_EVERY:
            try:
                self._store.update("users", row["id"], {"last_seen_at": datetime.now(UTC)})
            except Exception:  # never fail a request over a "last seen" timestamp
                log.warning("last_seen_update_failed")


def to_current_user(row: dict[str, Any]) -> CurrentUser:
    return CurrentUser(
        id=row["id"],
        email=row["email"],
        role=UserRole(row["role"]),
        display_name=row.get("display_name"),
        default_pincode=row.get("default_pincode"),
        preferences=dict(row.get("preferences") or {}),
    )


@lru_cache
def get_user_directory() -> UserDirectory:
    return UserDirectory(get_store(), get_settings().admin_emails)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def optional_user(
    request: Request,
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
    directory: Annotated[UserDirectory, Depends(get_user_directory)],
) -> CurrentUser | None:
    """The signed-in user, or None for anonymous requests. A bad token is an error."""
    token = _bearer(request)
    if token is None:
        return None
    user = directory.resolve(verifier.verify(token))
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


def require_user(user: Annotated[CurrentUser | None, Depends(optional_user)]) -> CurrentUser:
    if user is None:
        raise Unauthenticated("Please sign in.")
    return user


def require_admin(user: Annotated[CurrentUser, Depends(require_user)]) -> CurrentUser:
    if not user.is_admin:
        raise Forbidden("Admins only.")
    return user


OptionalUser = Annotated[CurrentUser | None, Depends(optional_user)]
User = Annotated[CurrentUser, Depends(require_user)]
Admin = Annotated[CurrentUser, Depends(require_admin)]
