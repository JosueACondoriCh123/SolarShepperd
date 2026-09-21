from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID

from geoalchemy2.shape import to_shape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    Alert,
    ForecastRun,
    Mission,
    ReportRun,
    ResponseCase,
    ResponseUpdate,
    RouteRun,
    SampleSubmission,
    SatelliteScene,
    TelemetryObservation,
)
from app.pilots import get_pilot
from app.services.object_storage import ObjectStorage


async def build_report(session: AsyncSession, settings: Settings, report_id: UUID) -> None:
    report = await session.get(ReportRun, report_id)
    if report is None:
        return
    report.status = "processing"
    await session.commit()
    try:
        mission = await session.get(Mission, report.mission_id)
        if mission is None:
            raise ValueError("Mission no longer exists")
        route = await session.get(RouteRun, mission.route_run_id) if mission.route_run_id else None
        pilot = get_pilot(report.pilot_slug)
        if pilot is None:
            raise ValueError("Report pilot is no longer configured")
        scene = (
            await session.execute(
                select(SatelliteScene)
                .where(
                    SatelliteScene.processing_status == "complete",
                    func.ST_Intersects(
                        SatelliteScene.footprint,
                        func.ST_GeomFromText(pilot.boundary.wkt, 4326),
                    ),
                )
                .order_by(SatelliteScene.acquired_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        forecast = (
            await session.execute(
                select(ForecastRun)
                .where(ForecastRun.pilot_slug == report.pilot_slug)
                .order_by(ForecastRun.fetched_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        telemetry_at = (
            await session.execute(
                select(func.max(TelemetryObservation.observed_at)).where(
                    TelemetryObservation.pilot_slug == report.pilot_slug
                )
            )
        ).scalar_one_or_none()
        sample_statement = select(SampleSubmission).where(
            SampleSubmission.owner_user_id == report.owner_user_id,
            SampleSubmission.pilot_slug == report.pilot_slug,
            SampleSubmission.status == "approved",
        )
        if mission.scheduled_start:
            sample_statement = sample_statement.where(
                SampleSubmission.sampled_at >= mission.scheduled_start
            )
        if mission.scheduled_end:
            sample_statement = sample_statement.where(
                SampleSubmission.sampled_at <= mission.scheduled_end
            )
        samples = list((await session.execute(sample_statement)).scalars())

        # Inspect if mission belongs to a ResponseCase
        response_case = (
            await session.execute(
                select(ResponseCase).where(ResponseCase.mission_id == mission.id).limit(1)
            )
        ).scalar_one_or_none()
        response_case_data = None
        if response_case:
            alert_rows = list(
                (
                    await session.execute(
                        select(Alert)
                        .where(Alert.response_case_id == response_case.id)
                        .order_by(Alert.created_at)
                    )
                ).scalars()
            )
            update_rows = list(
                (
                    await session.execute(
                        select(ResponseUpdate)
                        .where(ResponseUpdate.response_case_id == response_case.id)
                        .order_by(ResponseUpdate.created_at)
                    )
                ).scalars()
            )
            response_case_data = {
                "id": str(response_case.id),
                "status": response_case.status,
                "severity": response_case.severity,
                "resolution_notes": response_case.resolution_notes,
                "dismissal_reason": response_case.dismissal_reason,
                "acknowledged_at": response_case.acknowledged_at.isoformat()
                if response_case.acknowledged_at
                else None,
                "started_at": response_case.started_at.isoformat()
                if response_case.started_at
                else None,
                "completed_at": response_case.completed_at.isoformat()
                if response_case.completed_at
                else None,
                "closed_at": response_case.closed_at.isoformat()
                if response_case.closed_at
                else None,
                "originating_alerts": [
                    {
                        "id": str(a.id),
                        "kind": a.kind,
                        "title": a.title,
                        "message": a.message,
                        "severity": a.severity,
                        "is_forecast": a.kind == "forecast_threshold",
                        "created_at": a.created_at.isoformat(),
                    }
                    for a in alert_rows
                ],
                "updates": [
                    {
                        "id": str(u.id),
                        "notes": u.notes,
                        "latitude": to_shape(u.geom).y if u.geom else None,
                        "longitude": to_shape(u.geom).x if u.geom else None,
                        "created_at": u.created_at.isoformat(),
                    }
                    for u in update_rows
                ],
            }

        manifest: dict[str, Any] = {
            "schema_version": "solarshepherd-mission-evidence-v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "pilot": {
                "slug": pilot.slug,
                "name": pilot.name,
                "radius_km": pilot.radius_km,
            },
            "mission": {
                "id": str(mission.id),
                "title": mission.title,
                "status": mission.status,
                "scheduled_start": mission.scheduled_start.isoformat()
                if mission.scheduled_start
                else None,
                "scheduled_end": mission.scheduled_end.isoformat()
                if mission.scheduled_end
                else None,
                "herd_tlu_recorded_not_applied": mission.herd_tlu,
            },
            "route": {
                "id": str(route.id) if route else None,
                "distance_m": route.total_distance_m if route else None,
                "estimated_time_s": route.total_time_s if route else None,
                "diagnostics": route.diagnostics if route else {},
            },
            "sources": {
                "telemetry_latest_at": telemetry_at.isoformat() if telemetry_at else None,
                "forecast_run_id": str(forecast.id) if forecast else None,
                "forecast_generated_at": forecast.generated_at.isoformat() if forecast else None,
                "sentinel_scene_id": scene.id if scene else None,
                "sentinel_acquired_at": scene.acquired_at.isoformat() if scene else None,
            },
            "approved_samples": [
                {
                    "sample_code": sample.sample_code,
                    "sampled_at": sample.sampled_at.isoformat(),
                    "dry_matter_kg_ha": sample.dry_matter_kg_ha,
                    "method": sample.method,
                    "quadrat_area_m2": sample.quadrat_area_m2,
                }
                for sample in samples
            ],
            "response_case": response_case_data,
            "scientific_guardrails": {
                "biomass": "CALIBRATION_REQUIRED",
                "gch": "CALIBRATION_REQUIRED",
                "forecast_used_in_route_cost": False,
            },
        }
        pdf_bytes = _render_pdf(manifest)
        json_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        base_key = f"{report.owner_user_id}/{report.id}"
        storage = ObjectStorage(settings)
        await storage.put(settings.reports_bucket, f"{base_key}.pdf", pdf_bytes, "application/pdf")
        await storage.put(
            settings.reports_bucket, f"{base_key}.json", json_bytes, "application/json"
        )
        report.evidence_manifest = manifest
        report.pdf_object_key = f"{base_key}.pdf"
        report.json_object_key = f"{base_key}.json"
        report.status = "ready"
        report.completed_at = datetime.now(UTC)
        report.error_message = None
        await session.commit()
    except Exception as exc:
        report.status = "failed"
        report.error_message = str(exc)[:2000]
        await session.commit()
        raise


def _render_pdf(manifest: dict[str, Any]) -> bytes:
    target = BytesIO()
    document = SimpleDocTemplate(target, pagesize=A4, title="SolarShepherd mission evidence")
    styles = getSampleStyleSheet()
    mission = manifest["mission"]
    route = manifest["route"]
    sources = manifest["sources"]
    approved_samples = manifest.get("approved_samples", [])

    route_dist_km = (route["distance_m"] / 1000.0) if route.get("distance_m") else 0.0
    route_time_min = (route["estimated_time_s"] / 60.0) if route.get("estimated_time_s") else 0.0

    story = [
        Paragraph("SolarShepherd — Mission Evidence", styles["Title"]),
        Paragraph(str(mission["title"]), styles["Heading2"]),
        Spacer(1, 10),
        Table(
            [
                ["Mission status", mission["status"].upper()],
                ["Scheduled start", mission["scheduled_start"] or "Not scheduled"],
                ["Scheduled end", mission["scheduled_end"] or "Not scheduled"],
                ["Route distance", f"{route_dist_km:.2f} km ({route['distance_m'] or 0:.0f} m)"],
                ["Estimated walk time", f"{route_time_min:.1f} min"],
                ["Approved samples attached", str(len(approved_samples))],
            ],
            colWidths=[160, 320],
        ),
        Spacer(1, 14),
        Paragraph("Evidence Provenance & Climate", styles["Heading2"]),
        Table(
            [
                [key.replace("_", " ").title(), value or "Unavailable"]
                for key, value in sources.items()
            ],
            colWidths=[160, 320],
        ),
        Spacer(1, 14),
        Paragraph("Approved Ground-Truth Field Samples", styles["Heading2"]),
    ]

    if approved_samples:
        sample_rows = [
            ["Code", "Sampled At", "Dry Matter", "Method", "Quadrat"],
        ]
        for s in approved_samples[:25]:
            date_str = str(s.get("sampled_at", ""))[:16].replace("T", " ")
            sample_rows.append(
                [
                    str(s.get("sample_code", "")),
                    date_str,
                    f"{s.get('dry_matter_kg_ha', 0):.1f} kg/ha",
                    str(s.get("method", ""))[:20],
                    f"{s.get('quadrat_area_m2', 0):.2f} m²",
                ]
            )
        story.append(
            Table(
                sample_rows,
                colWidths=[90, 110, 100, 110, 70],
            )
        )
    else:
        story.append(
            Paragraph(
                "No approved field samples linked to this mission yet. "
                "Ground-truth samples remain required for future calibration.",
                styles["Italic"],
            )
        )

    resp_case = manifest.get("response_case")
    if resp_case:
        story.extend(
            [
                Spacer(1, 14),
                Paragraph("Response Center Episode", styles["Heading2"]),
                Table(
                    [
                        ["Episode ID", str(resp_case.get("id", ""))[:18] + "..."],
                        ["Episode status", str(resp_case.get("status", "")).upper()],
                        ["Severity", str(resp_case.get("severity", "")).upper()],
                        ["Acknowledged at", resp_case.get("acknowledged_at") or "Pending"],
                        ["Started at", resp_case.get("started_at") or "Pending"],
                        ["Completed at", resp_case.get("completed_at") or "Pending"],
                        ["Resolution notes", resp_case.get("resolution_notes") or "Open"],
                    ],
                    colWidths=[160, 320],
                ),
            ]
        )
        originating_alerts = resp_case.get("originating_alerts", [])
        if originating_alerts:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Originating Alert Signals", styles["Heading3"]))
            alert_rows = [["Signal Title", "Type", "Severity", "Triggered At"]]
            for a in originating_alerts[:10]:
                type_label = (
                    "FORECAST (Advisory)" if a.get("is_forecast") else "OBSERVATION (Real)"
                )
                alert_rows.append(
                    [
                        str(a.get("title", ""))[:28],
                        type_label,
                        str(a.get("severity", "")).upper(),
                        str(a.get("created_at", ""))[:16].replace("T", " "),
                    ]
                )
            story.append(Table(alert_rows, colWidths=[160, 130, 80, 110]))

        updates = resp_case.get("updates", [])
        if updates:
            story.append(Spacer(1, 8))
            story.append(Paragraph("Response Field Updates", styles["Heading3"]))
            update_rows = [["Notes", "Coordinates", "Timestamp"]]
            for u in updates[:15]:
                lat = u.get("latitude")
                lon = u.get("longitude")
                coords = f"{lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else "N/A"
                update_rows.append(
                    [
                        str(u.get("notes", ""))[:45],
                        coords,
                        str(u.get("created_at", ""))[:16].replace("T", " "),
                    ]
                )
            story.append(Table(update_rows, colWidths=[240, 120, 120]))

    story.extend(
        [
            Spacer(1, 14),
            Paragraph("Scientific Guardrails & Limitations", styles["Heading2"]),
            Paragraph(
                "Biomass and grazing carrying horizon (GCH) remain strictly "
                "CALIBRATION_REQUIRED. Weather forecasts are advisory and never "
                "incorporated into route cost calculations.",
                styles["BodyText"],
            ),
        ]
    )

    for item in story:
        if isinstance(item, Table):
            item.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8c95c")),
                        ("FONTNAME", (0, 0), (-1, -1), "Courier"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
    document.build(story)
    return target.getvalue()
