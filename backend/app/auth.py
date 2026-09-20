from __future__ import annotations

import asyncio
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header
from jwt import PyJWKClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import APIError
from app.models import UserProfile

LOCAL_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
SERVICE_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
LOCAL_GUEST_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    email: str | None
    is_guest: bool
    is_system_owner: bool
    auth_source: str


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_jwk_set=True, lifespan=600)


def _decode_token_sync(token: str, settings: Settings) -> dict[str, Any]:
    try:
        signing_key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "EdDSA"],
            audience="authenticated",
            issuer=settings.supabase_issuer,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise APIError("AUTH_REQUIRED", "Your session has expired.", status_code=401) from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise APIError("AUTH_REQUIRED", "The access token is invalid.", status_code=401) from exc


async def _principal_from_token(token: str, settings: Settings) -> Principal:
    claims = await asyncio.to_thread(_decode_token_sync, token, settings)
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError) as exc:
        raise APIError(
            "AUTH_REQUIRED", "The access token has no valid subject.", status_code=401
        ) from exc
    is_guest = bool(claims.get("is_anonymous", False))
    email_value = claims.get("email")
    email = str(email_value).strip().lower() if email_value and not is_guest else None
    user_metadata = claims.get("user_metadata") or {}
    if email and not (claims.get("email_confirmed_at") or user_metadata.get("email_verified")):
        raise APIError(
            "EMAIL_NOT_VERIFIED",
            "Verify your email before opening the field console.",
            status_code=403,
        )
    return Principal(
        user_id=user_id,
        email=email,
        is_guest=is_guest,
        is_system_owner=bool(email and email in settings.system_owner_emails),
        auth_source="supabase",
    )


async def require_api_access(
    authorization: Annotated[str | None, Header()] = None,
    admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    settings: Settings = Depends(get_settings),
) -> Principal:
    if (
        admin_token
        and settings.api_admin_token
        and secrets.compare_digest(admin_token, settings.api_admin_token)
    ):
        return Principal(SERVICE_USER_ID, None, False, True, "service_token")
    if settings.auth_mode == "development" and settings.environment != "production":
        if authorization == "Bearer dev-guest":
            return Principal(LOCAL_GUEST_ID, None, True, False, "development")
        return Principal(
            LOCAL_USER_ID,
            "local-owner@solarshepherd.test",
            False,
            True,
            "development",
        )
    if settings.auth_mode != "supabase" or not settings.supabase_configured:
        raise APIError("AUTH_REQUIRED", "Authentication is not configured.", status_code=503)
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise APIError("AUTH_REQUIRED", "A bearer access token is required.", status_code=401)
    return await _principal_from_token(token, settings)


async def ensure_profile(
    principal: Annotated[Principal, Depends(require_api_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Settings = Depends(get_settings),
) -> UserProfile:
    return await ensure_profile_record(principal, session, settings)


async def ensure_profile_record(
    principal: Principal,
    session: AsyncSession,
    settings: Settings,
) -> UserProfile:
    if principal.is_guest:
        raise APIError("FORBIDDEN", "Guest sessions are read-only.", status_code=403)
    profile = await session.get(UserProfile, principal.user_id)
    owner = principal.is_system_owner or bool(
        principal.email and principal.email in settings.system_owner_emails
    )
    if profile is None:
        profile = UserProfile(
            auth_user_id=principal.user_id,
            email=principal.email,
            display_name=(principal.email or "SolarShepherd member").split("@")[0],
            timezone=settings.pilot_timezone,
            status="active",
            onboarding_completed=principal.auth_source == "development",
            is_system_owner=owner,
            notification_preferences={"email": True},
            last_seen_at=datetime.now(UTC),
        )
        session.add(profile)
    else:
        if profile.status != "active":
            raise APIError("FORBIDDEN", "This account is not active.", status_code=403)
        profile.last_seen_at = datetime.now(UTC)
        if principal.email:
            profile.email = principal.email
        if owner and not profile.is_system_owner:
            profile.is_system_owner = True
    await session.commit()
    await session.refresh(profile)
    return profile


async def require_owner(
    profile: Annotated[UserProfile, Depends(ensure_profile)],
) -> UserProfile:
    if not profile.is_system_owner:
        raise APIError("FORBIDDEN", "System-owner access is required.", status_code=403)
    return profile


PrincipalDependency = Annotated[Principal, Depends(require_api_access)]
ProfileDependency = Annotated[UserProfile, Depends(ensure_profile)]
OwnerDependency = Annotated[UserProfile, Depends(require_owner)]
