from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth
from app.auth import LOCAL_GUEST_ID, LOCAL_USER_ID
from app.config import Settings
from app.errors import APIError


def _supabase_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        auth_mode="supabase",
        supabase_url="https://project.supabase.co",
        supabase_publishable_key="sb_publishable_test",
    )


@pytest.mark.asyncio
async def test_development_access_distinguishes_guest_and_member() -> None:
    settings = Settings(_env_file=None, environment="development", auth_mode="development")

    guest = await auth.require_api_access(
        authorization="Bearer dev-guest", admin_token=None, settings=settings
    )
    member = await auth.require_api_access(
        authorization=None, admin_token=None, settings=settings
    )

    assert guest.user_id == LOCAL_GUEST_ID
    assert guest.is_guest is True
    assert guest.is_system_owner is False
    assert member.user_id == LOCAL_USER_ID
    assert member.is_guest is False
    assert member.is_system_owner is True


@pytest.mark.asyncio
async def test_supabase_mode_requires_a_bearer_token() -> None:
    with pytest.raises(APIError) as exc_info:
        await auth.require_api_access(
            authorization=None,
            admin_token=None,
            settings=_supabase_settings(),
        )

    assert exc_info.value.code == "AUTH_REQUIRED"
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_signed_anonymous_claim_is_never_treated_as_member(monkeypatch) -> None:
    subject = uuid.uuid4()
    monkeypatch.setattr(
        auth,
        "_decode_token_sync",
        lambda _token, _settings: {
            "sub": str(subject),
            "email": "spoofed@example.com",
            "email_confirmed_at": datetime.now(UTC).isoformat(),
            "is_anonymous": True,
        },
    )

    principal = await auth._principal_from_token("signed-token", _supabase_settings())

    assert principal.user_id == subject
    assert principal.is_guest is True
    assert principal.email is None
    assert principal.is_system_owner is False


@pytest.mark.asyncio
async def test_unverified_email_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "_decode_token_sync",
        lambda _token, _settings: {
            "sub": str(uuid.uuid4()),
            "email": "member@example.com",
            "is_anonymous": False,
            "user_metadata": {},
        },
    )

    with pytest.raises(APIError) as exc_info:
        await auth._principal_from_token("signed-token", _supabase_settings())

    assert exc_info.value.code == "EMAIL_NOT_VERIFIED"
    assert exc_info.value.status_code == 403


class _SigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class _JwksClient:
    def __init__(self, key: object) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, _token: str) -> _SigningKey:
        return _SigningKey(self.key)


@pytest.mark.parametrize(
    ("claim_overrides", "expected_message"),
    [
        ({"iss": "https://attacker.example/auth/v1"}, "invalid"),
        ({"exp": datetime.now(UTC) - timedelta(minutes=1)}, "expired"),
    ],
)
def test_jwt_rejects_wrong_issuer_and_expiry(
    monkeypatch, claim_overrides: dict[str, object], expected_message: str
) -> None:
    settings = _supabase_settings()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "iss": settings.supabase_issuer,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    claims.update(claim_overrides)
    token = jwt.encode(claims, private_key, algorithm="RS256")
    monkeypatch.setattr(auth, "_jwks_client", lambda _url: _JwksClient(private_key.public_key()))

    with pytest.raises(APIError) as exc_info:
        auth._decode_token_sync(token, settings)

    assert exc_info.value.code == "AUTH_REQUIRED"
    assert expected_message in exc_info.value.message.lower()


def test_malformed_jwt_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(auth, "_jwks_client", lambda _url: _JwksClient(object()))

    with pytest.raises(APIError) as exc_info:
        auth._decode_token_sync("not-a-jwt", _supabase_settings())

    assert exc_info.value.code == "AUTH_REQUIRED"
