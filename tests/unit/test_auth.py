"""Token verification: Supabase-style JWTs (JWKS + legacy HS256) and dev sign-in."""

import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.auth import DevVerifier, SupabaseVerifier, Unauthenticated
from app.core.config import AuthMode, Settings

SUPABASE = "https://demo-project.supabase.co"
ISSUER = f"{SUPABASE}/auth/v1"
USER_ID = "2b6b8c1e-5d0a-4a43-9d0e-0c6f6b1a7e11"


class FakeJWKS:
    """Stands in for PyJWKClient: returns our test public key for any token."""

    def __init__(self, public_key: Any) -> None:
        self._key = public_key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        class K:
            key = self._key

        return K()


@pytest.fixture(scope="module")
def keypair() -> tuple[Any, Any]:
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key()


def claims(**over: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "sub": USER_ID,
        "email": "Asha@Example.in",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
        "user_metadata": {"full_name": "Asha K"},
    }
    base.update(over)
    return base


def verifier(public_key: Any, secret: str | None = None) -> SupabaseVerifier:
    settings = Settings(
        auth_mode=AuthMode.SUPABASE,
        supabase_url=SUPABASE,
        supabase_jwt_secret=secret,  # type: ignore[arg-type]
    )
    return SupabaseVerifier(settings, jwks_client=FakeJWKS(public_key))


def test_valid_es256_token(keypair: tuple[Any, Any]) -> None:
    private, public = keypair
    token = jwt.encode(claims(), private, algorithm="ES256", headers={"kid": "k1"})
    ident = verifier(public).verify(token)
    assert ident.user_id == uuid.UUID(USER_ID)
    assert ident.email == "asha@example.in"
    assert ident.name == "Asha K"


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"aud": "anon"}, "Invalid"),
        ({"iss": "https://evil.example/auth/v1"}, "Invalid"),
        ({"exp": int(time.time()) - 600}, "expired"),
        ({"email": ""}, "no email"),
        ({"sub": "not-a-uuid"}, "Invalid"),
    ],
)
def test_rejects_bad_claims(keypair: tuple[Any, Any], over: dict[str, Any], message: str) -> None:
    private, public = keypair
    token = jwt.encode(claims(**over), private, algorithm="ES256")
    with pytest.raises(Unauthenticated, match=message):
        verifier(public).verify(token)


def test_rejects_token_signed_by_another_key(keypair: tuple[Any, Any]) -> None:
    _, public = keypair
    other = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(claims(), other, algorithm="ES256")
    with pytest.raises(Unauthenticated):
        verifier(public).verify(token)


def test_rejects_unsigned_and_garbage_tokens(keypair: tuple[Any, Any]) -> None:
    _, public = keypair
    unsigned = jwt.encode(claims(), key=None, algorithm="none")  # type: ignore[arg-type]
    for token in (unsigned, "not.a.jwt", "dev:asha@example.in"):
        with pytest.raises(Unauthenticated):
            verifier(public).verify(token)


def test_hs256_only_with_configured_secret(keypair: tuple[Any, Any]) -> None:
    _, public = keypair
    secret = "a-very-long-test-secret-value-32-bytes-min"  # noqa: S105 - test-only key
    token = jwt.encode(claims(), secret, algorithm="HS256")
    with pytest.raises(Unauthenticated):
        verifier(public).verify(token)  # no secret configured: refused
    assert verifier(public, secret).verify(token).email == "asha@example.in"
    forged = jwt.encode(claims(), "some-other-secret-value-32-bytes-long", algorithm="HS256")
    with pytest.raises(Unauthenticated):
        verifier(public, secret).verify(forged)


def test_dev_tokens() -> None:
    v = DevVerifier()
    a = v.verify("dev:Asha@Example.in")
    assert a.email == "asha@example.in"
    assert a.user_id == v.verify("dev:asha@example.in").user_id  # stable per email
    for bad in ("asha@example.in", "dev:", "dev:not-an-email", "Bearer x"):
        with pytest.raises(Unauthenticated):
            v.verify(bad)


def test_admin_emails_parsed_from_env_string() -> None:
    s = Settings(admin_emails="ops@example.in, Owner@Example.in")  # type: ignore[arg-type]
    assert s.admin_emails == ["ops@example.in", "Owner@Example.in"]
