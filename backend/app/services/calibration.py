"""Calibration service for SolarShepherd.

Provides sample validation, template generation, satellite-ground matching,
regression candidate fitting, model activation gate, and GCH calculations.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import h3
from dateutil.parser import isoparse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import APIError
from app.models import AuditEvent, ModelVersion

REQUIRED_SAMPLE_FIELDS = (
    "sample_id",
    "sampled_at_with_timezone",
    "latitude",
    "longitude",
    "dry_matter_kg_ha",
    "method",
    "quadrat_area_m2",
)


@dataclass(frozen=True)
class ValidatedSample:
    sample_id: str
    sampled_at: datetime
    latitude: float
    longitude: float
    dry_matter_kg_ha: float
    method: str
    quadrat_area_m2: float


@dataclass(frozen=True)
class SampleValidation:
    checksum: str
    rows: list[ValidatedSample]
    errors: list[dict[str, Any]]

    @property
    def valid(self) -> bool:
        return not self.errors


def sample_template() -> str:
    return ",".join(REQUIRED_SAMPLE_FIELDS) + "\n"


def _add_error(errors: list[dict[str, Any]], row: int, field: str, message: str) -> None:
    errors.append({"row": row, "field": field, "message": message})


def validate_sample_csv(
    payload: bytes,
    pilot_lat: float,
    pilot_lon: float,
    pilot_radius_km: float,
) -> SampleValidation:
    checksum = hashlib.sha256(payload).hexdigest()
    errors: list[dict[str, Any]] = []
    rows: list[ValidatedSample] = []
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return SampleValidation(
            checksum,
            [],
            [{"row": 0, "field": "file", "message": "CSV must be UTF-8 encoded."}],
        )
    reader = csv.DictReader(io.StringIO(content))
    missing = [field for field in REQUIRED_SAMPLE_FIELDS if field not in (reader.fieldnames or [])]
    if missing:
        return SampleValidation(
            checksum,
            [],
            [
                {"row": 1, "field": field, "message": "Required column is missing."}
                for field in missing
            ],
        )
    seen: set[str] = set()
    for line, raw in enumerate(reader, start=2):
        row_errors: list[dict[str, Any]] = []

        sample_id = (raw.get("sample_id") or "").strip()
        if not sample_id:
            _add_error(row_errors, line, "sample_id", "A sample identifier is required.")
        elif sample_id in seen:
            _add_error(row_errors, line, "sample_id", "Duplicate sample_id in this file.")
        seen.add(sample_id)

        try:
            sampled_at = isoparse((raw.get("sampled_at_with_timezone") or "").strip())
            if sampled_at.tzinfo is None:
                _add_error(
                    row_errors,
                    line,
                    "sampled_at_with_timezone",
                    "An explicit UTC offset or timezone is required.",
                )
        except (TypeError, ValueError):
            sampled_at = datetime.min
            _add_error(
                row_errors,
                line,
                "sampled_at_with_timezone",
                "Use a valid ISO-8601 timestamp with timezone.",
            )

        parsed: dict[str, float] = {}
        for field in ("latitude", "longitude", "dry_matter_kg_ha", "quadrat_area_m2"):
            try:
                value = float(raw.get(field) or "")
                if not math.isfinite(value):
                    raise ValueError
                parsed[field] = value
            except ValueError:
                parsed[field] = 0.0
                _add_error(row_errors, line, field, "A finite numeric value is required.")
        latitude = parsed["latitude"]
        longitude = parsed["longitude"]
        if not -90 <= latitude <= 90:
            _add_error(row_errors, line, "latitude", "Latitude must be between -90 and 90.")
        if not -180 <= longitude <= 180:
            _add_error(row_errors, line, "longitude", "Longitude must be between -180 and 180.")
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            distance_km = h3.great_circle_distance(
                (pilot_lat, pilot_lon), (latitude, longitude), unit="km"
            )
            if distance_km > pilot_radius_km:
                _add_error(
                    row_errors,
                    line,
                    "latitude",
                    f"Sample is outside the {pilot_radius_km:g} km pilot area.",
                )
        if parsed["dry_matter_kg_ha"] <= 0:
            _add_error(
                row_errors,
                line,
                "dry_matter_kg_ha",
                "Dry matter must be greater than zero.",
            )
        if parsed["quadrat_area_m2"] <= 0:
            _add_error(
                row_errors,
                line,
                "quadrat_area_m2",
                "Quadrat area must be greater than zero.",
            )
        method = (raw.get("method") or "").strip()
        if not method:
            _add_error(row_errors, line, "method", "A documented sampling method is required.")

        errors.extend(row_errors)
        if not row_errors:
            rows.append(
                ValidatedSample(
                    sample_id=sample_id,
                    sampled_at=sampled_at,
                    latitude=latitude,
                    longitude=longitude,
                    dry_matter_kg_ha=parsed["dry_matter_kg_ha"],
                    method=method,
                    quadrat_area_m2=parsed["quadrat_area_m2"],
                )
            )
    if not rows and not errors:
        errors.append({"row": 1, "field": "file", "message": "CSV contains no sample rows."})
    return SampleValidation(checksum, rows, errors)


# ---------------------------------------------------------------------------
# Scientific Calibration Gate: Match -> Fit -> Validate -> Activate -> GCH
# ---------------------------------------------------------------------------


async def match_samples_with_satellite_data(
    session: AsyncSession,
    pilot_slug: str,
    window_days: int = 5,
) -> list[dict[str, Any]]:
    """Match ground calibration samples with nearest cloud-free satellite observations."""
    window_seconds = window_days * 86_400

    query = text(
        """
        SELECT s.id AS sample_id,
               s.external_sample_id,
               s.dry_matter_kg_ha,
               s.method,
               s.quadrat_area_m2,
               s.sampled_at,
               ST_X(s.geom) AS longitude,
               ST_Y(s.geom) AS latitude,
               c.h3_index,
               c.area_ha,
               obs.ndvi,
               obs.ndmi,
               obs.scene_id,
               obs.observed_at AS scene_acquired_at
        FROM calibration_samples AS s
        LEFT JOIN h3_cells AS c
          ON ST_Covers(c.geom, s.geom)
        LEFT JOIN LATERAL (
            SELECT o.h3_index, o.ndvi, o.ndmi, o.scene_id, o.observed_at
            FROM cell_observations AS o
            JOIN satellite_scenes AS sc ON sc.id = o.scene_id
            WHERE o.h3_index = c.h3_index
              AND sc.processing_status = 'complete'
              AND o.ndvi IS NOT NULL
              AND ABS(EXTRACT(EPOCH FROM (o.observed_at - s.sampled_at))) <= :window_seconds
            ORDER BY ABS(EXTRACT(EPOCH FROM (o.observed_at - s.sampled_at))) ASC
            LIMIT 1
        ) AS obs ON true
        WHERE s.pilot_slug = :pilot_slug
        ORDER BY s.sampled_at DESC
        """
    )
    rows = (
        await session.execute(
            query,
            {"pilot_slug": pilot_slug, "window_seconds": window_seconds},
        )
    ).mappings().all()

    matched: list[dict[str, Any]] = []
    for r in rows:
        matched.append(
            {
                "sample_id": str(r["sample_id"]),
                "external_sample_id": r["external_sample_id"],
                "dry_matter_kg_ha": float(r["dry_matter_kg_ha"]),
                "method": r["method"],
                "quadrat_area_m2": float(r["quadrat_area_m2"]),
                "sampled_at": r["sampled_at"].isoformat() if r["sampled_at"] else None,
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
                "h3_index": r["h3_index"],
                "area_ha": float(r["area_ha"]) if r["area_ha"] else None,
                "ndvi": float(r["ndvi"]) if r["ndvi"] is not None else None,
                "ndmi": float(r["ndmi"]) if r["ndmi"] is not None else None,
                "scene_id": r["scene_id"],
                "scene_acquired_at": (
                    r["scene_acquired_at"].isoformat() if r["scene_acquired_at"] else None
                ),
                "is_matched": r["ndvi"] is not None and r["scene_id"] is not None,
            }
        )
    return matched


def _calculate_regression(
    x_vals: list[float], y_vals: list[float]
) -> tuple[float, float, dict[str, Any]]:
    """Compute linear least-squares regression metrics."""
    n = len(x_vals)
    if n < 2:
        raise APIError("INSUFFICIENT_DATA", "At least 2 data points required for regression.")

    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals, strict=False))
    denominator = sum((x - mean_x) ** 2 for x in x_vals)

    if abs(denominator) < 1e-12:
        slope = 0.0
        intercept = mean_y
    else:
        slope = numerator / denominator
        intercept = mean_y - slope * mean_x

    predictions = [slope * x + intercept for x in x_vals]
    ss_tot = sum((y - mean_y) ** 2 for y in y_vals)
    ss_res = sum((y - pred) ** 2 for y, pred in zip(y_vals, predictions, strict=False))

    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
    r2 = max(0.0, min(1.0, r2))
    rmse = math.sqrt(ss_res / n)
    mae = sum(abs(y - pred) for y, pred in zip(y_vals, predictions, strict=False)) / n

    metrics = {
        "r2": round(r2, 4),
        "rmse": round(rmse, 2),
        "mae": round(mae, 2),
        "n_samples": n,
        "min_ndvi": round(min(x_vals), 4),
        "max_ndvi": round(max(x_vals), 4),
        "min_dm": round(min(y_vals), 1),
        "max_dm": round(max(y_vals), 1),
    }
    return slope, intercept, metrics


async def fit_candidate_model(
    session: AsyncSession,
    pilot_slug: str,
    algorithm: str = "linear_ndvi",
    sample_ids: list[str] | None = None,
    notes: str | None = None,
    user_id: UUID | None = None,
) -> ModelVersion:
    """Fit an empirical regression candidate from matched ground samples."""
    matched = await match_samples_with_satellite_data(session, pilot_slug)
    usable = [m for m in matched if m["is_matched"] and m["ndvi"] is not None]

    if sample_ids:
        usable = [m for m in usable if m["sample_id"] in sample_ids]

    if len(usable) < 3:
        raise APIError(
            "INSUFFICIENT_SAMPLES",
            f"At least 3 scene-matched field samples are required to fit a candidate model. "
            f"Currently matched: {len(usable)}.",
            status_code=400,
        )

    x_vals = [m["ndvi"] for m in usable]
    y_vals = [m["dry_matter_kg_ha"] for m in usable]

    slope, intercept, metrics = _calculate_regression(x_vals, y_vals)

    # Count existing models for pilot to construct version string
    model_count = (
        await session.scalar(
            select(func.count(ModelVersion.id)).where(
                ModelVersion.pilot_slug == pilot_slug, ModelVersion.kind == "dry_matter"
            )
        )
        or 0
    )
    version = f"dm-{algorithm[:6]}-v{model_count + 1}"

    model = ModelVersion(
        pilot_slug=pilot_slug,
        kind="dry_matter",
        version=version,
        algorithm=algorithm,
        status="candidate",
        coefficients={"slope": round(slope, 2), "intercept": round(intercept, 2)},
        metrics=metrics,
        training_sample_ids=[m["sample_id"] for m in usable],
        notes=notes,
    )
    session.add(model)
    await session.flush()

    audit = AuditEvent(
        actor_user_id=user_id,
        action="model_candidate_trained",
        entity_type="model_version",
        entity_id=str(model.id),
        details={
            "pilot_slug": pilot_slug,
            "version": version,
            "algorithm": algorithm,
            "metrics": metrics,
            "n_samples": len(usable),
        },
    )
    session.add(audit)
    await session.commit()
    await session.refresh(model)
    return model


async def activate_model_version(
    session: AsyncSession,
    model_id: UUID,
    user_id: UUID,
    pilot_slug: str = "jkuat",
    notes: str | None = None,
) -> ModelVersion:
    """Activate a candidate model, deprecating previously active models."""
    model = await session.get(ModelVersion, model_id)
    if not model or model.pilot_slug != pilot_slug:
        raise APIError("MODEL_NOT_FOUND", "Calibration model not found.", status_code=404)

    if model.status == "active":
        return model

    # Deprecate currently active models for this pilot/kind
    current_active = list(
        (
            await session.execute(
                select(ModelVersion).where(
                    ModelVersion.pilot_slug == pilot_slug,
                    ModelVersion.kind == model.kind,
                    ModelVersion.status == "active",
                )
            )
        ).scalars()
    )
    for prev in current_active:
        prev.status = "deprecated"
        session.add(prev)

    model.status = "active"
    model.activated_at = datetime.now(UTC)
    model.activated_by_user_id = user_id
    if notes:
        model.notes = notes

    session.add(model)

    audit = AuditEvent(
        actor_user_id=user_id,
        action="model_version_activated",
        entity_type="model_version",
        entity_id=str(model.id),
        details={
            "pilot_slug": pilot_slug,
            "version": model.version,
            "algorithm": model.algorithm,
            "metrics": model.metrics,
            "coefficients": model.coefficients,
        },
    )
    session.add(audit)
    await session.commit()
    await session.refresh(model)
    return model


async def calculate_grazing_capacity(
    session: AsyncSession,
    pilot_slug: str,
    herd_tlu: float,
    utilization_factor: float = 0.40,
    selected_cell_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate quantitative Grazing Capacity Horizon (GCH) in days using the active model."""
    active_model = (
        await session.execute(
            select(ModelVersion)
            .where(
                ModelVersion.pilot_slug == pilot_slug,
                ModelVersion.kind == "dry_matter",
                ModelVersion.status == "active",
            )
            .order_by(ModelVersion.activated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if not active_model:
        raise APIError(
            "CALIBRATION_REQUIRED",
            "No active calibration model exists for this pilot. "
            "A local model must be trained and activated first.",
            status_code=400,
        )

    slope = float(active_model.coefficients.get("slope", 0))
    intercept = float(active_model.coefficients.get("intercept", 0))

    # Fetch latest observations for cells in pilot
    query = text(
        """
        SELECT c.h3_index, c.area_ha, o.ndvi
        FROM h3_cells AS c
        JOIN pilots AS p ON p.slug = :pilot_slug
        LEFT JOIN LATERAL (
            SELECT obs.ndvi
            FROM cell_observations AS obs
            WHERE obs.h3_index = c.h3_index
              AND obs.ndvi IS NOT NULL
            ORDER BY obs.observed_at DESC
            LIMIT 1
        ) AS o ON true
        WHERE ST_DWithin(
            c.centroid::geography,
            p.center::geography,
            p.radius_km * 1000
        )
        """
    )
    rows = (await session.execute(query, {"pilot_slug": pilot_slug})).mappings().all()

    if selected_cell_ids:
        rows = [r for r in rows if r["h3_index"] in selected_cell_ids]

    total_biomass_kg = 0.0
    usable_forage_kg = 0.0
    valid_cells = 0
    total_area_ha = 0.0

    for r in rows:
        ndvi = r["ndvi"]
        area_ha = float(r["area_ha"]) if r["area_ha"] else 0.5
        total_area_ha += area_ha
        if ndvi is not None:
            dm_ha = max(0.0, slope * float(ndvi) + intercept)
            cell_biomass = dm_ha * area_ha
            total_biomass_kg += cell_biomass
            usable_forage_kg += cell_biomass * utilization_factor
            valid_cells += 1

    daily_consumption_kg = herd_tlu * 6.25
    horizon_days = (
        round(usable_forage_kg / daily_consumption_kg, 1) if daily_consumption_kg > 0 else 0.0
    )
    mean_biomass_kg_ha = (
        round(total_biomass_kg / total_area_ha, 1) if total_area_ha > 0 else 0.0
    )

    return {
        "pilot_slug": pilot_slug,
        "model_version": active_model.version,
        "herd_tlu": herd_tlu,
        "utilization_factor": utilization_factor,
        "total_biomass_kg_dm": round(total_biomass_kg, 1),
        "usable_forage_kg_dm": round(usable_forage_kg, 1),
        "daily_consumption_kg_dm": round(daily_consumption_kg, 1),
        "grazing_horizon_days": horizon_days,
        "cell_count": len(rows),
        "mean_biomass_kg_ha": mean_biomass_kg_ha,
        "calculated_at": datetime.now(UTC),
    }
