from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from pydantic import ValidationError

from app.api import operational
from app.errors import APIError
from app.models import (
    Alert,
    AlertRule,
    Mission,
    ReportRun,
    ResponseCase,
    ResponseUpdate,
    RouteRun,
    UserProfile,
)
from app.operational_schemas import (
    AlertRuleCreate,
    ResponseCaseAcknowledge,
    ResponseCaseClose,
    ResponseCaseComplete,
    ResponseCaseDismiss,
    ResponseCaseRoute,
    ResponseCaseStart,
    ResponseUpdateCreate,
)
from app.services.alerts import _ensure_response_case
from app.services.reporting import _render_pdf

USER_A_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
USER_B_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


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
# 1. Schema Validation Tests
# ---------------------------------------------------------------------------

def test_alert_rule_defaults_and_validation() -> None:
    rule = AlertRuleCreate(
        name="High Heat Alert",
        kind="forecast_threshold",
        metric="temperature_c",
        comparator=">=",
        threshold=35.0,
    )
    assert rule.severity == "warning"
    assert rule.response_mode == "case_and_mission"

    with pytest.raises(ValidationError):
        AlertRuleCreate(
            name="Invalid Severity",
            kind="forecast_threshold",
            metric="temperature_c",
            comparator=">=",
            threshold=35.0,
            severity="extreme",  # type: ignore
        )

    with pytest.raises(ValidationError):
        AlertRuleCreate(
            name="Invalid Mode",
            kind="forecast_threshold",
            metric="temperature_c",
            comparator=">=",
            threshold=35.0,
            response_mode="auto_pilot",  # type: ignore
        )


def test_response_case_schemas() -> None:
    ack = ResponseCaseAcknowledge(revision=1)
    assert ack.revision == 1

    route_id = uuid.uuid4()
    rc_route = ResponseCaseRoute(route_id=route_id, revision=2)
    assert rc_route.route_id == route_id
    assert rc_route.revision == 2

    start = ResponseCaseStart(revision=3)
    assert start.revision == 3

    comp = ResponseCaseComplete(revision=4)
    assert comp.revision == 4

    close = ResponseCaseClose(resolution_notes="Resolved safely.", revision=5)
    assert close.resolution_notes == "Resolved safely."

    with pytest.raises(ValidationError):
        ResponseCaseClose(resolution_notes="", revision=5)

    dismiss = ResponseCaseDismiss(reason="False alarm from cloud cover.", revision=1)
    assert dismiss.reason == "False alarm from cloud cover."

    with pytest.raises(ValidationError):
        ResponseCaseDismiss(reason="", revision=1)

    update = ResponseUpdateCreate(
        notes="Inspected sheep near row 4. Vegetation healthy.",
        latitude=-1.09,
        longitude=37.01,
    )
    assert update.latitude == -1.09
    assert update.longitude == 37.01


# ---------------------------------------------------------------------------
# 2. Alert-to-Action Automation (_ensure_response_case)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_response_case_creates_case_and_planned_mission() -> None:
    rule = AlertRule(
        id=uuid.uuid4(),
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        name="Telemetry Stale JKUAT",
        kind="telemetry_stale",
        severity="critical",
        response_mode="case_and_mission",
    )
    alert = Alert(
        id=uuid.uuid4(),
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        rule_id=rule.id,
        kind="telemetry_stale",
        title="Telemetry sensor lost",
        message="No data for 2 hours",
    )

    added_objects = []

    session = AsyncMock()
    session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = exec_mock

    case_id = await _ensure_response_case(
        session,
        rule,
        alert_title=alert.title,
        alert_message=alert.message,
        payload={"sensor_id": "SN-001"},
        now=datetime.now(UTC),
    )

    assert case_id is not None
    assert len(added_objects) == 3  # Mission, ResponseCase, AuditEvent

    mission = next(obj for obj in added_objects if isinstance(obj, Mission))
    case = next(obj for obj in added_objects if isinstance(obj, ResponseCase))

    assert mission.status == "planned"
    assert mission.route_run_id is None
    assert "Response Center" in mission.notes
    assert case.status == "triage"
    assert case.severity == "critical"
    assert case.mission_id == mission.id
    assert case.rule_id == rule.id


@pytest.mark.asyncio
async def test_ensure_response_case_groups_into_active_case() -> None:
    rule = AlertRule(
        id=uuid.uuid4(),
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        name="High Temp",
        kind="forecast_threshold",
        severity="critical",
        response_mode="case_and_mission",
    )
    existing_case = ResponseCase(
        id=uuid.uuid4(),
        pilot_slug="jkuat",
        owner_user_id=USER_A_ID,
        rule_id=rule.id,
        mission_id=uuid.uuid4(),
        status="triage",
        severity="critical",
        revision=1,
    )

    session = AsyncMock()
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = existing_case
    session.execute.return_value = exec_mock

    case_id = await _ensure_response_case(
        session,
        rule,
        alert_title="High Temp 38C",
        alert_message="Forecast exceeds threshold",
        payload={"temperature_c": 38.0},
        now=datetime.now(UTC),
    )

    assert case_id == existing_case.id
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Response Mission Guardrails & Lock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_mission_blocked_for_response_missions() -> None:
    profile = make_profile(USER_A_ID)
    mission_id = uuid.uuid4()
    mission = Mission(
        id=mission_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        title="Response Mission",
        status="planned",
        revision=1,
    )
    resp_case = ResponseCase(
        id=uuid.uuid4(),
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        mission_id=mission_id,
        status="triage",
        revision=1,
    )

    session = AsyncMock()
    session.get.return_value = mission
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = resp_case
    session.execute.return_value = exec_mock

    # Attempting to change status to active via general patch_mission
    with pytest.raises(APIError) as exc_info:
        await operational.patch_mission(
            mission_id=mission_id,
            request=operational.MissionPatch(status="active", revision=1),
            profile=profile,
            session=session,
            pilot="jkuat",
        )
    assert exc_info.value.code == "RESPONSE_MISSION_RESTRICTED"
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 4. Response Center Lifecycle Transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_case_acknowledge_and_revision_check() -> None:
    profile = make_profile(USER_A_ID)
    case_id = uuid.uuid4()
    mission_id = uuid.uuid4()

    mission = Mission(
        id=mission_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        title="Response Mission",
        status="planned",
        route_run_id=None,
        revision=1,
    )
    case = ResponseCase(
        id=case_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        mission_id=mission_id,
        status="triage",
        revision=1,
    )

    def mock_get(model, ident):
        if model == ResponseCase:
            return case
        if model == Mission:
            return mission
        return None

    session = AsyncMock()
    session.get.side_effect = mock_get
    exec_mock = MagicMock()
    exec_mock.scalars.return_value = []
    session.execute.return_value = exec_mock

    # Revision conflict check
    with pytest.raises(APIError) as exc_info:
        await operational.acknowledge_response_case(
            case_id=case_id,
            request=ResponseCaseAcknowledge(revision=0),
            profile=profile,
            session=session,
            pilot="jkuat",
        )
    assert exc_info.value.code == "REVISION_CONFLICT"

    # Successful ack
    res = await operational.acknowledge_response_case(
        case_id=case_id,
        request=ResponseCaseAcknowledge(revision=1),
        profile=profile,
        session=session,
        pilot="jkuat",
    )
    assert res["id"] == str(case_id)
    assert case.acknowledged_at is not None
    assert case.revision == 2


@pytest.mark.asyncio
async def test_response_case_route_assignment_and_start_guard() -> None:
    profile = make_profile(USER_A_ID)
    case_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    route_id = uuid.uuid4()

    mission = Mission(
        id=mission_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        title="Response Mission",
        status="planned",
        route_run_id=None,
        revision=1,
    )
    case = ResponseCase(
        id=case_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        mission_id=mission_id,
        status="triage",
        acknowledged_at=None,
        revision=1,
    )
    route = RouteRun(
        id=route_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        status="success",
    )

    def mock_get(model, ident):
        if model == ResponseCase:
            return case
        if model == Mission:
            return mission
        if model == RouteRun:
            return route
        return None

    session = AsyncMock()
    session.get.side_effect = mock_get

    # Cannot start before route and ack (status still triage)
    with pytest.raises(APIError) as exc_info:
        await operational.start_response_case(
            case_id=case_id,
            request=ResponseCaseStart(revision=1),
            profile=profile,
            session=session,
            pilot="jkuat",
        )
    assert exc_info.value.code == "CANNOT_START_WITHOUT_ROUTE_AND_ACK"

    # Now acknowledge
    case.acknowledged_at = datetime.now(UTC)

    # Attach route
    await operational.attach_response_case_route(
        case_id=case_id,
        request=ResponseCaseRoute(route_id=route_id, revision=1),
        profile=profile,
        session=session,
        pilot="jkuat",
    )

    assert case.status == "ready"
    assert mission.route_run_id == route_id
    assert case.revision == 2

    # Now start response case
    await operational.start_response_case(
        case_id=case_id,
        request=ResponseCaseStart(revision=2),
        profile=profile,
        session=session,
        pilot="jkuat",
    )
    assert case.status == "responding"
    assert mission.status == "active"
    assert case.revision == 3


@pytest.mark.asyncio
async def test_response_case_complete_and_close_with_report_requirement() -> None:
    profile = make_profile(USER_A_ID)
    case_id = uuid.uuid4()
    mission_id = uuid.uuid4()

    mission = Mission(
        id=mission_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        title="Response Mission",
        status="active",
        revision=2,
    )
    case = ResponseCase(
        id=case_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        mission_id=mission_id,
        status="responding",
        revision=3,
    )

    def mock_get(model, ident):
        if model == ResponseCase:
            return case
        if model == Mission:
            return mission
        return None

    session = AsyncMock()
    session.get.side_effect = mock_get
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = exec_mock

    # Complete mission
    settings = MagicMock()
    with patch("app.api.operational.dispatch_report"):
        await operational.complete_response_case(
            case_id=case_id,
            request=ResponseCaseComplete(revision=3),
            profile=profile,
            session=session,
            settings=settings,
            pilot="jkuat",
        )
    assert case.status == "review"
    assert mission.status == "completed"
    assert case.revision == 4

    # Try to close before report is ready
    exec_mock2 = MagicMock()
    exec_mock2.scalar_one_or_none.return_value = None
    session.execute.return_value = exec_mock2

    with pytest.raises(APIError) as exc_info:
        await operational.close_response_case(
            case_id=case_id,
            request=ResponseCaseClose(
                resolution_notes="Sheep safe, shaded under solar arrays.",
                revision=4,
            ),
            profile=profile,
            session=session,
            pilot="jkuat",
        )
    assert exc_info.value.code == "REPORT_NOT_READY"

    # When report is ready, close succeeds
    ready_report = ReportRun(
        id=uuid.uuid4(),
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        mission_id=mission_id,
        status="ready",
    )
    exec_mock3 = MagicMock()
    exec_mock3.scalar_one_or_none.return_value = ready_report
    session.execute.return_value = exec_mock3

    res = await operational.close_response_case(
        case_id=case_id,
        request=ResponseCaseClose(
            resolution_notes="Sheep moved to zone 2 successfully.",
            revision=4,
        ),
        profile=profile,
        session=session,
        pilot="jkuat",
    )
    assert res["status"] == "closed"
    assert case.status == "closed"
    assert case.closed_at is not None
    assert case.resolution_notes == "Sheep moved to zone 2 successfully."


@pytest.mark.asyncio
async def test_response_case_dismissal_cancels_open_mission() -> None:
    profile = make_profile(USER_A_ID)
    case_id = uuid.uuid4()
    mission_id = uuid.uuid4()

    mission = Mission(
        id=mission_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        title="Response Mission",
        status="planned",
        revision=1,
    )
    case = ResponseCase(
        id=case_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        mission_id=mission_id,
        status="triage",
        revision=1,
    )

    def mock_get(model, ident):
        if model == ResponseCase:
            return case
        if model == Mission:
            return mission
        return None

    session = AsyncMock()
    session.get.side_effect = mock_get

    await operational.dismiss_response_case(
        case_id=case_id,
        request=ResponseCaseDismiss(reason="Sensor error - false positive reading.", revision=1),
        profile=profile,
        session=session,
        pilot="jkuat",
    )

    assert case.status == "dismissed"
    assert case.dismissal_reason == "Sensor error - false positive reading."
    assert mission.status == "cancelled"


# ---------------------------------------------------------------------------
# 5. GPS Boundary Validation & Photo Metadata Stripping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_update_gps_bounds_validation() -> None:
    profile = make_profile(USER_A_ID)
    case_id = uuid.uuid4()
    case = ResponseCase(
        id=case_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        mission_id=uuid.uuid4(),
        status="responding",
        revision=1,
    )

    session = AsyncMock()
    session.get.return_value = case

    # Coordinate outside JKUAT pilot boundary (e.g. London coordinates 51.5, -0.12)
    with pytest.raises(APIError) as exc_info:
        await operational.create_response_update(
            case_id=case_id,
            request=ResponseUpdateCreate(
                notes="Far away reading",
                latitude=51.5074,
                longitude=-0.1278,
            ),
            profile=profile,
            session=session,
            pilot="jkuat",
        )
    assert exc_info.value.code == "OUTSIDE_PILOT"
    assert exc_info.value.status_code == 422

    # Coordinate inside JKUAT boundary (-1.096, 37.014)
    res = await operational.create_response_update(
        case_id=case_id,
        request=ResponseUpdateCreate(
            notes="Valid on-site reading",
            latitude=-1.096,
            longitude=37.014,
        ),
        profile=profile,
        session=session,
        pilot="jkuat",
    )
    assert "id" in res


@pytest.mark.asyncio
async def test_attachment_upload_strips_exif_and_enforces_limit() -> None:
    profile = make_profile(USER_A_ID)
    case_id = uuid.uuid4()
    update_id = uuid.uuid4()

    case = ResponseCase(
        id=case_id,
        owner_user_id=USER_A_ID,
        pilot_slug="jkuat",
        mission_id=uuid.uuid4(),
        status="responding",
        revision=1,
    )
    update = ResponseUpdate(
        id=update_id,
        response_case_id=case_id,
        author_user_id=USER_A_ID,
        notes="Field survey update",
    )

    # Create dummy in-memory JPEG with EXIF tags
    img = Image.new("RGB", (100, 100), color="blue")
    img_bytes = BytesIO()
    img.save(img_bytes, format="JPEG")
    img_raw = img_bytes.getvalue()

    upload_file = MagicMock()
    upload_file.filename = "field_photo.jpg"
    upload_file.content_type = "image/jpeg"
    upload_file.read = AsyncMock(return_value=img_raw)

    settings = MagicMock()
    settings.response_evidence_bucket = "response-evidence"

    def mock_get(model, ident):
        if model == ResponseUpdate:
            return update
        if model == ResponseCase:
            return case
        return None

    session = AsyncMock()
    session.get.side_effect = mock_get
    exec_mock = MagicMock()
    exec_mock.scalar_one.return_value = 0
    session.execute.return_value = exec_mock

    with patch("app.api.operational.ObjectStorage") as mock_storage_cls:
        mock_storage_inst = AsyncMock()
        mock_storage_cls.return_value = mock_storage_inst
        res = await operational.upload_response_attachment(
            update_id=update_id,
            file=upload_file,
            profile=profile,
            session=session,
            settings=settings,
        )

        assert res["content_type"] == "image/webp"
        call_args = mock_storage_inst.put.call_args
        stored_bytes = call_args[0][2]
        uploaded_image = Image.open(BytesIO(stored_bytes))
        assert uploaded_image.format == "WEBP"
        assert "exif" not in uploaded_image.info

    # Max 3 photos test
    exec_mock_limit = MagicMock()
    exec_mock_limit.scalar_one.return_value = 3
    session.execute.return_value = exec_mock_limit

    with pytest.raises(APIError) as exc_info:
        await operational.upload_response_attachment(
            update_id=update_id,
            file=upload_file,
            profile=profile,
            session=session,
            settings=settings,
        )
    assert exc_info.value.code == "ATTACHMENT_LIMIT"
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# 6. Report PDF Manifest with Response Center Provenance
# ---------------------------------------------------------------------------

def test_report_pdf_renders_response_case_manifest() -> None:
    manifest = {
        "mission": {
            "title": "Alert Response: High Temperature",
            "status": "completed",
            "scheduled_start": "2026-09-20T08:00:00+03:00",
            "scheduled_end": "2026-09-20T10:00:00+03:00",
        },
        "route": {"distance_m": 1200.0},
        "sources": {
            "telemetry_latest_at": "2026-09-20T07:55:00Z",
            "forecast_run_id": "forecast-123",
            "sentinel_scene_id": "scene-123",
        },
        "approved_samples": [],
        "scientific_guardrails": {
            "biomass": "CALIBRATION_REQUIRED",
            "gch": "CALIBRATION_REQUIRED",
            "forecast_used_in_route_cost": False,
        },
        "response_case": {
            "id": str(uuid.uuid4()),
            "status": "closed",
            "severity": "critical",
            "acknowledged_at": "2026-09-20T08:05:00Z",
            "closed_at": "2026-09-20T10:15:00Z",
            "resolution_notes": "Moved flock to solar arrays sector 4 for shade. Water refilled.",
            "alerts": [
                {
                    "title": "Extreme Heat Forecast",
                    "severity": "critical",
                    "is_forecast": True,
                    "created_at": "2026-09-20T08:00:00Z",
                }
            ],
            "updates_count": 2,
        },
    }

    pdf = _render_pdf(manifest)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2_000
