from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import h3
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.routing import (
    ROUTING_MODEL_VERSION,
    NoRouteError,
    RouteResult,
    RoutingParameters,
    SurfaceCell,
    find_route,
)
from app.errors import APIError
from app.models import RouteRun, SatelliteScene, SystemState, TelemetryObservation
from app.pilots import get_pilot
from app.schemas import RouteRequest, RouteResponse


class RoutingService:
    def __init__(
        self, session: AsyncSession, h3_resolution: int, pilot_slug: str = "jkuat"
    ) -> None:
        self.session = session
        self.h3_resolution = h3_resolution
        self.pilot = get_pilot(pilot_slug)
        if self.pilot is None:
            raise ValueError(f"unsupported pilot: {pilot_slug}")

    async def calculate(
        self, request: RouteRequest, owner_user_id: uuid.UUID | None = None
    ) -> RouteResponse:
        start_point = Point(request.start.longitude, request.start.latitude)
        end_point = Point(request.end.longitude, request.end.latitude)
        if not self.pilot.boundary.covers(start_point) or not self.pilot.boundary.covers(end_point):
            raise APIError(
                "OUTSIDE_PILOT",
                "Route origin and destination must both be inside the active pilot.",
                status_code=422,
                details={"pilot_slug": self.pilot.slug, "radius_km": self.pilot.radius_km},
            )
        start_index = h3.latlng_to_cell(
            request.start.latitude, request.start.longitude, self.h3_resolution
        )
        end_index = h3.latlng_to_cell(
            request.end.latitude, request.end.longitude, self.h3_resolution
        )
        latest_uv, latest_uv_at = await self._latest_uv()
        rows = (
            await self.session.execute(
                text(
                    """
                    SELECT c.h3_index,
                           ST_Y(c.centroid) AS latitude,
                           ST_X(c.centroid) AS longitude,
                           c.elevation_m,
                           c.slope_deg,
                           c.water_distance_m,
                           latest.ndvi,
                           latest.valid_fraction
                    FROM h3_cells AS c
                    LEFT JOIN LATERAL (
                        SELECT o.ndvi, o.valid_fraction
                        FROM cell_observations AS o
                        WHERE o.h3_index = c.h3_index
                        ORDER BY o.observed_at DESC
                        LIMIT 1
                    ) AS latest ON true
                    WHERE c.elevation_m IS NOT NULL
                      AND c.slope_deg IS NOT NULL
                      AND ST_DWithin(
                          c.centroid::geography,
                          ST_SetSRID(ST_MakePoint(:pilot_lon, :pilot_lat), 4326)::geography,
                          :radius_m
                      )
                    """
                ),
                {
                    "pilot_lon": self.pilot.longitude,
                    "pilot_lat": self.pilot.latitude,
                    "radius_m": self.pilot.radius_km * 1_000,
                },
            )
        ).mappings()
        cells: list[SurfaceCell] = []
        for row in rows:
            flags: list[str] = []
            forage_index: float | None = None
            if row["ndvi"] is not None and (row["valid_fraction"] or 0) >= 0.5:
                forage_index = max(0.0, min(1.0, (float(row["ndvi"]) + 1.0) / 2.0))
                flags.append("FORAGE_IS_RELATIVE_NDVI_PROXY")
            cells.append(
                SurfaceCell(
                    h3_index=row["h3_index"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    elevation_m=float(row["elevation_m"]),
                    slope_deg=float(row["slope_deg"]),
                    uv_index=latest_uv,
                    forage_index=forage_index,
                    water_distance_m=(
                        float(row["water_distance_m"])
                        if row["water_distance_m"] is not None
                        else None
                    ),
                    quality_flags=tuple(flags),
                )
            )
        if not cells:
            raise APIError(
                "INSUFFICIENT_DATA",
                "Terrain ingestion must complete before routing is available.",
                status_code=409,
                details={"required_source": "Copernicus DEM GLO-30"},
            )
        environmental_weights = (
            {"uv_weight": 0.0, "forage_weight": 0.0, "water_weight": 0.0}
            if request.profile == "fastest"
            else {
                "uv_weight": request.uv_weight,
                "forage_weight": request.forage_weight,
                "water_weight": request.water_weight,
            }
        )
        params = RoutingParameters(
            max_slope_deg=request.max_slope_deg,
            **environmental_weights,
        )
        try:
            result = find_route(cells, start_index, end_index, params)
        except NoRouteError as exc:
            raise APIError(
                "NO_ROUTE_FOUND",
                str(exc),
                status_code=422,
                details={
                    "start_h3": start_index,
                    "end_h3": end_index,
                    "surface_cell_count": len(cells),
                    "max_slope_deg": request.max_slope_deg,
                },
            ) from exc
        by_id = {cell.h3_index: cell for cell in cells}
        provenance = await self._provenance(latest_uv_at)
        response_data = self._serialize(
            result,
            by_id,
            request.herd_tlu,
            request.profile,
            environmental_weights,
            provenance,
        )
        route = RouteRun(
            id=uuid.uuid4(),
            pilot_slug=self.pilot.slug,
            status="complete",
            start_point=from_shape(
                start_point, srid=4326
            ),
            end_point=from_shape(end_point, srid=4326),
            parameters=request.model_dump(),
            total_distance_m=result.total_distance_m,
            total_time_s=result.estimated_time_s,
            geojson=response_data["geojson"],
            elevation_profile=response_data["elevation_profile"],
            diagnostics=response_data["diagnostics"],
            owner_user_id=owner_user_id,
        )
        self.session.add(route)
        await self.session.commit()
        return RouteResponse(
            id=route.id,
            status="complete",
            total_distance_m=result.total_distance_m,
            estimated_time_s=result.estimated_time_s,
            geojson=response_data["geojson"],
            elevation_profile=response_data["elevation_profile"],
            diagnostics=response_data["diagnostics"],
            quality_flags=result.quality_flags,
            not_applied_parameters=["herd_tlu"] if request.herd_tlu is not None else [],
            profile=request.profile,
        )

    async def _latest_uv(self) -> tuple[float | None, datetime | None]:
        row = (
            await self.session.execute(
                select(TelemetryObservation.value, TelemetryObservation.observed_at)
                .where(
                    TelemetryObservation.pilot_slug == self.pilot.slug,
                    TelemetryObservation.metric == "uv_index",
                )
                .order_by(TelemetryObservation.observed_at.desc())
                .limit(1)
            )
        ).one_or_none()
        return (float(row.value), row.observed_at) if row else (None, None)

    async def _provenance(self, latest_uv_at: datetime | None) -> dict[str, Any]:
        scene = (
            await self.session.execute(
                select(SatelliteScene)
                .where(
                    SatelliteScene.processing_status == "complete",
                    SatelliteScene.footprint.is_not(None),
                    text(
                        "ST_Intersects(satellite_scenes.footprint, "
                        "ST_GeomFromText(:pilot_boundary, 4326))"
                    ),
                )
                .order_by(SatelliteScene.acquired_at.desc())
                .limit(1)
            ),
            {"pilot_boundary": self.pilot.boundary.wkt},
        ).scalar_one_or_none()
        states = (
            await self.session.execute(
                select(SystemState).where(
                    SystemState.key.in_(
                        [
                            f"terrain_provenance:{self.pilot.slug}",
                            f"osm_water_provenance:{self.pilot.slug}",
                        ]
                    )
                )
            )
        ).scalars()
        state_by_key = {state.key.split(":", 1)[0]: state.value for state in states}
        return {
            "pilot_slug": self.pilot.slug,
            "uv_observed_at": latest_uv_at.isoformat() if latest_uv_at else None,
            "satellite_scene_id": scene.id if scene else None,
            "satellite_acquired_at": scene.acquired_at.isoformat() if scene else None,
            "terrain": state_by_key.get("terrain_provenance"),
            "water": state_by_key.get("osm_water_provenance"),
        }

    def _serialize(
        self,
        result: RouteResult,
        cells: dict[str, SurfaceCell],
        herd_tlu: float | None,
        profile: str,
        environmental_weights: dict[str, float],
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        coordinates = [
            [cells[cell_id].longitude, cells[cell_id].latitude] for cell_id in result.cells
        ]
        cumulative_distance = 0.0
        elevation_profile = [
            {
                "distance_m": 0.0,
                "elevation_m": cells[result.cells[0]].elevation_m,
            }
        ]
        segment_features: list[dict[str, Any]] = []
        for segment in result.segments:
            cumulative_distance += segment.distance_m
            destination = cells[segment.to_cell]
            elevation_profile.append(
                {
                    "distance_m": cumulative_distance,
                    "elevation_m": destination.elevation_m,
                }
            )
            segment_features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [cells[segment.from_cell].longitude, cells[segment.from_cell].latitude],
                            [destination.longitude, destination.latitude],
                        ],
                    },
                    "properties": {
                        "cost_s": segment.cost_s,
                        "time_s": segment.time_s,
                        "distance_m": segment.distance_m,
                        "slope": segment.directional_slope,
                        "multiplier": segment.multiplier,
                        "uv_index": destination.uv_index,
                        "forage_index": destination.forage_index,
                        "water_distance_m": destination.water_distance_m,
                        "quality_flags": list(destination.quality_flags),
                    },
                }
            )
        return {
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coordinates},
                        "properties": {
                            "model_version": ROUTING_MODEL_VERSION,
                            "total_distance_m": result.total_distance_m,
                            "estimated_time_s": result.estimated_time_s,
                        },
                    },
                    *segment_features,
                ],
            },
            "elevation_profile": elevation_profile,
            "diagnostics": {
                "pilot_slug": self.pilot.slug,
                "model_version": ROUTING_MODEL_VERSION,
                "visited_nodes": result.visited_nodes,
                "route_cells": len(result.cells),
                "total_cost_s": result.total_cost_s,
                "quality_flags": list(result.quality_flags),
                "calculation_time": datetime.now(UTC).isoformat(),
                "herd_tlu_applied": False,
                "herd_tlu_received": herd_tlu,
                "profile": profile,
                "environmental_weights": environmental_weights,
                "inputs_as_of": provenance,
            },
        }
