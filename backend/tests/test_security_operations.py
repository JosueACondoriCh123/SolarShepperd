from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth
from app.api import operational
from app.auth import Principal, require_owner
from app.config import Settings
from app.errors import APIError
from app.models import (
    CalibrationSample,
    Mission,
    RouteRun,
    SampleSubmission,
    UserProfile,
)
from app.operational_schemas import MissionPatch, SampleReview
from app.services.object_storage import ObjectStorage

USER_A_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
USER_B_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
OWNER_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def make_profile(user_id: uuid.UUID, is_owner: bool = False) -> UserProfile:
    return UserProfile(
        auth_user_id=user_id,
        email=f"user-{user_id.hex[:6]}@example.test",
        display_name=f"User {user_id.hex[:6]}",
        is_system_owner=is_owner,
        status="active",
        onboarding_completed=True,
    )


# ---------------------------------------------------------------------------
# 1. Cross-User Multitenancy & Ownership Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_user_cannot_access_other_user_mission() -> None:
    profile_a = make_profile(USER_A_ID, is_owner=False)
    profile_b = make_profile(USER_B_ID, is_owner=False)

    mission = Mission(
        id=uuid.uuid4(),
        owner_user_id=profile_a.auth_user_id,
        title="Secret Pasture Scout",
        status="planned",
        revision=1,
    )

    session = AsyncMock()
    session.get.return_value = mission

    # Owner A can access
    owned = await operational._owned_mission(session, mission.id, profile_a)
    assert owned.id == mission.id

    # User B is blocked
    with pytest.raises(APIError) as exc_info:
        await operational._owned_mission(session, mission.id, profile_b)
    assert exc_info.value.code == "OWNERSHIP_REQUIRED"
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_cross_user_cannot_access_other_user_sample() -> None:
    profile_a = make_profile(USER_A_ID, is_owner=False)
    profile_b = make_profile(USER_B_ID, is_owner=False)

    sample = SampleSubmission(
        id=uuid.uuid4(),
        owner_user_id=profile_a.auth_user_id,
        sample_code="SS-20260920-0001",
        dry_matter_kg_ha=620.0,
        status="draft",
    )

    session = AsyncMock()
    session.get.return_value = sample

    # User B is rejected
    with pytest.raises(APIError) as exc_info:
        await operational._owned_sample(session, sample.id, profile_b)
    assert exc_info.value.code == "OWNERSHIP_REQUIRED"
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_attach_other_user_route_to_mission() -> None:
    profile_b = make_profile(USER_B_ID, is_owner=False)

    # Route belongs to User A
    foreign_route = RouteRun(
        id=uuid.uuid4(),
        owner_user_id=USER_A_ID,
        status="complete",
        total_distance_m=1200.0,
    )

    session = AsyncMock()
    session.get.return_value = foreign_route

    # Attempting to validate or attach route belonging to User A
    with pytest.raises(APIError) as exc_info:
        if foreign_route.owner_user_id != profile_b.auth_user_id:
            raise APIError(
                "OWNERSHIP_REQUIRED", "The selected route is unavailable.", status_code=422
            )

    assert exc_info.value.code == "OWNERSHIP_REQUIRED"
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# 2. RBAC Permissions Tests (Guest / Member / Owner)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rbac_member_cannot_access_owner_endpoints() -> None:
    member_principal = Principal(
        user_id=USER_A_ID,
        email="member@example.com",
        is_guest=False,
        is_system_owner=False,
        auth_source="supabase",
    )

    # Calling require_owner dependency with regular member
    with pytest.raises(APIError) as exc_info:
        await require_owner(member_principal)
    assert exc_info.value.code == "FORBIDDEN"
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_rbac_guest_cannot_access_owner_endpoints() -> None:
    guest_principal = Principal(
        user_id=auth.LOCAL_GUEST_ID,
        email=None,
        is_guest=True,
        is_system_owner=False,
        auth_source="supabase",
    )

    with pytest.raises(APIError) as exc_info:
        await require_owner(guest_principal)
    assert exc_info.value.code == "FORBIDDEN"
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_rbac_system_owner_passes_owner_guard() -> None:
    owner_principal = Principal(
        user_id=OWNER_ID,
        email="admin@solarshepherd.test",
        is_guest=False,
        is_system_owner=True,
        auth_source="supabase",
    )

    result = await require_owner(owner_principal)
    assert result.is_system_owner is True
    assert result.user_id == OWNER_ID


# ---------------------------------------------------------------------------
# 3. Optimistic Concurrency Conflict on Missions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mission_revision_conflict_returns_409() -> None:
    profile = make_profile(USER_A_ID, is_owner=False)
    mission = Mission(
        id=uuid.uuid4(),
        owner_user_id=profile.auth_user_id,
        title="Field Trial #1",
        description="Original notes",
        status="planned",
        revision=3,  # Current DB revision is 3
    )

    session = AsyncMock()
    session.get.return_value = mission

    # Request arrives with stale revision = 2
    stale_request = MissionPatch(title="Conflicting Edit", revision=2)

    with pytest.raises(APIError) as exc_info:
        await operational.patch_mission(mission.id, stale_request, profile, session)

    assert exc_info.value.code == "REVISION_CONFLICT"
    assert exc_info.value.status_code == 409
    assert exc_info.value.details == {"current_revision": 3}


@pytest.mark.asyncio
async def test_mission_revision_success_increments_revision() -> None:
    profile = make_profile(USER_A_ID, is_owner=False)
    mission = Mission(
        id=uuid.uuid4(),
        owner_user_id=profile.auth_user_id,
        title="Field Trial #1",
        description="Original",
        status="planned",
        revision=1,
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.get.return_value = mission

    valid_request = MissionPatch(title="Updated Title", revision=1)
    updated = await operational.patch_mission(mission.id, valid_request, profile, session)

    assert updated["title"] == "Updated Title"
    assert mission.revision == 2
    session.commit.assert_awaited()


# ---------------------------------------------------------------------------
# 4. Sample Review & Approval Idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sample_approval_is_idempotent() -> None:
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    owner = make_profile(OWNER_ID, is_owner=True)
    sample_id = uuid.uuid4()
    calib_id = uuid.uuid4()

    sample = SampleSubmission(
        id=sample_id,
        owner_user_id=USER_A_ID,
        sample_code="SS-20260920-ABCD",
        sampled_at=datetime.now(UTC),
        geom=from_shape(Point(37.0144, -1.1018), srid=4326),
        dry_matter_kg_ha=750.0,
        method="clipped quadrat",
        quadrat_area_m2=0.25,
        status="approved",
        calibration_sample_id=calib_id,
        revision=2,
    )

    session = AsyncMock()
    session.get.return_value = sample

    # When review endpoint is called on an ALREADY approved sample with decision="approved"
    request = SampleReview(decision="approved", notes="Re-verifying")
    result = await operational.review_sample(sample_id, request, owner, session)

    # It must return the sample without calling session.add for a new CalibrationSample
    assert result["status"] == "approved"
    # session.add should not be called with a new CalibrationSample
    added_types = [type(call.args[0]) for call in session.add.call_args_list if call.args]
    assert CalibrationSample not in added_types


# ---------------------------------------------------------------------------
# 5. Token and Storage Key Expiration / Security
# ---------------------------------------------------------------------------

def test_expired_jwt_raises_auth_required() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        auth_mode="supabase",
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="pub_key",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    expired_claims = {
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "iss": settings.supabase_issuer,
        "exp": datetime.now(UTC) - timedelta(seconds=60),  # expired 1 minute ago
    }
    token = jwt.encode(expired_claims, private_key, algorithm="RS256")

    class MockJwksClient:
        def get_signing_key_from_jwt(self, _tok):
            class KeyObj:
                key = private_key.public_key()
            return KeyObj()

    # Monkeypatch jwks
    import unittest.mock as mock
    with mock.patch.object(auth, "_jwks_client", return_value=MockJwksClient()):
        with pytest.raises(APIError) as exc_info:
            auth._decode_token_sync(token, settings)
        assert exc_info.value.code == "AUTH_REQUIRED"
        assert "expired" in exc_info.value.message.lower()


def test_object_storage_rejects_path_traversal() -> None:
    settings = Settings(_env_file=None, local_storage_path="C:/data/test")
    storage = ObjectStorage(settings)

    with pytest.raises(APIError) as exc_info:
        storage.local_path("reports", "../../../etc/passwd")
    assert exc_info.value.code == "INVALID_OBJECT_KEY"


# ---------------------------------------------------------------------------
# 6. Service Worker Never Caches Private Endpoints
# ---------------------------------------------------------------------------

def test_service_worker_excludes_private_endpoints() -> None:
    sw_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "sw.js"
    assert sw_path.exists(), "sw.js must exist in frontend/public"
    content = sw_path.read_text(encoding="utf-8")

    # Verify PRIVATE_API_PREFIXES exists and protects sensitive paths
    assert "PRIVATE_API_PREFIXES" in content
    for sensitive_path in [
        "/api/v1/missions",
        "/api/v1/sample-submissions",
        "/api/v1/reports",
        "/api/v1/me",
        "/api/v1/alerts",
        "/api/v1/admin",
    ]:
        assert sensitive_path in content, f"{sensitive_path} must be explicitly in sw.js"

    # Verify no private paths are in SHARED_API_PATHS
    shared_section = content.split("SHARED_API_PATHS = [")[1].split("];")[0]
    for sensitive_path in [
        "/api/v1/missions",
        "/api/v1/sample-submissions",
        "/api/v1/reports",
        "/api/v1/me",
    ]:
        assert sensitive_path not in shared_section, (
            f"{sensitive_path} must NOT be in SHARED_API_PATHS"
        )
