from __future__ import annotations

import hashlib
import io
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from geoalchemy2.shape import from_shape, to_shape
from PIL import Image, UnidentifiedImageError
from shapely.geometry import Point
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import OwnerDependency, PrincipalDependency, ProfileDependency, require_api_access
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import APIError
from app.models import (
    Alert,
    AlertRule,
    AuditEvent,
    CalibrationSample,
    DataSourceSetting,
    ForecastRun,
    IngestionRun,
    Mission,
    NotificationDelivery,
    ReportRun,
    ResponseAttachment,
    ResponseCase,
    ResponseUpdate,
    RouteRun,
    SampleAttachment,
    SampleSubmission,
    SatelliteScene,
    TelemetryObservation,
    UserProfile,
)
from app.operational_schemas import (
    AlertRuleCreate,
    AlertRulePatch,
    DataSourcePatch,
    MemberPatch,
    MissionCreate,
    MissionPatch,
    ProfilePatch,
    ReportCreate,
    ResponseCaseAcknowledge,
    ResponseCaseClose,
    ResponseCaseComplete,
    ResponseCaseDismiss,
    ResponseCaseRoute,
    ResponseCaseStart,
    ResponseUpdateCreate,
    SampleReview,
    SampleSubmissionCreate,
)
from app.pilots import PILOTS, PilotDefinition, get_pilot
from app.services.object_storage import ObjectStorage
from app.tasks.jobs import dispatch_report

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_access)])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


def _require_pilot(slug: str | None) -> PilotDefinition:
    pilot = get_pilot(slug)
    if pilot is None:
        raise APIError(
            "PILOT_NOT_FOUND",
            "The requested pilot is not configured.",
            status_code=404,
            details={"pilot_slug": slug, "available": [item.slug for item in PILOTS]},
        )
    return pilot


def _profile(profile: UserProfile) -> dict[str, Any]:
    return {
        "id": str(profile.auth_user_id),
        "default_pilot_slug": profile.default_pilot_slug,
        "email": profile.email,
        "display_name": profile.display_name,
        "timezone": profile.timezone,
        "status": profile.status,
        "role": "member",
        "is_system_owner": profile.is_system_owner,
        "onboarding_completed": profile.onboarding_completed,
        "notification_preferences": profile.notification_preferences,
        "created_at": profile.created_at,
        "last_seen_at": profile.last_seen_at,
    }


def _mission(
    item: Mission, sample_count: int = 0, response_case_id: str | None = None
) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "pilot_slug": item.pilot_slug,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "scheduled_start": item.scheduled_start,
        "scheduled_end": item.scheduled_end,
        "route_run_id": str(item.route_run_id) if item.route_run_id else None,
        "herd_tlu": item.herd_tlu,
        "notes": item.notes,
        "revision": item.revision,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "sample_count": sample_count,
        "response_case_id": response_case_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _owned_mission(
    session: AsyncSession,
    mission_id: UUID,
    profile: UserProfile,
    pilot_slug: str = "jkuat",
) -> Mission:
    mission = await session.get(Mission, mission_id)
    if (
        mission is None
        or (mission.pilot_slug or "jkuat") != pilot_slug
        or (mission.owner_user_id != profile.auth_user_id and not profile.is_system_owner)
    ):
        raise APIError("OWNERSHIP_REQUIRED", "Mission not found.", status_code=404)
    return mission


def _sample(item: SampleSubmission, attachment_count: int = 0) -> dict[str, Any]:
    point = to_shape(item.geom)
    return {
        "id": str(item.id),
        "pilot_slug": item.pilot_slug,
        "sample_code": item.sample_code,
        "external_reference": item.external_reference,
        "mission_id": str(item.mission_id) if item.mission_id else None,
        "sampled_at": item.sampled_at,
        "latitude": point.y,
        "longitude": point.x,
        "dry_matter_kg_ha": item.dry_matter_kg_ha,
        "method": item.method,
        "quadrat_area_m2": item.quadrat_area_m2,
        "status": item.status,
        "review_notes": item.review_notes,
        "attachment_count": attachment_count,
        "revision": item.revision,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _owned_sample(
    session: AsyncSession,
    submission_id: UUID,
    profile: UserProfile,
    pilot_slug: str = "jkuat",
) -> SampleSubmission:
    sample = await session.get(SampleSubmission, submission_id, with_for_update=True)
    if (
        sample is None
        or (sample.pilot_slug or "jkuat") != pilot_slug
        or (sample.owner_user_id != profile.auth_user_id and not profile.is_system_owner)
    ):
        raise APIError("OWNERSHIP_REQUIRED", "Sample submission not found.", status_code=404)
    return sample


@router.get("/me")
async def get_me(profile: ProfileDependency) -> dict[str, Any]:
    return _profile(profile)


@router.patch("/me")
async def patch_me(
    request: ProfilePatch, profile: ProfileDependency, session: SessionDependency
) -> dict[str, Any]:
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await session.commit()
    await session.refresh(profile)
    return _profile(profile)


@router.delete("/me")
async def delete_me(
    profile: ProfileDependency,
    session: SessionDependency,
    settings: SettingsDependency,
    confirm: bool = Query(False),
) -> dict[str, str]:
    if not confirm:
        raise APIError(
            "CONFIRMATION_REQUIRED", "Pass confirm=true to delete the account.", status_code=422
        )
    profile.status = "deleted"
    profile.display_name = "Deleted member"
    profile.email = None
    profile.notification_preferences = {}
    profile.is_system_owner = False
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="account.deleted",
            entity_type="user_profile",
            entity_id=str(profile.auth_user_id),
        )
    )
    await session.commit()
    if settings.auth_mode == "supabase" and settings.supabase_secret_key:
        url = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{profile.auth_user_id}"
        headers = {
            "Authorization": f"Bearer {settings.supabase_secret_key}",
            "apikey": settings.supabase_secret_key,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.delete(url, headers=headers)
        if not response.is_success and response.status_code != 404:
            raise APIError(
                "ACCOUNT_PROVIDER_DELETE_FAILED",
                "The profile was disabled, but the authentication identity needs operator review.",
                status_code=502,
            )
    return {"status": "deleted"}


@router.get("/dashboard")
async def dashboard(
    principal: PrincipalDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    telemetry_at = (
        await session.execute(
            select(func.max(TelemetryObservation.observed_at)).where(
                TelemetryObservation.pilot_slug == pilot_definition.slug
            )
        )
    ).scalar_one_or_none()
    forecast = (
        await session.execute(
            select(ForecastRun)
            .where(ForecastRun.pilot_slug == pilot_definition.slug)
            .order_by(ForecastRun.fetched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    scene = (
        await session.execute(
            select(SatelliteScene)
            .where(
                func.ST_Intersects(
                    SatelliteScene.footprint,
                    func.ST_GeomFromText(pilot_definition.boundary.wkt, 4326),
                )
            )
            .order_by(SatelliteScene.acquired_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    mission = (
        None
        if principal.is_guest
        else (
            await session.execute(
                select(Mission)
                .where(
                    Mission.owner_user_id == principal.user_id,
                    Mission.pilot_slug == pilot_definition.slug,
                    Mission.status.in_(["active", "planned", "draft"]),
                )
                .order_by(Mission.scheduled_start.asc().nullslast(), Mission.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    )
    pending_samples = (
        0
        if principal.is_guest
        else (
            await session.execute(
                select(func.count())
                .select_from(SampleSubmission)
                .where(
                    SampleSubmission.owner_user_id == principal.user_id,
                    SampleSubmission.pilot_slug == pilot_definition.slug,
                    SampleSubmission.status == "pending_review",
                )
            )
        ).scalar_one()
    )
    unread_alerts = (
        0
        if principal.is_guest
        else (
            await session.execute(
                select(func.count())
                .select_from(Alert)
                .where(
                    Alert.owner_user_id == principal.user_id,
                    Alert.pilot_slug == pilot_definition.slug,
                    Alert.acknowledged_at.is_(None),
                )
            )
        ).scalar_one()
    )
    return {
        "generated_at": datetime.now(UTC),
        "pilot_slug": pilot_definition.slug,
        "telemetry_latest_at": telemetry_at,
        "forecast_generated_at": forecast.generated_at if forecast else None,
        "forecast_valid_to": forecast.valid_to if forecast else None,
        "scene": {
            "id": scene.id,
            "acquired_at": scene.acquired_at,
            "cloud_cover_pct": scene.cloud_cover_pct,
        }
        if scene
        else None,
        "active_mission": _mission(mission) if mission else None,
        "pending_samples": pending_samples,
        "unread_alerts": unread_alerts,
        "calibration_status": "CALIBRATION_REQUIRED",
    }


def _field_flow_stage(
    key: str,
    label: str,
    status: Literal["ready", "current", "attention", "blocked"],
    summary: str,
    evidence_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "summary": summary,
        "evidence_at": evidence_at,
    }


@router.get("/field-flow")
async def field_flow(
    principal: PrincipalDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
    mission_id: UUID | None = None,
) -> dict[str, Any]:
    """Build one deterministic evidence-to-report workflow from persisted records."""
    pilot_definition = _require_pilot(pilot)
    now = datetime.now(UTC)

    telemetry = (
        await session.execute(
            select(TelemetryObservation)
            .where(TelemetryObservation.pilot_slug == pilot_definition.slug)
            .order_by(TelemetryObservation.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    forecast = (
        await session.execute(
            select(ForecastRun)
            .where(ForecastRun.pilot_slug == pilot_definition.slug)
            .order_by(ForecastRun.fetched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    scene = (
        await session.execute(
            select(SatelliteScene)
            .where(
                func.ST_Intersects(
                    SatelliteScene.footprint,
                    func.ST_GeomFromText(pilot_definition.boundary.wkt, 4326),
                )
            )
            .order_by(SatelliteScene.acquired_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    mission: Mission | None = None
    if mission_id is not None:
        if principal.is_guest:
            raise APIError("FORBIDDEN", "Guest sessions cannot open missions.", status_code=403)
        mission = await session.get(Mission, mission_id)
        if (
            mission is None
            or mission.pilot_slug != pilot_definition.slug
            or (
                mission.owner_user_id != principal.user_id
                and not principal.is_system_owner
            )
        ):
            raise APIError("OWNERSHIP_REQUIRED", "Mission not found.", status_code=404)
    elif not principal.is_guest:
        mission = (
            await session.execute(
                select(Mission)
                .where(
                    Mission.owner_user_id == principal.user_id,
                    Mission.pilot_slug == pilot_definition.slug,
                    Mission.status.in_(["active", "planned", "draft"]),
                )
                .order_by(
                    (Mission.status == "active").desc(),
                    (Mission.status == "planned").desc(),
                    Mission.scheduled_start.asc().nullslast(),
                    Mission.created_at.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    route: RouteRun | None = None
    if mission and mission.route_run_id:
        route = await session.get(RouteRun, mission.route_run_id)
    elif not principal.is_guest:
        route = (
            await session.execute(
                select(RouteRun)
                .where(
                    RouteRun.owner_user_id == principal.user_id,
                    RouteRun.pilot_slug == pilot_definition.slug,
                    RouteRun.status == "complete",
                )
                .order_by(RouteRun.requested_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    sample_counts = {"draft": 0, "pending_review": 0, "approved": 0, "rejected": 0}
    report: ReportRun | None = None
    if mission:
        rows = (
            await session.execute(
                select(SampleSubmission.status, func.count())
                .where(SampleSubmission.mission_id == mission.id)
                .group_by(SampleSubmission.status)
            )
        ).all()
        sample_counts.update({str(status): int(count) for status, count in rows})
        report = (
            await session.execute(
                select(ReportRun)
                .where(
                    ReportRun.mission_id == mission.id,
                    ReportRun.owner_user_id == mission.owner_user_id,
                )
                .order_by(ReportRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    telemetry_age = (
        max(0.0, (now - telemetry.observed_at).total_seconds()) if telemetry else None
    )
    telemetry_fresh = (
        telemetry_age is not None
        and telemetry_age <= timedelta(hours=6).total_seconds()
    )
    forecast_current = bool(forecast and forecast.valid_from <= now <= forecast.valid_to)
    scene_usable = bool(
        scene
        and scene.processing_status == "complete"
        and (scene.valid_fraction is None or scene.valid_fraction >= 0.5)
    )

    observe_status: Literal["ready", "current", "attention", "blocked"]
    if telemetry_fresh:
        observe_status = "ready"
        observe_summary = f"Fresh observation from {telemetry.source}."
    elif telemetry:
        observe_status = "attention"
        observe_summary = "The latest observation is stale; forecast remains separate."
    elif forecast_current:
        observe_status = "attention"
        observe_summary = "No station observation; only modelled outlook is available."
    else:
        observe_status = "blocked"
        observe_summary = "No current weather evidence is available."

    if scene_usable:
        landscape_status: Literal["ready", "current", "attention", "blocked"] = "ready"
        landscape_summary = "A processed Sentinel-2 surface is available."
    elif scene:
        landscape_status = "attention"
        landscape_summary = "A scene exists but processing or valid coverage is incomplete."
    else:
        landscape_status = "blocked"
        landscape_summary = "No Sentinel-2 scene has been persisted for this pilot."

    route_attached = bool(mission and mission.route_run_id and route)
    if route_attached:
        route_status: Literal["ready", "current", "attention", "blocked"] = "ready"
        route_summary = "A versioned evidence route is attached to the mission."
    elif route:
        route_status = "current"
        route_summary = "A saved route is ready to attach to the mission."
    else:
        route_status = "blocked"
        route_summary = "No saved terrain route is available yet."

    if mission is None:
        mission_status: Literal["ready", "current", "attention", "blocked"] = "blocked"
        mission_summary = "Create a mission to preserve decisions and field activity."
    elif mission.status == "draft":
        mission_status = "current"
        mission_summary = "Mission brief exists and is ready to be planned."
    elif mission.status in {"planned", "active", "completed"}:
        mission_status = "ready"
        mission_summary = f"Mission is {mission.status}."
    else:
        mission_status = "attention"
        mission_summary = f"Mission is {mission.status}; choose another mission to continue."

    if report and report.status == "ready":
        proof_status: Literal["ready", "current", "attention", "blocked"] = "ready"
        proof_summary = "The immutable PDF and JSON evidence package is ready."
    elif report and report.status in {"queued", "processing"}:
        proof_status = "current"
        proof_summary = "The evidence package is being generated."
    elif mission and mission.status == "completed":
        proof_status = "current"
        proof_summary = "Field work is complete; generate its evidence package."
    elif mission:
        proof_status = "attention"
        proof_summary = "Capture field evidence and complete the mission before reporting."
    else:
        proof_status = "blocked"
        proof_summary = "A mission is required before evidence can be packaged."

    if principal.is_guest:
        next_action = {
            "key": "explore_route",
            "label": "Explore an evidence route",
            "reason": "Guest mode can inspect shared evidence but cannot persist field work.",
            "section": "routes",
        }
    elif mission is None and route is None:
        next_action = {
            "key": "plan_route",
            "label": "Plan the first route",
            "reason": "A terrain-backed route creates the movement evidence for a mission.",
            "section": "routes",
        }
    elif mission is None:
        next_action = {
            "key": "create_mission",
            "label": "Create a mission",
            "reason": "A saved route is available and can be attached immediately.",
            "section": "field-flow",
        }
    elif not route_attached:
        next_action = {
            "key": "attach_route" if route else "plan_route",
            "label": "Attach the saved route" if route else "Plan a mission route",
            "reason": "The mission needs a versioned route before field deployment.",
            "section": "field-flow" if route else "routes",
        }
    elif mission.status == "draft":
        next_action = {
            "key": "plan_mission",
            "label": "Mark mission as planned",
            "reason": "The brief and route are ready for scheduling.",
            "section": "field-flow",
        }
    elif mission.status == "planned":
        next_action = {
            "key": "start_mission",
            "label": "Start field mission",
            "reason": "Starting creates an auditable field-work timestamp.",
            "section": "field-flow",
        }
    elif mission.status == "active" and sum(sample_counts.values()) == 0:
        next_action = {
            "key": "capture_sample",
            "label": "Capture field evidence",
            "reason": "A georeferenced sample strengthens the mission record but remains optional.",
            "section": "samples",
        }
    elif mission.status == "active":
        next_action = {
            "key": "complete_mission",
            "label": "Complete mission",
            "reason": "Field evidence is attached and the mission can be closed.",
            "section": "field-flow",
        }
    elif mission.status == "completed" and report is None:
        next_action = {
            "key": "generate_report",
            "label": "Generate evidence package",
            "reason": "The completed mission is ready for a versioned PDF and JSON receipt.",
            "section": "field-flow",
        }
    else:
        next_action = {
            "key": "review_report",
            "label": "Review mission evidence",
            "reason": "The workflow record is available for review and export.",
            "section": "reports",
        }

    return {
        "generated_at": now,
        "pilot_slug": pilot_definition.slug,
        "mission": _mission(mission, sum(sample_counts.values())) if mission else None,
        "route": {
            "id": str(route.id),
            "name": route.name or f"Route {str(route.id)[:8]}",
            "attached": route_attached,
            "requested_at": route.requested_at,
            "total_distance_m": route.total_distance_m,
            "estimated_time_s": route.total_time_s,
            "profile": route.parameters.get("profile", "resource_aware"),
        }
        if route
        else None,
        "evidence": {
            "telemetry": {
                "status": "healthy" if telemetry_fresh else "stale" if telemetry else "unavailable",
                "observed_at": telemetry.observed_at if telemetry else None,
                "source": telemetry.source if telemetry else None,
                "station_id": telemetry.station_id if telemetry else None,
                "quality_flags": telemetry.quality_flags if telemetry else [],
                "age_seconds": telemetry_age,
            },
            "forecast": {
                "status": "current" if forecast_current else "stale" if forecast else "unavailable",
                "generated_at": forecast.generated_at if forecast else None,
                "valid_to": forecast.valid_to if forecast else None,
                "source": forecast.source if forecast else None,
                "model": forecast.model if forecast else None,
            },
            "scene": {
                "status": "ready" if scene_usable else "attention" if scene else "unavailable",
                "id": scene.id if scene else None,
                "acquired_at": scene.acquired_at if scene else None,
                "source": scene.source if scene else None,
                "valid_fraction": scene.valid_fraction if scene else None,
            },
        },
        "samples": {"total": sum(sample_counts.values()), **sample_counts},
        "report": _report(report) if report else None,
        "stages": [
            _field_flow_stage(
                "sense", "Sense", observe_status, observe_summary,
                telemetry.observed_at if telemetry else forecast.generated_at if forecast else None,
            ),
            _field_flow_stage(
                "read", "Read landscape", landscape_status, landscape_summary,
                scene.acquired_at if scene else None,
            ),
            _field_flow_stage(
                "move", "Move", route_status, route_summary,
                route.requested_at if route else None,
            ),
            _field_flow_stage(
                "act", "Act", mission_status, mission_summary,
                mission.updated_at if mission else None,
            ),
            _field_flow_stage(
                "prove", "Prove", proof_status, proof_summary,
                report.completed_at if report else None,
            ),
        ],
        "next_action": next_action,
        "calibration_status": "CALIBRATION_REQUIRED",
    }


@router.get("/missions")
async def list_missions(
    profile: ProfileDependency,
    session: SessionDependency,
    status: str | None = None,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    statement = select(Mission).where(
        Mission.owner_user_id == profile.auth_user_id,
        Mission.pilot_slug == pilot_definition.slug,
    )
    if status:
        statement = statement.where(Mission.status == status)
    rows = list((await session.execute(statement.order_by(Mission.created_at.desc()))).scalars())
    counts = (
        dict(
            (
                await session.execute(
                    select(SampleSubmission.mission_id, func.count())
                    .where(SampleSubmission.mission_id.in_([item.id for item in rows]))
                    .group_by(SampleSubmission.mission_id)
                )
            ).all()
        )
        if rows
        else {}
    )
    case_map = (
        dict(
            (
                await session.execute(
                    select(ResponseCase.mission_id, ResponseCase.id).where(
                        ResponseCase.mission_id.in_([item.id for item in rows])
                    )
                )
            ).all()
        )
        if rows
        else {}
    )
    return {
        "data": [
            _mission(
                item,
                counts.get(item.id, 0),
                str(case_map[item.id]) if item.id in case_map else None,
            )
            for item in rows
        ],
        "count": len(rows),
    }


@router.get("/routes")
async def list_saved_routes(
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    rows = list(
        (
            await session.execute(
                select(RouteRun)
                .where(
                    RouteRun.owner_user_id == profile.auth_user_id, RouteRun.status == "complete"
                    , RouteRun.pilot_slug == pilot_definition.slug
                )
                .order_by(RouteRun.requested_at.desc())
                .limit(100)
            )
        ).scalars()
    )
    return {
        "data": [
            {
                "id": str(item.id),
                "name": item.name or f"Route {str(item.id)[:8]}",
                "requested_at": item.requested_at,
                "total_distance_m": item.total_distance_m,
                "estimated_time_s": item.total_time_s,
                "profile": item.parameters.get("profile", "resource_aware"),
            }
            for item in rows
        ],
        "count": len(rows),
    }


@router.post("/missions", status_code=201)
async def create_mission(
    request: MissionCreate,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    if request.route_run_id:
        route = await session.get(RouteRun, request.route_run_id)
        if (
            route is None
            or route.owner_user_id != profile.auth_user_id
            or route.pilot_slug != pilot_definition.slug
        ):
            raise APIError(
                "OWNERSHIP_REQUIRED", "The selected route is unavailable.", status_code=422
            )
    mission = Mission(
        pilot_slug=pilot_definition.slug,
        owner_user_id=profile.auth_user_id,
        **request.model_dump(),
    )
    session.add(mission)
    await session.flush()
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="mission.create",
            entity_type="mission",
            entity_id=str(mission.id),
            details={"title": mission.title},
        )
    )
    await session.commit()
    await session.refresh(mission)
    return _mission(mission)


@router.get("/missions/{mission_id}")
async def get_mission(
    mission_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    mission = await _owned_mission(session, mission_id, profile, _require_pilot(pilot).slug)
    sample_count = (
        await session.execute(
            select(func.count())
            .select_from(SampleSubmission)
            .where(SampleSubmission.mission_id == mission.id)
        )
    ).scalar_one()
    resp_case_id = (
        await session.execute(
            select(ResponseCase.id).where(ResponseCase.mission_id == mission.id).limit(1)
        )
    ).scalar_one_or_none()
    return _mission(
        mission, sample_count, str(resp_case_id) if resp_case_id else None
    )


@router.post("/missions/{mission_id}/duplicate", status_code=201)
async def duplicate_mission(
    mission_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    original = await _owned_mission(session, mission_id, profile, _require_pilot(pilot).slug)
    copy = Mission(
        pilot_slug=original.pilot_slug,
        owner_user_id=profile.auth_user_id,
        title=f"{original.title} (Copy)",
        description=original.description,
        scheduled_start=None,
        scheduled_end=None,
        route_run_id=original.route_run_id,
        herd_tlu=original.herd_tlu,
        notes=original.notes,
        status="draft",
        revision=1,
    )
    session.add(copy)
    await session.flush()
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="mission.duplicate",
            entity_type="mission",
            entity_id=str(copy.id),
            details={"source_mission_id": str(original.id)},
        )
    )
    await session.commit()
    await session.refresh(copy)
    return _mission(copy)


@router.get("/missions/{mission_id}/samples")
async def list_mission_samples(
    mission_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    mission = await _owned_mission(session, mission_id, profile, _require_pilot(pilot).slug)
    rows = list(
        (
            await session.execute(
                select(SampleSubmission)
                .where(SampleSubmission.mission_id == mission.id)
                .order_by(SampleSubmission.created_at.desc())
            )
        ).scalars()
    )
    counts = (
        dict(
            (
                await session.execute(
                    select(SampleAttachment.submission_id, func.count())
                    .where(SampleAttachment.submission_id.in_([item.id for item in rows]))
                    .group_by(SampleAttachment.submission_id)
                )
            ).all()
        )
        if rows
        else {}
    )
    return {"data": [_sample(item, counts.get(item.id, 0)) for item in rows], "count": len(rows)}


@router.get("/missions/{mission_id}/timeline")
async def get_mission_timeline(
    mission_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    mission = await _owned_mission(session, mission_id, profile, _require_pilot(pilot).slug)
    sample_ids = list(
        (
            await session.execute(
                select(SampleSubmission.id).where(SampleSubmission.mission_id == mission.id)
            )
        ).scalars()
    )
    entity_ids = [str(mission.id)] + [str(sid) for sid in sample_ids]
    rows = list(
        (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.entity_id.in_(entity_ids))
                .order_by(AuditEvent.occurred_at.desc())
            )
        ).scalars()
    )
    return {
        "data": [
            {
                "id": str(ev.id),
                "action": ev.action,
                "entity_type": ev.entity_type,
                "entity_id": ev.entity_id,
                "details": ev.details,
                "occurred_at": ev.occurred_at,
            }
            for ev in rows
        ],
        "count": len(rows),
    }


@router.patch("/missions/{mission_id}")
async def patch_mission(
    mission_id: UUID,
    request: MissionPatch,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    mission = await _owned_mission(session, mission_id, profile, _require_pilot(pilot).slug)
    if request.revision != mission.revision:
        raise APIError(
            "REVISION_CONFLICT",
            "The mission changed on another device. Refresh before saving.",
            status_code=409,
            details={"current_revision": mission.revision},
        )
    updates = request.model_dump(exclude_unset=True, exclude={"revision"})
    if "status" in updates or "route_run_id" in updates:
        resp_case = (
            await session.execute(
                select(ResponseCase).where(ResponseCase.mission_id == mission.id)
            )
        ).scalar_one_or_none()
        if resp_case is not None:
            raise APIError(
                "RESPONSE_MISSION_RESTRICTED",
                (
                    "Status and route transitions for response missions "
                    "must be performed via the Response Center."
                ),
                status_code=409,
            )
    if "route_run_id" in updates and updates["route_run_id"]:
        route = await session.get(RouteRun, updates["route_run_id"])
        if (
            route is None
            or route.owner_user_id != profile.auth_user_id
            or route.pilot_slug != mission.pilot_slug
        ):
            raise APIError(
                "OWNERSHIP_REQUIRED", "The selected route is unavailable.", status_code=422
            )
    previous_status = mission.status
    for field, value in updates.items():
        setattr(mission, field, value)
    if (
        mission.scheduled_start
        and mission.scheduled_end
        and mission.scheduled_end < mission.scheduled_start
    ):
        raise APIError("INVALID_TIME_RANGE", "Mission end must follow its start.", status_code=422)
    if mission.status == "active" and previous_status != "active":
        mission.started_at = datetime.now(UTC)
    if mission.status == "completed" and previous_status != "completed":
        mission.completed_at = datetime.now(UTC)
    mission.revision += 1
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action=f"mission.{mission.status}"
            if mission.status != previous_status
            else "mission.update",
            entity_type="mission",
            entity_id=str(mission.id),
            details={"status": mission.status, "revision": mission.revision},
        )
    )
    await session.commit()
    await session.refresh(mission)
    return _mission(mission)


@router.delete("/missions/{mission_id}", status_code=204)
async def delete_mission(
    mission_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> None:
    mission = await _owned_mission(session, mission_id, profile, _require_pilot(pilot).slug)
    if mission.status == "active":
        raise APIError(
            "MISSION_ACTIVE", "An active mission must be cancelled first.", status_code=409
        )
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="mission.delete",
            entity_type="mission",
            entity_id=str(mission.id),
            details={"title": mission.title},
        )
    )
    await session.delete(mission)
    await session.commit()


@router.get("/sample-submissions")
async def list_samples(
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    statement = select(SampleSubmission).where(
        SampleSubmission.pilot_slug == pilot_definition.slug
    )
    if not profile.is_system_owner:
        statement = statement.where(SampleSubmission.owner_user_id == profile.auth_user_id)
    rows = list(
        (await session.execute(statement.order_by(SampleSubmission.created_at.desc()))).scalars()
    )
    counts = (
        dict(
            (
                await session.execute(
                    select(SampleAttachment.submission_id, func.count())
                    .where(SampleAttachment.submission_id.in_([item.id for item in rows]))
                    .group_by(SampleAttachment.submission_id)
                )
            ).all()
        )
        if rows
        else {}
    )
    return {"data": [_sample(item, counts.get(item.id, 0)) for item in rows], "count": len(rows)}


@router.post("/sample-submissions", status_code=201)
async def create_sample(
    request: SampleSubmissionCreate,
    profile: ProfileDependency,
    session: SessionDependency,
    settings: SettingsDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    del settings
    pilot_definition = _require_pilot(pilot)
    distance = _haversine_km(
        request.latitude,
        request.longitude,
        pilot_definition.latitude,
        pilot_definition.longitude,
    )
    if distance > pilot_definition.radius_km:
        raise APIError(
            "OUTSIDE_PILOT",
            f"Sample coordinates fall outside the {pilot_definition.name} pilot.",
            status_code=422,
            details={"distance_km": round(distance, 3)},
        )
    if request.mission_id:
        mission = await session.get(Mission, request.mission_id)
        if mission is None or (
            mission.owner_user_id != profile.auth_user_id and not profile.is_system_owner
        ):
            raise APIError(
                "OWNERSHIP_REQUIRED", "The selected mission is unavailable.", status_code=422
            )
        if mission.pilot_slug != pilot_definition.slug:
            raise APIError(
                "PILOT_MISMATCH",
                "The selected mission belongs to another pilot.",
                status_code=422,
            )
    sample = SampleSubmission(
        pilot_slug=pilot_definition.slug,
        owner_user_id=profile.auth_user_id,
        mission_id=request.mission_id,
        sample_code=f"SS-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(4).upper()}",
        external_reference=request.external_reference,
        sampled_at=request.sampled_at.astimezone(UTC),
        geom=from_shape(Point(request.longitude, request.latitude), srid=4326),
        dry_matter_kg_ha=request.dry_matter_kg_ha,
        method=request.method,
        quadrat_area_m2=request.quadrat_area_m2,
        status="draft",
    )
    session.add(sample)
    await session.flush()
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="sample.create",
            entity_type="sample_submission",
            entity_id=str(sample.id),
            details={
                "sample_code": sample.sample_code,
                "mission_id": str(request.mission_id) if request.mission_id else None,
            },
        )
    )
    await session.commit()
    await session.refresh(sample)
    return _sample(sample)


@router.post("/sample-submissions/{submission_id}/attachments", status_code=201)
async def add_sample_attachment(
    submission_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    settings: SettingsDependency,
    file: UploadFile = File(),
    pilot: str = "jkuat",
) -> dict[str, Any]:
    sample = await _owned_sample(session, submission_id, profile, _require_pilot(pilot).slug)
    if sample.status not in {"draft", "rejected"}:
        raise APIError("REVIEW_REQUIRED", "Submitted samples cannot be modified.", status_code=409)
    attachment_count = (
        await session.execute(
            select(func.count())
            .select_from(SampleAttachment)
            .where(SampleAttachment.submission_id == sample.id)
        )
    ).scalar_one()
    if attachment_count >= 3:
        raise APIError(
            "ATTACHMENT_LIMIT", "A sample can contain at most three photos.", status_code=422
        )
    payload = await file.read()
    if len(payload) > 8 * 1024 * 1024:
        raise APIError("FILE_TOO_LARGE", "Sample photos are limited to 8 MB.", status_code=413)
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise APIError("UNSUPPORTED_MEDIA_TYPE", "Use JPEG, PNG or WebP photos.", status_code=415)
    try:
        image = Image.open(io.BytesIO(payload))
        image.thumbnail((2400, 2400))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, "WEBP", quality=88, method=6)
        normalized = output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise APIError(
            "INVALID_IMAGE", "The uploaded photo cannot be decoded.", status_code=422
        ) from exc
    checksum = hashlib.sha256(normalized).hexdigest()
    object_key = f"{profile.auth_user_id}/{sample.id}/{uuid.uuid4()}.webp"
    await ObjectStorage(settings).put(
        settings.sample_evidence_bucket, object_key, normalized, "image/webp"
    )
    attachment = SampleAttachment(
        submission_id=sample.id,
        object_key=object_key,
        original_filename=(file.filename or "sample-photo")[:255],
        content_type="image/webp",
        size_bytes=len(normalized),
        checksum=checksum,
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return {
        "id": str(attachment.id),
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
    }


@router.post("/sample-submissions/{submission_id}/submit")
async def submit_sample(
    submission_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    sample = await _owned_sample(session, submission_id, profile, _require_pilot(pilot).slug)
    if sample.status == "pending_review":
        return _sample(sample)
    if sample.status not in {"draft", "rejected"}:
        raise APIError("REVIEW_REQUIRED", "This sample cannot be submitted again.", status_code=409)
    sample.status = "pending_review"
    sample.submitted_at = datetime.now(UTC)
    sample.review_notes = None
    sample.revision += 1
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="sample.submit",
            entity_type="sample_submission",
            entity_id=str(sample.id),
            details={"sample_code": sample.sample_code},
        )
    )
    await session.commit()
    await session.refresh(sample)
    return _sample(sample)


@router.post("/admin/sample-submissions/{submission_id}/review")
async def review_sample(
    submission_id: UUID,
    request: SampleReview,
    owner: OwnerDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    sample = await session.get(SampleSubmission, submission_id)
    if sample is None or (sample.pilot_slug or "jkuat") != pilot_definition.slug:
        raise APIError("SAMPLE_NOT_FOUND", "Sample submission not found.", status_code=404)
    if sample.status == "approved" and request.decision == "approved":
        return _sample(sample)
    if sample.status != "pending_review":
        raise APIError("REVIEW_REQUIRED", "Only pending samples can be reviewed.", status_code=409)
    now = datetime.now(UTC)
    if request.decision == "approved":
        calibration = CalibrationSample(
            pilot_slug=sample.pilot_slug,
            external_sample_id=sample.sample_code,
            sampled_at=sample.sampled_at,
            geom=sample.geom,
            dry_matter_kg_ha=sample.dry_matter_kg_ha,
            method=sample.method,
            quadrat_area_m2=sample.quadrat_area_m2,
            metadata_json={
                "sample_submission_id": str(sample.id),
                "reviewed_by": str(owner.auth_user_id),
            },
        )
        session.add(calibration)
        await session.flush()
        sample.calibration_sample_id = calibration.id
    sample.status = request.decision
    sample.review_notes = request.notes.strip() or None
    sample.reviewed_at = now
    sample.reviewed_by_id = owner.auth_user_id
    sample.revision += 1
    alert = Alert(
        pilot_slug=sample.pilot_slug,
        owner_user_id=sample.owner_user_id,
        kind="sample_review",
        title=f"Sample {sample.sample_code} {request.decision}",
        message=request.notes.strip() or f"Your sample was {request.decision}.",
        severity="info" if request.decision == "approved" else "warning",
        payload={"sample_submission_id": str(sample.id), "decision": request.decision},
        dedupe_key=f"sample-review:{sample.id}:{request.decision}:{sample.revision}",
    )
    session.add(alert)
    await session.flush()
    target_profile = await session.get(UserProfile, sample.owner_user_id)
    if target_profile and target_profile.notification_preferences.get("email", True):
        session.add(NotificationDelivery(alert_id=alert.id, channel="email", status="pending"))
    session.add(
        AuditEvent(
            actor_user_id=owner.auth_user_id,
            action=f"sample.{request.decision}",
            entity_type="sample_submission",
            entity_id=str(sample.id),
            details={"notes": request.notes},
        )
    )
    await session.commit()
    await session.refresh(sample)
    return _sample(sample)


@router.post("/reports", status_code=202)
async def create_report(
    request: ReportCreate,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    mission = await _owned_mission(
        session, request.mission_id, profile, pilot_definition.slug
    )
    if mission.pilot_slug != pilot_definition.slug:
        raise APIError(
            "PILOT_MISMATCH", "The selected mission belongs to another pilot.", status_code=422
        )
    report = ReportRun(
        pilot_slug=pilot_definition.slug,
        owner_user_id=profile.auth_user_id,
        mission_id=mission.id,
        status="queued",
        parameters={"title": request.title or mission.title},
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    task = dispatch_report(str(report.id))
    return {"id": str(report.id), "status": report.status, "task_id": task.id}


@router.get("/reports")
async def list_reports(
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    rows = list(
        (
            await session.execute(
                select(ReportRun)
                .where(
                    ReportRun.owner_user_id == profile.auth_user_id,
                    ReportRun.pilot_slug == pilot_definition.slug,
                )
                .order_by(ReportRun.created_at.desc())
            )
        ).scalars()
    )
    return {"data": [_report(item) for item in rows], "count": len(rows)}


def _report(item: ReportRun) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "pilot_slug": item.pilot_slug,
        "mission_id": str(item.mission_id),
        "status": item.status,
        "parameters": item.parameters,
        "evidence_manifest": item.evidence_manifest,
        "error_message": item.error_message,
        "created_at": item.created_at,
        "completed_at": item.completed_at,
        "downloads": {
            "pdf": f"/reports/{item.id}/download/pdf" if item.pdf_object_key else None,
            "json": f"/reports/{item.id}/download/json" if item.json_object_key else None,
        },
    }


@router.get("/reports/{report_id}")
async def get_report(
    report_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    report = await session.get(ReportRun, report_id)
    if (
        report is None
        or report.pilot_slug != pilot_definition.slug
        or report.owner_user_id != profile.auth_user_id
    ):
        raise APIError("OWNERSHIP_REQUIRED", "Report not found.", status_code=404)
    return _report(report)


@router.get("/reports/{report_id}/download/{format_name}", response_model=None)
async def download_report(
    report_id: UUID,
    format_name: Literal["pdf", "json"],
    profile: ProfileDependency,
    session: SessionDependency,
    settings: SettingsDependency,
    pilot: str = "jkuat",
) -> RedirectResponse | FileResponse:
    pilot_definition = _require_pilot(pilot)
    report = await session.get(ReportRun, report_id)
    if (
        report is None
        or report.pilot_slug != pilot_definition.slug
        or (report.owner_user_id != profile.auth_user_id and not profile.is_system_owner)
    ):
        raise APIError("OWNERSHIP_REQUIRED", "Report not found.", status_code=404)
    key = report.pdf_object_key if format_name == "pdf" else report.json_object_key
    if report.status != "ready" or not key:
        raise APIError("REPORT_NOT_READY", "The report is not ready for download.", status_code=409)
    storage = ObjectStorage(settings)
    signed_url = await storage.signed_url(settings.reports_bucket, key)
    if signed_url:
        return RedirectResponse(signed_url, status_code=307)
    path = storage.local_path(settings.reports_bucket, key)
    if not path.exists():
        raise APIError("REPORT_FILE_MISSING", "The report file is unavailable.", status_code=404)
    media_type = "application/pdf" if format_name == "pdf" else "application/json"
    return FileResponse(
        path, media_type=media_type, filename=f"solarshepherd-{report.id}.{format_name}"
    )


@router.get("/alert-rules")
async def list_alert_rules(
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    rows = list(
        (
            await session.execute(
                select(AlertRule)
                .where(
                    AlertRule.owner_user_id == profile.auth_user_id,
                    AlertRule.pilot_slug == pilot_definition.slug,
                )
                .order_by(AlertRule.created_at.desc())
            )
        ).scalars()
    )
    return {"data": [_alert_rule(item) for item in rows], "count": len(rows)}


def _alert_rule(item: AlertRule) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "pilot_slug": item.pilot_slug,
        "name": item.name,
        "kind": item.kind,
        "metric": item.metric,
        "comparator": item.comparator,
        "threshold": item.threshold,
        "lookahead_hours": item.lookahead_hours,
        "cooldown_minutes": item.cooldown_minutes,
        "channels": item.channels,
        "enabled": item.enabled,
        "severity": getattr(item, "severity", "warning") or "warning",
        "response_mode": getattr(item, "response_mode", "case_and_mission") or "case_and_mission",
        "last_triggered_at": item.last_triggered_at,
    }


@router.post("/alert-rules", status_code=201)
async def create_alert_rule(
    request: AlertRuleCreate,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    rule = AlertRule(
        pilot_slug=pilot_definition.slug,
        owner_user_id=profile.auth_user_id,
        **request.model_dump(),
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return _alert_rule(rule)


@router.patch("/alert-rules/{rule_id}")
async def patch_alert_rule(
    rule_id: UUID,
    request: AlertRulePatch,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    rule = await session.get(AlertRule, rule_id)
    if (
        rule is None
        or rule.pilot_slug != pilot_definition.slug
        or rule.owner_user_id != profile.auth_user_id
    ):
        raise APIError("OWNERSHIP_REQUIRED", "Alert rule not found.", status_code=404)
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await session.commit()
    await session.refresh(rule)
    return _alert_rule(rule)


@router.delete("/alert-rules/{rule_id}", status_code=204)
async def delete_alert_rule(
    rule_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> None:
    pilot_definition = _require_pilot(pilot)
    rule = await session.get(AlertRule, rule_id)
    if (
        rule is None
        or rule.pilot_slug != pilot_definition.slug
        or rule.owner_user_id != profile.auth_user_id
    ):
        raise APIError("OWNERSHIP_REQUIRED", "Alert rule not found.", status_code=404)
    await session.delete(rule)
    await session.commit()


@router.get("/alerts")
async def list_alerts(
    profile: ProfileDependency,
    session: SessionDependency,
    unread_only: bool = False,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    statement = select(Alert).where(
        Alert.owner_user_id == profile.auth_user_id,
        Alert.pilot_slug == pilot_definition.slug,
    )
    if unread_only:
        statement = statement.where(Alert.acknowledged_at.is_(None))
    rows = list(
        (await session.execute(statement.order_by(Alert.created_at.desc()).limit(200))).scalars()
    )
    return {
        "data": [
            {
                "id": str(item.id),
                "pilot_slug": item.pilot_slug,
                "response_case_id": str(item.response_case_id) if item.response_case_id else None,
                "kind": item.kind,
                "title": item.title,
                "message": item.message,
                "severity": item.severity,
                "payload": item.payload,
                "created_at": item.created_at,
                "acknowledged_at": item.acknowledged_at,
            }
            for item in rows
        ],
        "count": len(rows),
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = "jkuat",
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    alert = await session.get(Alert, alert_id)
    if (
        alert is None
        or alert.pilot_slug != pilot_definition.slug
        or alert.owner_user_id != profile.auth_user_id
    ):
        raise APIError("OWNERSHIP_REQUIRED", "Alert not found.", status_code=404)
    alert.acknowledged_at = alert.acknowledged_at or datetime.now(UTC)
    await session.commit()
    return {"id": str(alert.id), "acknowledged_at": alert.acknowledged_at}


@router.get("/admin/members")
async def list_members(owner: OwnerDependency, session: SessionDependency) -> dict[str, Any]:
    del owner
    rows = list(
        (
            await session.execute(select(UserProfile).order_by(UserProfile.created_at.desc()))
        ).scalars()
    )
    return {"data": [_profile(item) for item in rows], "count": len(rows)}


@router.patch("/admin/members/{user_id}")
async def patch_member(
    user_id: UUID,
    request: MemberPatch,
    owner: OwnerDependency,
    session: SessionDependency,
) -> dict[str, Any]:
    profile = await session.get(UserProfile, user_id)
    if profile is None:
        raise APIError("MEMBER_NOT_FOUND", "Member not found.", status_code=404)
    if profile.auth_user_id == owner.auth_user_id and request.status == "suspended":
        raise APIError(
            "OWNER_SELF_LOCKOUT", "The owner cannot suspend their own account.", status_code=409
        )
    profile.status = request.status
    session.add(
        AuditEvent(
            actor_user_id=owner.auth_user_id,
            action=f"member.{request.status}",
            entity_type="user_profile",
            entity_id=str(profile.auth_user_id),
        )
    )
    await session.commit()
    await session.refresh(profile)
    return _profile(profile)


@router.get("/admin/audit-events")
async def list_audit_events(
    owner: OwnerDependency,
    session: SessionDependency,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    del owner
    rows = list(
        (
            await session.execute(
                select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit)
            )
        ).scalars()
    )
    return {
        "data": [
            {
                "id": str(item.id),
                "actor_user_id": str(item.actor_user_id) if item.actor_user_id else None,
                "action": item.action,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "details": item.details,
                "occurred_at": item.occurred_at,
            }
            for item in rows
        ],
        "count": len(rows),
    }


@router.get("/admin/data-sources")
async def list_data_sources(
    owner: OwnerDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    del owner
    pilot_definition = _require_pilot(pilot)
    settings_by_source = {
        item.source: item
        for item in (
            await session.execute(
                select(DataSourceSetting).where(
                    DataSourceSetting.pilot_slug == pilot_definition.slug
                )
            )
        ).scalars()
    }
    latest_runs = list(
        (
            await session.execute(
                select(IngestionRun)
                .where(IngestionRun.pilot_slug == pilot_definition.slug)
                .order_by(IngestionRun.source, IngestionRun.started_at.desc())
            )
        ).scalars()
    )
    latest_by_source: dict[str, IngestionRun] = {}
    for run in latest_runs:
        latest_by_source.setdefault(run.source, run)
    sources = []
    names = ["aviation_weather", "forecast", "satellite", "terrain", "osm"]
    if pilot_definition.slug == "jkuat":
        names.insert(0, "conduit")
    for name in names:
        configured = settings_by_source.get(name)
        run = latest_by_source.get(name)
        sources.append(
            {
                "source": name,
                "enabled": configured.enabled if configured else True,
                "schedule": configured.schedule if configured else None,
                "mapping": configured.mapping if configured else {},
                "pilot_slug": pilot_definition.slug,
                "latest_status": run.status if run else "never_run",
                "latest_run_at": run.started_at if run else None,
                "records_written": run.records_written if run else 0,
                "error_code": run.error_code if run else None,
            }
        )
    return {"data": sources, "count": len(sources)}


@router.patch("/admin/data-sources/{source}")
async def patch_data_source(
    source: Literal[
        "conduit", "aviation_weather", "forecast", "satellite", "terrain", "osm"
    ],
    request: DataSourcePatch,
    owner: OwnerDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    if source == "conduit" and pilot_definition.slug != "jkuat":
        raise APIError(
            "SOURCE_NOT_AVAILABLE", "Conduit is only configured for JKUAT.", status_code=422
        )
    item = await session.get(
        DataSourceSetting,
        {"pilot_slug": pilot_definition.slug, "source": source},
    )
    if item is None:
        item = DataSourceSetting(
            pilot_slug=pilot_definition.slug,
            source=source,
            updated_by_id=owner.auth_user_id,
        )
        session.add(item)
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    item.updated_by_id = owner.auth_user_id
    session.add(
        AuditEvent(
            actor_user_id=owner.auth_user_id,
            action="data_source.updated",
            entity_type="data_source",
            entity_id=f"{pilot_definition.slug}:{source}",
            details={
                "pilot_slug": pilot_definition.slug,
                **request.model_dump(exclude_unset=True),
            },
        )
    )
    await session.commit()
    return {
        "source": item.source,
        "pilot_slug": item.pilot_slug,
        "enabled": item.enabled,
        "schedule": item.schedule,
        "mapping": item.mapping,
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    a = sin(delta_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lon / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(a))


# ---------------------------------------------------------------------------
# Response Center (Alert-to-Action Workflow: Detect -> Verify -> Route -> Respond -> Prove)
# ---------------------------------------------------------------------------


async def _owned_response_case(
    session: AsyncSession,
    case_id: UUID,
    profile: UserProfile,
    pilot_slug: str = "jkuat",
) -> ResponseCase:
    case = await session.get(ResponseCase, case_id)
    if (
        case is None
        or (case.pilot_slug or "jkuat") != pilot_slug
        or (case.owner_user_id != profile.auth_user_id and not profile.is_system_owner)
    ):
        raise APIError("OWNERSHIP_REQUIRED", "Response case not found.", status_code=404)
    return case


def _response_case_summary(
    item: ResponseCase,
    rule_name: str | None = None,
    mission_title: str | None = None,
    mission_status: str | None = None,
    alert_count: int = 0,
    update_count: int = 0,
    route_run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "pilot_slug": item.pilot_slug,
        "owner_user_id": str(item.owner_user_id),
        "rule_id": str(item.rule_id) if item.rule_id else None,
        "rule_name": rule_name,
        "mission_id": str(item.mission_id),
        "mission_title": mission_title,
        "mission_status": mission_status,
        "status": item.status,
        "severity": item.severity,
        "revision": item.revision,
        "resolution_notes": item.resolution_notes,
        "dismissal_reason": item.dismissal_reason,
        "acknowledged_at": item.acknowledged_at,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "closed_at": item.closed_at,
        "dismissed_at": item.dismissed_at,
        "alert_count": alert_count,
        "update_count": update_count,
        "route_run_id": route_run_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/response-cases")
async def list_response_cases(
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
    status: str | None = None,
    severity: str | None = None,
    rule_id: UUID | None = None,
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    statement = select(ResponseCase).where(ResponseCase.pilot_slug == pilot_definition.slug)
    if not profile.is_system_owner:
        statement = statement.where(ResponseCase.owner_user_id == profile.auth_user_id)
    if status:
        statement = statement.where(ResponseCase.status == status)
    if severity:
        statement = statement.where(ResponseCase.severity == severity)
    if rule_id:
        statement = statement.where(ResponseCase.rule_id == rule_id)

    result = await session.execute(statement.order_by(ResponseCase.created_at.desc()))
    rows = list(result.scalars())
    if not rows:
        return {"data": [], "count": 0}

    case_ids = [c.id for c in rows]
    mission_ids = [c.mission_id for c in rows]
    rule_ids = [c.rule_id for c in rows if c.rule_id is not None]

    missions_map = (
        dict(
            (
                await session.execute(
                    select(Mission.id, Mission).where(Mission.id.in_(mission_ids))
                )
            ).all()
        )
        if mission_ids
        else {}
    )

    rules_map = (
        dict(
            (
                await session.execute(
                    select(AlertRule.id, AlertRule.name).where(AlertRule.id.in_(rule_ids))
                )
            ).all()
        )
        if rule_ids
        else {}
    )

    alert_counts = (
        dict(
            (
                await session.execute(
                    select(Alert.response_case_id, func.count())
                    .where(Alert.response_case_id.in_(case_ids))
                    .group_by(Alert.response_case_id)
                )
            ).all()
        )
        if case_ids
        else {}
    )

    update_counts = (
        dict(
            (
                await session.execute(
                    select(ResponseUpdate.response_case_id, func.count())
                    .where(ResponseUpdate.response_case_id.in_(case_ids))
                    .group_by(ResponseUpdate.response_case_id)
                )
            ).all()
        )
        if case_ids
        else {}
    )

    data = []
    for c in rows:
        m = missions_map.get(c.mission_id)
        data.append(
            _response_case_summary(
                c,
                rule_name=rules_map.get(c.rule_id) if c.rule_id else None,
                mission_title=m.title if m else None,
                mission_status=m.status if m else None,
                alert_count=alert_counts.get(c.id, 0),
                update_count=update_counts.get(c.id, 0),
                route_run_id=str(m.route_run_id) if m and m.route_run_id else None,
            )
        )
    return {"data": data, "count": len(data)}


@router.get("/response-cases/{case_id}")
async def get_response_case(
    case_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    mission = await session.get(Mission, case.mission_id)
    rule = await session.get(AlertRule, case.rule_id) if case.rule_id else None
    route = (
        await session.get(RouteRun, mission.route_run_id)
        if mission and mission.route_run_id
        else None
    )

    alerts = list(
        (
            await session.execute(
                select(Alert)
                .where(Alert.response_case_id == case.id)
                .order_by(Alert.created_at.desc())
            )
        ).scalars()
    )

    updates = list(
        (
            await session.execute(
                select(ResponseUpdate)
                .where(ResponseUpdate.response_case_id == case.id)
                .order_by(ResponseUpdate.created_at.desc())
            )
        ).scalars()
    )

    update_ids = [u.id for u in updates]
    attachments = (
        list(
            (
                await session.execute(
                    select(ResponseAttachment).where(ResponseAttachment.update_id.in_(update_ids))
                )
            ).scalars()
        )
        if update_ids
        else []
    )
    attachments_by_update: dict[UUID, list[dict[str, Any]]] = {}
    for att in attachments:
        attachments_by_update.setdefault(att.update_id, []).append(
            {
                "id": str(att.id),
                "original_filename": att.original_filename,
                "content_type": att.content_type,
                "size_bytes": att.size_bytes,
                "download_url": f"/api/v1/response-attachments/{att.id}/download",
                "created_at": att.created_at,
            }
        )

    report = (
        await session.execute(
            select(ReportRun)
            .where(ReportRun.mission_id == case.mission_id)
            .order_by(ReportRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    audit_rows = list(
        (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.entity_id.in_([str(case.id), str(case.mission_id)]))
                .order_by(AuditEvent.occurred_at.desc())
            )
        ).scalars()
    )

    # Determine deterministic next action
    if case.status == "triage":
        if not case.acknowledged_at:
            next_action = {
                "stage": "Verify",
                "action": "acknowledge",
                "label": "Acknowledge alert and review evidence",
                "description": (
                    "Confirm the signal was received and inspect whether it represents "
                    "a forecast or observation."
                ),
            }
        else:
            next_action = {
                "stage": "Route",
                "action": "route",
                "label": "Attach verified route in Route Planner",
                "description": (
                    "Calculate and attach a real terrain-safe route before "
                    "starting field response."
                ),
            }
    elif case.status == "ready":
        next_action = {
            "stage": "Respond",
            "action": "start",
            "label": "Start response mission",
            "description": (
                "Alert acknowledged and route attached. Start the operational field response."
            ),
        }
    elif case.status == "responding":
        next_action = {
            "stage": "Respond",
            "action": "complete",
            "label": "Complete response mission",
            "description": (
                "Field movement is finished. Complete the mission to trigger automatic "
                "evidence report compilation."
            ),
        }
    elif case.status == "review":
        if not report or report.status in {"queued", "processing"}:
            next_action = {
                "stage": "Prove",
                "action": "waiting_report",
                "label": "Evidence report is generating...",
                "description": "Worker is compiling verified PDF and JSON receipts.",
            }
        elif report.status == "failed":
            next_action = {
                "stage": "Prove",
                "action": "retry_report",
                "label": "Retry report generation",
                "description": (
                    "Evidence generation encountered an issue. Re-queue compiling report."
                ),
            }
        else:
            next_action = {
                "stage": "Prove",
                "action": "close",
                "label": "Close episode with resolution notes",
                "description": (
                    "Evidence package is ready. Enter resolution notes to seal "
                    "the operational response."
                ),
            }
    elif case.status == "closed":
        next_action = {
            "stage": "Prove",
            "action": "none",
            "label": "Episode closed",
            "description": f"Resolution: {case.resolution_notes or 'Closed successfully.'}",
        }
    else:
        next_action = {
            "stage": "Verify",
            "action": "none",
            "label": "Episode dismissed",
            "description": f"Dismissal reason: {case.dismissal_reason or 'No reason provided.'}",
        }

    summary = _response_case_summary(
        case,
        rule_name=rule.name if rule else None,
        mission_title=mission.title if mission else None,
        mission_status=mission.status if mission else None,
        alert_count=len(alerts),
        update_count=len(updates),
        route_run_id=str(mission.route_run_id) if mission and mission.route_run_id else None,
    )

    return {
        **summary,
        "case": summary,
        "rule": _alert_rule(rule) if rule else None,
        "mission": _mission(mission, response_case_id=str(case.id)) if mission else None,
        "route": {
            "id": str(route.id),
            "name": route.name or f"Route {str(route.id)[:8]}",
            "total_distance_m": route.total_distance_m,
            "estimated_time_s": route.total_time_s,
            "geojson": route.geojson,
            "profile": route.parameters.get("profile", "resource_aware"),
        }
        if route
        else None,
        "alerts": [
            {
                "id": str(a.id),
                "kind": a.kind,
                "title": a.title,
                "message": a.message,
                "severity": a.severity,
                "payload": a.payload,
                "is_forecast": a.kind == "forecast_threshold",
                "created_at": a.created_at,
                "acknowledged_at": a.acknowledged_at,
            }
            for a in alerts
        ],
        "updates": [
            {
                "id": str(u.id),
                "author_user_id": str(u.author_user_id),
                "notes": u.notes,
                "latitude": to_shape(u.geom).y if u.geom else None,
                "longitude": to_shape(u.geom).x if u.geom else None,
                "created_at": u.created_at,
                "attachments": attachments_by_update.get(u.id, []),
            }
            for u in updates
        ],
        "report": {
            "id": str(report.id),
            "status": report.status,
            "created_at": report.created_at,
            "completed_at": report.completed_at,
            "error_message": report.error_message,
            "downloads": {
                "pdf": f"/api/v1/reports/{report.id}/download/pdf"
                if report.status == "ready"
                else None,
                "json": f"/api/v1/reports/{report.id}/download/json"
                if report.status == "ready"
                else None,
            },
        }
        if report
        else None,
        "timeline": [
            {
                "id": str(ev.id),
                "action": ev.action,
                "entity_type": ev.entity_type,
                "entity_id": ev.entity_id,
                "details": ev.details,
                "occurred_at": ev.occurred_at,
            }
            for ev in audit_rows
        ],
        "next_action": next_action,
    }


@router.post("/response-cases/{case_id}/acknowledge")
async def acknowledge_response_case(
    case_id: UUID,
    request: ResponseCaseAcknowledge,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    if case.status not in {"triage"}:
        raise APIError(
            "INVALID_TRANSITION",
            f"Case in status '{case.status}' cannot be acknowledged.",
            status_code=409,
        )
    if request.revision != case.revision:
        raise APIError(
            "REVISION_CONFLICT",
            "The response case was modified by another session. Refresh before saving.",
            status_code=409,
            details={"current_revision": case.revision},
        )

    now = datetime.now(UTC)
    case.acknowledged_at = now
    # Acknowledge all alerts attached to this case
    await session.execute(
        select(Alert).where(Alert.response_case_id == case.id)
    )
    linked_alerts = list(
        (
            await session.execute(
                select(Alert).where(Alert.response_case_id == case.id)
            )
        ).scalars()
    )
    for a in linked_alerts:
        if not a.acknowledged_at:
            a.acknowledged_at = now

    mission = await session.get(Mission, case.mission_id)
    if mission and mission.route_run_id:
        case.status = "ready"

    case.revision += 1
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="response_case.acknowledged",
            entity_type="response_case",
            entity_id=str(case.id),
            details={"status": case.status, "revision": case.revision},
        )
    )
    await session.commit()
    await session.refresh(case)
    return {"id": str(case.id), "status": case.status, "revision": case.revision}


@router.post("/response-cases/{case_id}/route")
async def attach_response_case_route(
    case_id: UUID,
    request: ResponseCaseRoute,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    if case.status not in {"triage", "ready"}:
        raise APIError(
            "INVALID_TRANSITION",
            f"Route cannot be attached while case is in status '{case.status}'.",
            status_code=409,
        )
    if request.revision != case.revision:
        raise APIError(
            "REVISION_CONFLICT",
            "The response case was modified by another session. Refresh before saving.",
            status_code=409,
            details={"current_revision": case.revision},
        )

    route = await session.get(RouteRun, request.route_id)
    if (
        route is None
        or route.owner_user_id != profile.auth_user_id
        or route.pilot_slug != case.pilot_slug
    ):
        raise APIError("OWNERSHIP_REQUIRED", "The selected route is unavailable.", status_code=422)

    mission = await session.get(Mission, case.mission_id)
    if mission is None:
        raise APIError("MISSION_NOT_FOUND", "Associated mission not found.", status_code=404)

    mission.route_run_id = route.id
    mission.revision += 1

    if case.acknowledged_at:
        case.status = "ready"

    case.revision += 1
    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="response_case.route_attached",
            entity_type="response_case",
            entity_id=str(case.id),
            details={
                "route_id": str(route.id),
                "status": case.status,
                "revision": case.revision,
            },
        )
    )
    await session.commit()
    await session.refresh(case)
    return {
        "id": str(case.id),
        "status": case.status,
        "route_id": str(route.id),
        "revision": case.revision,
    }


@router.post("/response-cases/{case_id}/start")
async def start_response_case(
    case_id: UUID,
    request: ResponseCaseStart,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    if request.revision != case.revision:
        raise APIError(
            "REVISION_CONFLICT",
            "The response case was modified by another session. Refresh before saving.",
            status_code=409,
            details={"current_revision": case.revision},
        )

    mission = await session.get(Mission, case.mission_id)
    if not mission or not mission.route_run_id or not case.acknowledged_at:
        raise APIError(
            "CANNOT_START_WITHOUT_ROUTE_AND_ACK",
            "A response mission cannot be started without route assignment and acknowledgment.",
            status_code=409,
        )
    if case.status != "ready":
        raise APIError(
            "INVALID_TRANSITION",
            f"Case in status '{case.status}' cannot be started.",
            status_code=409,
        )

    now = datetime.now(UTC)
    case.status = "responding"
    case.started_at = now
    case.revision += 1

    mission.status = "active"
    mission.started_at = now
    mission.revision += 1

    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="response_case.started",
            entity_type="response_case",
            entity_id=str(case.id),
            details={"status": case.status, "mission_id": str(mission.id)},
        )
    )
    await session.commit()
    await session.refresh(case)
    return {"id": str(case.id), "status": case.status, "revision": case.revision}


@router.post("/response-cases/{case_id}/complete")
async def complete_response_case(
    case_id: UUID,
    request: ResponseCaseComplete,
    profile: ProfileDependency,
    session: SessionDependency,
    settings: SettingsDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    if request.revision != case.revision:
        raise APIError(
            "REVISION_CONFLICT",
            "The response case was modified by another session. Refresh before saving.",
            status_code=409,
            details={"current_revision": case.revision},
        )
    if case.status != "responding":
        raise APIError(
            "INVALID_TRANSITION",
            f"Case in status '{case.status}' cannot be completed.",
            status_code=409,
        )

    now = datetime.now(UTC)
    case.status = "review"
    case.completed_at = now
    case.revision += 1

    mission = await session.get(Mission, case.mission_id)
    if mission:
        mission.status = "completed"
        mission.completed_at = now
        mission.revision += 1

    # Idempotent report generation
    report = (
        await session.execute(
            select(ReportRun)
            .where(ReportRun.mission_id == case.mission_id)
            .order_by(ReportRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if report is None:
        report = ReportRun(
            pilot_slug=case.pilot_slug,
            owner_user_id=case.owner_user_id,
            mission_id=case.mission_id,
            status="queued",
            parameters={"title": f"Evidence: {mission.title if mission else 'Response mission'}"},
        )
        session.add(report)
        await session.flush()
        dispatch_report(str(report.id))

    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="response_case.completed",
            entity_type="response_case",
            entity_id=str(case.id),
            details={"status": case.status, "report_id": str(report.id)},
        )
    )
    await session.commit()
    await session.refresh(case)
    return {
        "id": str(case.id),
        "status": case.status,
        "report_id": str(report.id),
        "revision": case.revision,
    }


@router.post("/response-cases/{case_id}/close")
async def close_response_case(
    case_id: UUID,
    request: ResponseCaseClose,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    if request.revision != case.revision:
        raise APIError(
            "REVISION_CONFLICT",
            "The response case was modified by another session. Refresh before saving.",
            status_code=409,
            details={"current_revision": case.revision},
        )
    if case.status != "review":
        raise APIError(
            "INVALID_TRANSITION",
            f"Case in status '{case.status}' cannot be closed.",
            status_code=409,
        )

    notes = request.resolution_notes.strip()
    if not notes:
        raise APIError(
            "RESOLUTION_NOTES_REQUIRED", "Resolution notes are required.", status_code=422
        )

    # Verify that evidence report is ready
    report = (
        await session.execute(
            select(ReportRun)
            .where(ReportRun.mission_id == case.mission_id)
            .order_by(ReportRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if not report or report.status != "ready":
        raise APIError(
            "REPORT_NOT_READY",
            "Episode can only be closed once the evidence package report is ready.",
            status_code=409,
        )

    now = datetime.now(UTC)
    case.status = "closed"
    case.closed_at = now
    case.resolution_notes = notes
    case.revision += 1

    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="response_case.closed",
            entity_type="response_case",
            entity_id=str(case.id),
            details={"resolution_notes": notes, "report_id": str(report.id)},
        )
    )
    await session.commit()
    await session.refresh(case)
    return {"id": str(case.id), "status": case.status, "revision": case.revision}


@router.post("/response-cases/{case_id}/dismiss")
async def dismiss_response_case(
    case_id: UUID,
    request: ResponseCaseDismiss,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    if request.revision != case.revision:
        raise APIError(
            "REVISION_CONFLICT",
            "The response case was modified by another session. Refresh before saving.",
            status_code=409,
            details={"current_revision": case.revision},
        )
    if case.status == "closed":
        raise APIError(
            "CANNOT_DISMISS_CLOSED", "Closed episodes cannot be dismissed.", status_code=409
        )

    reason = request.reason.strip()
    if not reason:
        raise APIError(
            "DISMISSAL_REASON_REQUIRED", "Dismissal reason is required.", status_code=422
        )

    now = datetime.now(UTC)
    case.status = "dismissed"
    case.dismissed_at = now
    case.dismissal_reason = reason
    case.revision += 1

    mission = await session.get(Mission, case.mission_id)
    if mission and mission.status not in {"completed", "cancelled"}:
        mission.status = "cancelled"
        mission.revision += 1

    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="response_case.dismissed",
            entity_type="response_case",
            entity_id=str(case.id),
            details={"reason": reason},
        )
    )
    await session.commit()
    await session.refresh(case)
    return {"id": str(case.id), "status": case.status, "revision": case.revision}


@router.post("/response-cases/{case_id}/updates")
async def create_response_update(
    case_id: UUID,
    request: ResponseUpdateCreate,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    if case.status in {"closed", "dismissed"}:
        raise APIError(
            "CASE_TERMINATED",
            "Updates cannot be logged on closed or dismissed episodes.",
            status_code=409,
        )

    point = Point(request.longitude, request.latitude)
    if not pilot_definition.boundary.covers(point):
        raise APIError(
            "OUTSIDE_PILOT",
            "The GPS coordinates are outside the pilot boundary.",
            status_code=422,
        )

    update = ResponseUpdate(
        response_case_id=case.id,
        author_user_id=profile.auth_user_id,
        notes=request.notes.strip(),
        geom=from_shape(point, srid=4326),
    )
    session.add(update)
    await session.flush()

    session.add(
        AuditEvent(
            actor_user_id=profile.auth_user_id,
            action="response_update.created",
            entity_type="response_update",
            entity_id=str(update.id),
            details={"case_id": str(case.id), "notes": update.notes},
        )
    )
    await session.commit()
    await session.refresh(update)
    return {
        "id": str(update.id),
        "case_id": str(case.id),
        "notes": update.notes,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "created_at": update.created_at,
    }


@router.post("/response-updates/{update_id}/attachments")
async def upload_response_attachment(
    update_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    settings: SettingsDependency,
    file: UploadFile = File(),
) -> dict[str, Any]:
    update = await session.get(ResponseUpdate, update_id)
    if update is None:
        raise APIError("UPDATE_NOT_FOUND", "Update not found.", status_code=404)
    case = await session.get(ResponseCase, update.response_case_id)
    if case is None or (case.owner_user_id != profile.auth_user_id and not profile.is_system_owner):
        raise APIError("OWNERSHIP_REQUIRED", "Access denied.", status_code=403)
    if case.status in {"closed", "dismissed"}:
        raise APIError(
            "CASE_TERMINATED",
            "Attachments cannot be added to closed or dismissed episodes.",
            status_code=409,
        )

    count = (
        await session.execute(
            select(func.count())
            .select_from(ResponseAttachment)
            .where(ResponseAttachment.update_id == update.id)
        )
    ).scalar_one()
    if count >= 3:
        raise APIError(
            "ATTACHMENT_LIMIT",
            "An update can contain at most three photos.",
            status_code=422,
        )

    payload = await file.read()
    if len(payload) > 8 * 1024 * 1024:
        raise APIError("FILE_TOO_LARGE", "Photos are limited to 8 MB.", status_code=413)
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise APIError("UNSUPPORTED_MEDIA_TYPE", "Use JPEG, PNG or WebP photos.", status_code=415)

    try:
        image = Image.open(io.BytesIO(payload))
        image.thumbnail((2400, 2400))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        output = io.BytesIO()
        # Save stripping all metadata
        image.save(output, "WEBP", quality=88, method=6)
        normalized = output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise APIError(
            "INVALID_IMAGE", "The uploaded photo cannot be decoded.", status_code=422
        ) from exc

    checksum = hashlib.sha256(normalized).hexdigest()
    object_key = f"{profile.auth_user_id}/{case.id}/{update.id}/{uuid.uuid4()}.webp"
    await ObjectStorage(settings).put(
        settings.response_evidence_bucket, object_key, normalized, "image/webp"
    )

    attachment = ResponseAttachment(
        update_id=update.id,
        object_key=object_key,
        original_filename=(file.filename or "response-photo")[:255],
        content_type="image/webp",
        size_bytes=len(normalized),
        checksum=checksum,
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return {
        "id": str(attachment.id),
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
    }


@router.get("/response-attachments/{attachment_id}/download")
async def download_response_attachment(
    attachment_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    settings: SettingsDependency,
) -> Any:
    attachment = await session.get(ResponseAttachment, attachment_id)
    if attachment is None:
        raise APIError("ATTACHMENT_NOT_FOUND", "Attachment not found.", status_code=404)
    update = await session.get(ResponseUpdate, attachment.update_id)
    if update is None:
        raise APIError("ATTACHMENT_NOT_FOUND", "Update not found.", status_code=404)
    case = await session.get(ResponseCase, update.response_case_id)
    if case is None or (case.owner_user_id != profile.auth_user_id and not profile.is_system_owner):
        raise APIError("OWNERSHIP_REQUIRED", "Access denied.", status_code=403)

    storage = ObjectStorage(settings)
    signed_url = await storage.signed_url(
        settings.response_evidence_bucket, attachment.object_key
    )
    if signed_url:
        return RedirectResponse(signed_url, status_code=307)
    path = storage.local_path(settings.response_evidence_bucket, attachment.object_key)
    if not path.exists():
        raise APIError("FILE_MISSING", "Attachment file not found on storage.", status_code=404)
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.original_filename,
    )


@router.post("/response-cases/{case_id}/report/retry")
async def retry_response_case_report(
    case_id: UUID,
    profile: ProfileDependency,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    case = await _owned_response_case(session, case_id, profile, pilot_definition.slug)
    report = (
        await session.execute(
            select(ReportRun)
            .where(ReportRun.mission_id == case.mission_id)
            .order_by(ReportRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if report is None:
        mission = await session.get(Mission, case.mission_id)
        report = ReportRun(
            pilot_slug=case.pilot_slug,
            owner_user_id=case.owner_user_id,
            mission_id=case.mission_id,
            status="queued",
            parameters={"title": f"Evidence: {mission.title if mission else 'Response mission'}"},
        )
        session.add(report)
        await session.flush()
    else:
        report.status = "queued"
        report.error_message = None

    dispatch_report(str(report.id))
    await session.commit()
    return {"report_id": str(report.id), "status": report.status}

