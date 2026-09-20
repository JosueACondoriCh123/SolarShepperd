from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from geoalchemy2.shape import from_shape
from pyproj import Geod
from shapely.geometry import Point, mapping
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    OwnerDependency,
    PrincipalDependency,
    ProfileDependency,
    ensure_profile_record,
    require_api_access,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.domain.gpx import route_to_gpx
from app.errors import APIError
from app.integrations.satellite import public_scene_tilejson_url
from app.models import (
    CalibrationImport,
    CalibrationSample,
    ForecastPoint,
    ForecastRun,
    IngestionRun,
    ModelVersion,
    RouteRun,
    SatelliteScene,
    SystemState,
    TelemetryObservation,
)
from app.pilots import PILOTS, PilotDefinition, get_pilot
from app.schemas import (
    CalibrationStatus,
    ForecastPointResponse,
    ForecastResponse,
    IngestionRunResponse,
    Measurement,
    RouteRequest,
    RouteResponse,
    TelemetryResponse,
)
from app.services.calibration import sample_template, validate_sample_csv
from app.services.routing import RoutingService
from app.tasks.jobs import dispatch_ingestion

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_access)])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
GEOD = Geod(ellps="WGS84")


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


def _station_distance_m(pilot: PilotDefinition, longitude: float, latitude: float) -> float:
    _, _, distance = GEOD.inv(pilot.longitude, pilot.latitude, longitude, latitude)
    return float(distance)


@router.get("/pilots")
async def pilots(session: SessionDependency) -> dict[str, Any]:
    data = []
    now = datetime.now(UTC)
    for pilot in PILOTS:
        latest = (
            await session.execute(
                select(func.max(TelemetryObservation.observed_at)).where(
                    TelemetryObservation.pilot_slug == pilot.slug
                )
            )
        ).scalar_one_or_none()
        if latest is None:
            observation_status = "never_run"
        else:
            age = now - latest.astimezone(UTC)
            observation_status = "healthy" if age <= timedelta(hours=3) else "stale"
            if age > timedelta(hours=24):
                observation_status = "unavailable"
        data.append(
            {
                **pilot.public_dict(),
                "latest_observed_at": latest,
                "observation_status": observation_status,
            }
        )
    return {"data": data, "count": len(data), "default_pilot_slug": "jkuat"}


@router.get("/pilots/{pilot_slug}/context")
async def pilot_context(pilot_slug: str, session: SessionDependency) -> dict[str, Any]:
    pilot = _require_pilot(pilot_slug)
    latest_rows = (
        await session.execute(
            select(
                TelemetryObservation.station_id,
                func.max(TelemetryObservation.observed_at),
            )
            .where(TelemetryObservation.pilot_slug == pilot.slug)
            .group_by(TelemetryObservation.station_id)
        )
    ).all()
    latest_by_station = {station_id: observed_at for station_id, observed_at in latest_rows}
    station_features = []
    for station in pilot.stations:
        distance_m = _station_distance_m(pilot, station.longitude, station.latitude)
        station_features.append(
            {
                "type": "Feature",
                "id": station.station_id,
                "geometry": {
                    "type": "Point",
                    "coordinates": [station.longitude, station.latitude],
                },
                "properties": {
                    "station_id": station.station_id,
                    "name": station.name,
                    "source": station.source,
                    "role": station.role,
                    "distance_to_center_m": distance_m,
                    "outside_pilot": distance_m > pilot.radius_km * 1_000,
                    "latest_observed_at": latest_by_station.get(station.station_id),
                },
            }
        )
    water_rows = (
        await session.execute(
            text(
                """
                SELECT osm_id, name, feature_type, tags, fetched_at,
                       ST_AsGeoJSON(geom)::json AS geometry
                FROM water_points
                WHERE ST_DWithin(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                    :radius_m
                )
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)
                LIMIT 500
                """
            ),
            {
                "longitude": pilot.longitude,
                "latitude": pilot.latitude,
                "radius_m": pilot.radius_km * 1_000,
            },
        )
    ).mappings()
    water_features = [
        {
            "type": "Feature",
            "id": row["osm_id"],
            "geometry": row["geometry"],
            "properties": {
                "name": row["name"],
                "feature_type": row["feature_type"],
                "source": "OpenStreetMap / Overpass",
                "fetched_at": row["fetched_at"],
                "coverage_warning": "OpenStreetMap water-feature coverage may be incomplete.",
            },
        }
        for row in water_rows
    ]
    return {
        "pilot": pilot.public_dict(),
        "boundary": {
            "type": "Feature",
            "geometry": mapping(pilot.boundary),
            "properties": {"pilot_slug": pilot.slug, "radius_km": pilot.radius_km},
        },
        "stations": {"type": "FeatureCollection", "features": station_features},
        "water": {"type": "FeatureCollection", "features": water_features},
        "water_coverage_warning": "OpenStreetMap water-feature coverage may be incomplete.",
    }


@router.get("/pilots/{pilot_slug}/scenes/{scene_id}/tiles")
async def scene_tiles(
    pilot_slug: str, scene_id: str, session: SessionDependency
) -> dict[str, Any]:
    pilot = _require_pilot(pilot_slug)
    scene = await session.get(SatelliteScene, scene_id)
    if scene is None or scene.processing_status != "complete":
        raise APIError("SCENE_NOT_FOUND", "The requested scene is unavailable.", status_code=404)
    intersects = (
        await session.execute(
            select(
                func.ST_Intersects(
                    SatelliteScene.footprint,
                    func.ST_GeomFromText(pilot.boundary.wkt, 4326),
                )
            ).where(SatelliteScene.id == scene_id)
        )
    ).scalar_one_or_none()
    if intersects is not True:
        raise APIError(
            "SCENE_NOT_FOUND", "The requested scene does not cover this pilot.", status_code=404
        )
    return {
        "scene_id": scene.id,
        "pilot_slug": pilot.slug,
        "tilejson_url": public_scene_tilejson_url(scene.id),
        "source": scene.source,
        "acquired_at": scene.acquired_at,
        "attribution": "Sentinel-2 L2A via Microsoft Planetary Computer",
    }


@router.get("/telemetry", response_model=TelemetryResponse)
async def telemetry(
    session: SessionDependency,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    metric: str | None = None,
    station_id: str | None = None,
    bucket_minutes: int = Query(default=1, ge=1, le=1_440),
    pilot: str = Query(default="jkuat"),
) -> TelemetryResponse:
    pilot_definition = _require_pilot(pilot)
    end = to_time or datetime.now(UTC)
    start = from_time or end - timedelta(hours=24)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end < start:
        raise APIError("INVALID_TIME_RANGE", "'to' must be after 'from'.", status_code=422)
    if end - start > timedelta(days=90):
        raise APIError(
            "TIME_RANGE_TOO_LARGE", "Telemetry queries are limited to 90 days.", status_code=422
        )
    conditions = [
        TelemetryObservation.pilot_slug == pilot_definition.slug,
        TelemetryObservation.observed_at >= start,
        TelemetryObservation.observed_at <= end,
    ]
    if metric:
        conditions.append(TelemetryObservation.metric == metric)
    if station_id:
        conditions.append(TelemetryObservation.station_id == station_id)
    if bucket_minutes == 1:
        statement = select(TelemetryObservation).where(*conditions)
    else:
        bucket_index = func.floor(
            func.extract("epoch", TelemetryObservation.observed_at) / (bucket_minutes * 60)
        )
        ranked = (
            select(
                TelemetryObservation.id.label("observation_id"),
                func.row_number()
                .over(
                    partition_by=(
                        TelemetryObservation.metric,
                        TelemetryObservation.station_id,
                        TelemetryObservation.depth_cm,
                        bucket_index,
                    ),
                    order_by=TelemetryObservation.observed_at.desc(),
                )
                .label("bucket_rank"),
            )
            .where(*conditions)
            .subquery()
        )
        statement = (
            select(TelemetryObservation)
            .join(ranked, ranked.c.observation_id == TelemetryObservation.id)
            .where(ranked.c.bucket_rank == 1)
        )
    rows = (
        await session.execute(
            statement.order_by(TelemetryObservation.observed_at.asc()).limit(20_000)
        )
    ).scalars()
    data = [
        Measurement(
            metric=row.metric,
            value=row.value,
            unit=row.unit,
            observed_at=row.observed_at,
            source=row.source,
            quality_flags=[
                *row.quality_flags,
                *(["DOWNSAMPLED_LATEST_IN_BUCKET"] if bucket_minutes > 1 else []),
            ],
            model_version=row.model_version,
            station_id=row.station_id,
            depth_cm=row.depth_cm,
        )
        for row in rows
    ]
    return TelemetryResponse(data=data, count=len(data), from_time=start, to_time=end)


@router.get("/forecast", response_model=ForecastResponse)
async def forecast(
    session: SessionDependency,
    hours: int = Query(default=72, ge=1, le=168),
    pilot: str = Query(default="jkuat"),
) -> ForecastResponse:
    pilot_definition = _require_pilot(pilot)
    run = (
        await session.execute(
            select(ForecastRun)
            .where(
                ForecastRun.pilot_slug == pilot_definition.slug,
                ForecastRun.status == "success",
            )
            .order_by(ForecastRun.fetched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return ForecastResponse(
            run_id=None,
            source="Open-Meteo",
            model_version=None,
            generated_at=None,
            fetched_at=None,
            valid_from=None,
            valid_to=None,
            data=[],
            count=0,
            attribution="Weather data by Open-Meteo.com",
        )
    end = datetime.now(UTC) + timedelta(hours=hours)
    rows = (
        await session.execute(
            select(ForecastPoint)
            .where(
                ForecastPoint.forecast_run_id == run.id,
                ForecastPoint.valid_at <= end,
            )
            .order_by(ForecastPoint.valid_at.asc())
        )
    ).scalars()
    values = [
        ForecastPointResponse(
            valid_at=row.valid_at,
            temperature_c=row.temperature_c,
            relative_humidity_pct=row.relative_humidity_pct,
            precipitation_probability_pct=row.precipitation_probability_pct,
            precipitation_mm=row.precipitation_mm,
            uv_index=row.uv_index,
            wind_speed_m_s=row.wind_speed_m_s,
            wind_gust_m_s=row.wind_gust_m_s,
            et0_mm=row.et0_mm,
            quality_flags=row.quality_flags,
        )
        for row in rows
    ]
    return ForecastResponse(
        run_id=run.id,
        source="Open-Meteo",
        model_version=run.model,
        generated_at=run.generated_at,
        fetched_at=run.fetched_at,
        valid_from=values[0].valid_at if values else run.valid_from,
        valid_to=values[-1].valid_at if values else run.valid_to,
        data=values,
        count=len(values),
        attribution="Weather data by Open-Meteo.com (forecast, not observation)",
    )


@router.get("/scenes")
async def scenes(
    session: SessionDependency,
    limit: int = Query(default=20, ge=1, le=100),
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    values = (
        await session.execute(
            select(SatelliteScene)
            .where(
                func.ST_Intersects(
                    SatelliteScene.footprint,
                    func.ST_GeomFromText(pilot_definition.boundary.wkt, 4326),
                )
            )
            .order_by(SatelliteScene.acquired_at.desc())
            .limit(limit)
        )
    ).scalars()
    data = [
        {
            "id": scene.id,
            "source": scene.source,
            "collection": scene.collection,
            "acquired_at": scene.acquired_at,
            "cloud_cover_pct": scene.cloud_cover_pct,
            "processing_status": scene.processing_status,
            "valid_fraction": scene.valid_fraction,
            "assets": scene.assets,
        }
        for scene in values
    ]
    return {"data": data, "count": len(data)}


@router.get("/cells")
async def cells(
    session: SessionDependency,
    bbox: str = Query(description="minLon,minLat,maxLon,maxLat"),
    layer: Literal["ndvi", "ndmi", "elevation", "slope", "forage_proxy"] = "ndvi",
    observed_date: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=8_000, ge=1, le=10_000),
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    try:
        min_lon, min_lat, max_lon, max_lat = [float(value) for value in bbox.split(",")]
    except (TypeError, ValueError):
        raise APIError(
            "INVALID_BBOX", "bbox must contain minLon,minLat,maxLon,maxLat", status_code=422
        ) from None
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise APIError("INVALID_BBOX", "bbox coordinates are outside valid bounds", status_code=422)
    query = text(
        """
        SELECT c.h3_index,
               c.area_ha,
               c.elevation_m,
               c.slope_deg,
               c.water_distance_m,
               ST_AsGeoJSON(c.geom)::json AS geometry,
               latest.ndvi,
               latest.ndmi,
               latest.valid_fraction,
               latest.observed_at,
               latest.scene_id,
               latest.quality_flags,
               latest.model_version
        FROM h3_cells AS c
        LEFT JOIN LATERAL (
            SELECT o.ndvi, o.ndmi, o.valid_fraction, o.observed_at,
                   o.scene_id, o.quality_flags, o.model_version
            FROM cell_observations AS o
            WHERE o.h3_index = c.h3_index
              AND (
                  CAST(:observed_date AS date) IS NULL
                  OR o.observed_at::date <= CAST(:observed_date AS date)
              )
            ORDER BY o.observed_at DESC
            LIMIT 1
        ) AS latest ON true
        WHERE ST_Intersects(
            c.geom,
            ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
        )
          AND ST_DWithin(
              c.centroid::geography,
              ST_SetSRID(ST_MakePoint(:pilot_lon, :pilot_lat), 4326)::geography,
              :radius_m
          )
        LIMIT :limit
        """
    )
    rows = (
        await session.execute(
            query,
            {
                "observed_date": observed_date,
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "pilot_lon": pilot_definition.longitude,
                "pilot_lat": pilot_definition.latitude,
                "radius_m": pilot_definition.radius_km * 1_000,
                "limit": limit,
            },
        )
    ).mappings()

    def layer_value(row: Any) -> tuple[float | None, str, str | None]:
        if layer == "elevation":
            return row["elevation_m"], "m", "Copernicus DEM GLO-30"
        if layer == "slope":
            return row["slope_deg"], "degrees", "Copernicus DEM GLO-30"
        if layer == "forage_proxy":
            value = None if row["ndvi"] is None else max(0.0, min(1.0, (row["ndvi"] + 1) / 2))
            return value, "relative index", "Sentinel-2 NDVI proxy"
        return row[layer], "index", "Sentinel-2 L2A"

    features = []
    for row in rows:
        value, unit, source = layer_value(row)
        quality_flags = list(row["quality_flags"] or [])
        if layer == "forage_proxy" and value is not None:
            quality_flags.append("RELATIVE_PROXY_NOT_BIOMASS")
        features.append(
            {
                "type": "Feature",
                "id": row["h3_index"],
                "geometry": row["geometry"],
                "properties": {
                    "h3_index": row["h3_index"],
                    "value": value,
                    "unit": unit,
                    "observed_at": row["observed_at"],
                    "source": source,
                    "quality_flags": quality_flags,
                    "model_version": row["model_version"],
                    "valid_fraction": row["valid_fraction"],
                    "scene_id": row["scene_id"],
                    "area_ha": row["area_ha"],
                    "water_distance_m": row["water_distance_m"],
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {"layer": layer, "count": len(features), "biomass_calibrated": False},
    }


@router.get("/cells/change")
async def cell_change(
    session: SessionDependency,
    bbox: str = Query(description="minLon,minLat,maxLon,maxLat"),
    from_scene_id: str = Query(),
    to_scene_id: str = Query(),
    layer: Literal["ndvi", "ndmi"] = "ndvi",
    limit: int = Query(default=8_000, ge=1, le=10_000),
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    try:
        min_lon, min_lat, max_lon, max_lat = [float(value) for value in bbox.split(",")]
    except (TypeError, ValueError):
        raise APIError(
            "INVALID_BBOX", "bbox must contain minLon,minLat,maxLon,maxLat", status_code=422
        ) from None
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise APIError("INVALID_BBOX", "bbox coordinates are outside valid bounds", status_code=422)
    scenes_by_id = {
        scene.id: scene
        for scene in (
            await session.execute(
                select(SatelliteScene).where(SatelliteScene.id.in_([from_scene_id, to_scene_id]))
            )
        ).scalars()
    }
    if len(scenes_by_id) != 2:
        raise APIError("SCENE_NOT_FOUND", "Both comparison scenes must exist.", status_code=404)
    if scenes_by_id[from_scene_id].acquired_at >= scenes_by_id[to_scene_id].acquired_at:
        raise APIError(
            "INVALID_SCENE_ORDER",
            "from_scene_id must be older than to_scene_id.",
            status_code=422,
        )
    column = "ndvi" if layer == "ndvi" else "ndmi"
    query = text(
        f"""
        SELECT c.h3_index, c.area_ha, c.water_distance_m,
               ST_AsGeoJSON(c.geom)::json AS geometry,
               old.{column} AS from_value, recent.{column} AS to_value,
               old.valid_fraction AS from_valid_fraction,
               recent.valid_fraction AS to_valid_fraction,
               old.quality_flags AS from_flags,
               recent.quality_flags AS to_flags,
               recent.model_version
        FROM h3_cells AS c
        LEFT JOIN cell_observations AS old
          ON old.h3_index = c.h3_index AND old.scene_id = :from_scene_id
        LEFT JOIN cell_observations AS recent
          ON recent.h3_index = c.h3_index AND recent.scene_id = :to_scene_id
        WHERE ST_Intersects(
            c.geom,
            ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
        )
          AND ST_DWithin(
              c.centroid::geography,
              ST_SetSRID(ST_MakePoint(:pilot_lon, :pilot_lat), 4326)::geography,
              :radius_m
          )
        LIMIT :limit
        """
    )
    rows = (
        await session.execute(
            query,
            {
                "from_scene_id": from_scene_id,
                "to_scene_id": to_scene_id,
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "pilot_lon": pilot_definition.longitude,
                "pilot_lat": pilot_definition.latitude,
                "radius_m": pilot_definition.radius_km * 1_000,
                "limit": limit,
            },
        )
    ).mappings()
    features = []
    for row in rows:
        sufficient = (
            row["from_value"] is not None
            and row["to_value"] is not None
            and (row["from_valid_fraction"] or 0) >= 0.5
            and (row["to_valid_fraction"] or 0) >= 0.5
        )
        flags = sorted(set((row["from_flags"] or []) + (row["to_flags"] or [])))
        if not sufficient:
            flags.append("INSUFFICIENT_VALID_COVERAGE_FOR_CHANGE")
        delta = float(row["to_value"] - row["from_value"]) if sufficient else None
        features.append(
            {
                "type": "Feature",
                "id": row["h3_index"],
                "geometry": row["geometry"],
                "properties": {
                    "h3_index": row["h3_index"],
                    "value": delta,
                    "from_value": row["from_value"],
                    "to_value": row["to_value"],
                    "unit": "index difference",
                    "observed_at": scenes_by_id[to_scene_id].acquired_at,
                    "source": "Sentinel-2 L2A scene comparison",
                    "quality_flags": flags,
                    "model_version": row["model_version"],
                    "valid_fraction": min(
                        row["from_valid_fraction"] or 0,
                        row["to_valid_fraction"] or 0,
                    ),
                    "scene_id": to_scene_id,
                    "from_scene_id": from_scene_id,
                    "to_scene_id": to_scene_id,
                    "area_ha": row["area_ha"],
                    "water_distance_m": row["water_distance_m"],
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "layer": f"delta_{layer}",
            "count": len(features),
            "biomass_calibrated": False,
            "from_scene_id": from_scene_id,
            "to_scene_id": to_scene_id,
        },
    }


@router.get("/cells/{h3_index}")
async def cell_detail(
    h3_index: str,
    session: SessionDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT c.h3_index, c.area_ha, c.elevation_m, c.slope_deg,
                       c.water_distance_m, c.terrain_source, c.water_source,
                       ST_AsGeoJSON(c.geom)::json AS geometry,
                       o.ndvi, o.ndmi, o.valid_fraction, o.observed_at,
                       o.scene_id, o.quality_flags, o.model_version
                FROM h3_cells AS c
                LEFT JOIN LATERAL (
                    SELECT * FROM cell_observations
                    WHERE h3_index = c.h3_index
                    ORDER BY observed_at DESC LIMIT 1
                ) AS o ON true
                WHERE c.h3_index = :h3_index
                  AND ST_DWithin(
                      c.centroid::geography,
                      ST_SetSRID(ST_MakePoint(:pilot_lon, :pilot_lat), 4326)::geography,
                      :radius_m
                  )
                """
                ),
                {
                    "h3_index": h3_index,
                    "pilot_lon": pilot_definition.longitude,
                    "pilot_lat": pilot_definition.latitude,
                    "radius_m": pilot_definition.radius_km * 1_000,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise APIError("CELL_NOT_FOUND", "The requested H3 cell is not available.", status_code=404)
    return {
        **dict(row),
        "biomass_kg_dm_ha": None,
        "gch_days": None,
        "capacity_status": "CALIBRATION_REQUIRED",
    }


@router.post("/routes", response_model=RouteResponse, status_code=201)
async def create_route(
    request: RouteRequest,
    session: SessionDependency,
    settings: SettingsDependency,
    principal: PrincipalDependency,
    pilot: str = Query(default="jkuat"),
) -> RouteResponse:
    pilot_definition = _require_pilot(pilot)
    owner_user_id = None
    if not principal.is_guest:
        profile = await ensure_profile_record(principal, session, settings)
        owner_user_id = profile.auth_user_id
    return await RoutingService(
        session, settings.h3_resolution, pilot_slug=pilot_definition.slug
    ).calculate(
        request, owner_user_id=owner_user_id
    )


@router.get("/routes/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: UUID,
    session: SessionDependency,
    principal: PrincipalDependency,
    pilot: str = "jkuat",
) -> RouteResponse:
    pilot_definition = _require_pilot(pilot)
    route = await session.get(RouteRun, route_id)
    if (
        route is None
        or route.pilot_slug != pilot_definition.slug
        or route.status != "complete"
        or (
            route.owner_user_id
            and route.owner_user_id != principal.user_id
            and not principal.is_system_owner
        )
    ):
        raise APIError("ROUTE_NOT_FOUND", "The requested route was not found.", status_code=404)
    quality_flags = route.diagnostics.get("quality_flags", [])
    herd_received = route.parameters.get("herd_tlu") is not None
    return RouteResponse(
        id=route.id,
        status="complete",
        total_distance_m=route.total_distance_m or 0,
        estimated_time_s=route.total_time_s or 0,
        geojson=route.geojson or {"type": "FeatureCollection", "features": []},
        elevation_profile=route.elevation_profile,
        diagnostics=route.diagnostics,
        quality_flags=quality_flags,
        not_applied_parameters=["herd_tlu"] if herd_received else [],
        profile=route.parameters.get("profile", "resource_aware"),
    )


@router.get("/routes/{route_id}/gpx")
async def get_route_gpx(
    route_id: UUID,
    session: SessionDependency,
    profile: ProfileDependency,
    pilot: str = "jkuat",
) -> Response:
    pilot_definition = _require_pilot(pilot)
    route = await session.get(RouteRun, route_id)
    if (
        route is None
        or route.pilot_slug != pilot_definition.slug
        or not route.geojson
        or (
            route.owner_user_id
            and route.owner_user_id != profile.auth_user_id
            and not profile.is_system_owner
        )
    ):
        raise APIError("ROUTE_NOT_FOUND", "The requested route was not found.", status_code=404)
    line = next(
        (
            feature
            for feature in route.geojson.get("features", [])
            if feature.get("geometry", {}).get("type") == "LineString"
        ),
        None,
    )
    if line is None:
        raise APIError(
            "ROUTE_EXPORT_FAILED", "The route contains no line geometry.", status_code=500
        )
    elevations = [item.get("elevation_m") for item in route.elevation_profile]
    coordinates = [
        (float(point[0]), float(point[1]), elevations[index] if index < len(elevations) else None)
        for index, point in enumerate(line["geometry"]["coordinates"])
    ]
    payload = route_to_gpx(coordinates, f"SolarShepherd {route.id}")
    return Response(
        content=payload,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="solarshepherd-{route.id}.gpx"'},
    )


@router.get("/routes/{route_id}/evidence")
async def get_route_evidence(
    route_id: UUID,
    session: SessionDependency,
    profile: ProfileDependency,
    pilot: str = "jkuat",
) -> JSONResponse:
    pilot_definition = _require_pilot(pilot)
    route = await session.get(RouteRun, route_id)
    if (
        route is None
        or route.pilot_slug != pilot_definition.slug
        or route.status != "complete"
        or (
            route.owner_user_id
            and route.owner_user_id != profile.auth_user_id
            and not profile.is_system_owner
        )
    ):
        raise APIError("ROUTE_NOT_FOUND", "The requested route was not found.", status_code=404)
    payload = {
        "schema_version": "solarshepherd-route-evidence-v1",
        "route_id": str(route.id),
        "requested_at": route.requested_at.isoformat(),
        "parameters": route.parameters,
        "total_distance_m": route.total_distance_m,
        "estimated_time_s": route.total_time_s,
        "geometry": route.geojson,
        "elevation_profile": route.elevation_profile,
        "diagnostics": route.diagnostics,
        "quality_flags": route.diagnostics.get("quality_flags", []),
        "scientific_notice": (
            "Forecast data is advisory and was not used by this route. Biomass and "
            "carrying capacity were not calculated."
        ),
    }
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="solarshepherd-{route.id}-evidence.json"'
        },
    )


@router.get("/calibration/status", response_model=CalibrationStatus)
async def calibration_status(
    session: SessionDependency, pilot: str = Query(default="jkuat")
) -> CalibrationStatus:
    pilot_definition = _require_pilot(pilot)
    sample_count = (
        await session.execute(
            select(func.count())
            .select_from(CalibrationSample)
            .where(CalibrationSample.pilot_slug == pilot_definition.slug)
        )
    ).scalar_one()
    active_model = (
        await session.execute(
            select(ModelVersion)
            .where(ModelVersion.kind == "dry_matter", ModelVersion.status == "active")
            .order_by(ModelVersion.activated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ready = active_model is not None
    return CalibrationStatus(
        status="READY" if ready else "CALIBRATION_REQUIRED",
        sample_count=sample_count,
        active_model_version=active_model.version if active_model else None,
        required_fields=[
            "sample_id",
            "sampled_at_with_timezone",
            "latitude",
            "longitude",
            "dry_matter_kg_ha",
            "method",
            "quadrat_area_m2",
        ],
        message=(
            "A validated local dry-matter model is active."
            if ready
            else (
                "Biomass and grazing capacity remain locked until local field "
                "samples are validated."
            )
        ),
    )


@router.get("/calibration/samples/template.csv")
async def calibration_sample_template() -> Response:
    return Response(
        content=sample_template(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="solarshepherd-samples.csv"'},
    )


@router.get("/calibration/samples/coverage")
async def calibration_sample_coverage(
    session: SessionDependency, pilot: str = Query(default="jkuat")
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    rows = (
        await session.execute(
            text(
                """
                SELECT s.id, s.external_sample_id, s.sampled_at, s.dry_matter_kg_ha,
                       s.method, s.quadrat_area_m2,
                       ST_X(s.geom) AS longitude, ST_Y(s.geom) AS latitude,
                       nearest.id AS scene_id, nearest.acquired_at AS scene_acquired_at
                FROM calibration_samples AS s
                LEFT JOIN LATERAL (
                    SELECT sc.id, sc.acquired_at
                    FROM satellite_scenes AS sc
                    WHERE sc.processing_status = 'complete'
                      AND ABS(EXTRACT(EPOCH FROM (sc.acquired_at - s.sampled_at))) <= 432000
                    ORDER BY ABS(EXTRACT(EPOCH FROM (sc.acquired_at - s.sampled_at)))
                    LIMIT 1
                ) AS nearest ON true
                WHERE s.pilot_slug = :pilot_slug
                ORDER BY s.sampled_at DESC
                """
            ),
            {"pilot_slug": pilot_definition.slug},
        )
    ).mappings()
    features = [
        {
            "type": "Feature",
            "id": str(row["id"]),
            "geometry": {
                "type": "Point",
                "coordinates": [row["longitude"], row["latitude"]],
            },
            "properties": {
                "sample_id": row["external_sample_id"],
                "sampled_at": row["sampled_at"],
                "dry_matter_kg_ha": row["dry_matter_kg_ha"],
                "method": row["method"],
                "quadrat_area_m2": row["quadrat_area_m2"],
                "scene_id": row["scene_id"],
                "scene_acquired_at": row["scene_acquired_at"],
            },
        }
        for row in rows
    ]
    matched = sum(1 for feature in features if feature["properties"]["scene_id"])
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "sample_count": len(features),
            "scene_matched_count": matched,
            "unmatched_count": len(features) - matched,
            "match_window_days": 5,
            "model_activation": "CALIBRATION_REQUIRED",
        },
    }


@router.get("/operations/ingestions")
async def ingestion_operations(
    session: SessionDependency,
    owner: OwnerDependency,
    limit: int = Query(default=50, ge=1, le=200),
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    del owner
    pilot_definition = _require_pilot(pilot)
    rows = (
        await session.execute(
            select(IngestionRun)
            .where(IngestionRun.pilot_slug == pilot_definition.slug)
            .order_by(IngestionRun.started_at.desc())
            .limit(limit)
        )
    ).scalars()
    data = [
        IngestionRunResponse(
            id=row.id,
            source=row.source,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            records_seen=row.records_seen,
            records_written=row.records_written,
            latency_ms=row.latency_ms,
            discovered_fields=row.discovered_fields,
            diagnostics=row.diagnostics,
            error_code=row.error_code,
            error_message=row.error_message,
        ).model_dump(mode="json")
        for row in rows
    ]
    return {"data": data, "count": len(data)}


def _next_scheduled_run(source: str, now: datetime) -> datetime | None:
    candidate = now.replace(second=0, microsecond=0)
    if source == "conduit":
        candidate = candidate.replace(minute=8)
        return candidate if candidate > now else candidate + timedelta(hours=1)
    if source == "forecast":
        candidate = candidate.replace(minute=18)
        while candidate <= now or candidate.hour % 3:
            candidate += timedelta(hours=1)
            candidate = candidate.replace(minute=18)
        return candidate
    if source == "aviation_weather":
        minute = ((candidate.minute // 15) + 1) * 15
        if minute >= 60:
            return candidate.replace(minute=0) + timedelta(hours=1)
        return candidate.replace(minute=minute)
    if source == "satellite":
        candidate = candidate.replace(hour=2, minute=20)
        return candidate if candidate > now else candidate + timedelta(days=1)
    if source == "osm":
        candidate = candidate.replace(hour=3, minute=10)
        days = (7 - candidate.weekday()) % 7
        candidate += timedelta(days=days)
        return candidate if candidate > now else candidate + timedelta(days=7)
    return None


@router.get("/operations/status")
async def operations_status(
    session: SessionDependency,
    owner: OwnerDependency,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    del owner
    pilot_definition = _require_pilot(pilot)
    now = datetime.now(UTC)
    thresholds = {
        "conduit": timedelta(hours=2),
        "aviation_weather": timedelta(hours=3),
        "forecast": timedelta(hours=6),
        "satellite": timedelta(hours=48),
        "terrain": timedelta(days=30),
        "osm": timedelta(days=8),
    }
    sources = []
    source_names = list(thresholds)
    if pilot_definition.slug != "jkuat":
        source_names.remove("conduit")
    for source in source_names:
        threshold = thresholds[source]
        latest = (
            await session.execute(
                select(IngestionRun)
                .where(
                    IngestionRun.pilot_slug == pilot_definition.slug,
                    IngestionRun.source == source,
                )
                .order_by(IngestionRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        last_success = (
            await session.execute(
                select(IngestionRun)
                .where(
                    IngestionRun.pilot_slug == pilot_definition.slug,
                    IngestionRun.source == source,
                    IngestionRun.status == "success",
                )
                .order_by(IngestionRun.finished_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        success_at = last_success.finished_at if last_success else None
        if latest is None:
            status = "never_run"
        elif latest.status == "failed" and (success_at is None or latest.started_at > success_at):
            status = "degraded" if success_at else "unavailable"
        elif success_at is None or now - success_at > threshold:
            status = "stale"
        else:
            status = "healthy"
        sources.append(
            {
                "pilot_slug": pilot_definition.slug,
                "source": source,
                "status": status,
                "latest_run_status": latest.status if latest else None,
                "latest_run_at": latest.started_at if latest else None,
                "last_success_at": success_at,
                "age_seconds": (now - success_at).total_seconds() if success_at else None,
                "error_code": latest.error_code if latest else None,
                "next_scheduled_at": _next_scheduled_run(source, now),
            }
        )
    heartbeat = await session.get(SystemState, "worker_heartbeat")
    heartbeat_at = None
    if heartbeat:
        raw = heartbeat.value.get("observed_at")
        if raw:
            try:
                heartbeat_at = datetime.fromisoformat(str(raw))
            except ValueError:
                heartbeat_at = None
    worker_status = (
        "healthy"
        if heartbeat_at and now - heartbeat_at.astimezone(UTC) <= timedelta(minutes=3)
        else "stale"
    )
    return {
        "generated_at": now,
        "pilot_slug": pilot_definition.slug,
        "sources": sources,
        "worker": {"status": worker_status, "last_heartbeat_at": heartbeat_at},
    }


def verify_admin_token(principal: PrincipalDependency) -> None:
    if not principal.is_system_owner:
        raise APIError("FORBIDDEN", "System-owner access is required.", status_code=403)


async def _sample_validation_result(
    payload: bytes,
    session: AsyncSession,
    pilot: PilotDefinition,
) -> tuple[Any, list[dict[str, Any]]]:
    if len(payload) > 2_000_000:
        raise APIError("FILE_TOO_LARGE", "Calibration CSV is limited to 2 MB.", status_code=413)
    validation = validate_sample_csv(
        payload,
        pilot.latitude,
        pilot.longitude,
        pilot.radius_km,
    )
    errors = list(validation.errors)
    identifiers = [row.sample_id for row in validation.rows]
    if identifiers:
        existing = set(
            (
                await session.execute(
                    select(CalibrationSample.external_sample_id).where(
                        CalibrationSample.external_sample_id.in_(identifiers)
                    )
                )
            ).scalars()
        )
        for index, row in enumerate(validation.rows, start=2):
            if row.sample_id in existing:
                errors.append(
                    {
                        "row": index,
                        "field": "sample_id",
                        "message": "sample_id already exists in the calibration registry.",
                    }
                )
    return validation, errors


@router.post("/admin/calibration/samples/validate")
async def validate_calibration_samples(
    session: SessionDependency,
    settings: SettingsDependency,
    _: Annotated[None, Depends(verify_admin_token)],
    pilot: str = Query(default="jkuat"),
    file: UploadFile = File(),
) -> dict[str, Any]:
    del settings
    pilot_definition = _require_pilot(pilot)
    payload = await file.read()
    validation, errors = await _sample_validation_result(payload, session, pilot_definition)
    return {
        "valid": not errors,
        "checksum": validation.checksum,
        "row_count": len(validation.rows),
        "errors": errors,
    }


@router.post("/admin/calibration/samples/import", status_code=201)
async def import_calibration_samples(
    session: SessionDependency,
    settings: SettingsDependency,
    _: Annotated[None, Depends(verify_admin_token)],
    pilot: str = Query(default="jkuat"),
    file: UploadFile = File(),
) -> dict[str, Any]:
    del settings
    pilot_definition = _require_pilot(pilot)
    payload = await file.read()
    checksum = hashlib.sha256(payload).hexdigest()
    prior = (
        await session.execute(
            select(CalibrationImport).where(CalibrationImport.checksum == checksum)
        )
    ).scalar_one_or_none()
    if prior:
        return {
            "status": "already_imported",
            "import_id": str(prior.id),
            "checksum": prior.checksum,
            "row_count": prior.row_count,
        }
    validation, errors = await _sample_validation_result(payload, session, pilot_definition)
    if errors:
        raise APIError(
            "INVALID_CALIBRATION_BATCH",
            "The entire sample batch was rejected. Correct every row and try again.",
            status_code=422,
            details={"checksum": validation.checksum, "errors": errors},
        )
    import_run = CalibrationImport(
        pilot_slug=pilot_definition.slug,
        checksum=validation.checksum,
        filename=Path(file.filename or "samples.csv").name,
        row_count=len(validation.rows),
        status="success",
        diagnostics={"pilot": pilot_definition.name, "atomic_import": True},
    )
    session.add(import_run)
    await session.flush()
    for row in validation.rows:
        session.add(
            CalibrationSample(
                pilot_slug=pilot_definition.slug,
                external_sample_id=row.sample_id,
                sampled_at=row.sampled_at.astimezone(UTC),
                geom=from_shape(Point(row.longitude, row.latitude), srid=4326),
                dry_matter_kg_ha=row.dry_matter_kg_ha,
                method=row.method,
                quadrat_area_m2=row.quadrat_area_m2,
                metadata_json={"import_checksum": validation.checksum},
                import_id=import_run.id,
            )
        )
    await session.commit()
    return {
        "status": "imported",
        "import_id": str(import_run.id),
        "checksum": validation.checksum,
        "row_count": len(validation.rows),
        "model_activation": "CALIBRATION_REQUIRED",
    }


@router.post("/admin/ingestions/{source}/run", status_code=202)
async def run_ingestion(
    source: Literal[
        "conduit", "aviation_weather", "satellite", "terrain", "osm", "forecast"
    ],
    _: Annotated[None, Depends(verify_admin_token)],
    from_date: date | None = None,
    to_date: date | None = None,
    pilot: str = Query(default="jkuat"),
) -> dict[str, Any]:
    pilot_definition = _require_pilot(pilot)
    if source == "conduit" and pilot_definition.slug != "jkuat":
        raise APIError(
            "SOURCE_NOT_AVAILABLE",
            "Conduit is only configured for JKUAT.",
            status_code=422,
        )
    today = datetime.now(UTC).date()
    task = dispatch_ingestion(
        source,
        (from_date or today - timedelta(days=1)).isoformat(),
        (to_date or today).isoformat(),
        pilot_definition.slug,
    )
    return {
        "status": "accepted",
        "source": source,
        "pilot_slug": pilot_definition.slug,
        "task_id": task.id,
    }
