from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import h3
import structlog
from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.indices import SPECTRAL_MODEL_VERSION
from app.integrations.aviation_weather import (
    AviationWeatherClient,
    normalize_metar_records,
)
from app.integrations.conduit import ConduitClient, normalize_records
from app.integrations.geo import geodesic_buffer, h3_cells_for_polygon, h3_centroid, h3_polygon
from app.integrations.geocsv import EXCLUDED_FIELDS, VERIFIED_FIELDS, parse_geocsv
from app.integrations.open_meteo import (
    FORECAST_MODEL_VERSION,
    OpenMeteoClient,
    parse_forecast_points,
)
from app.integrations.osm import fetch_water_features
from app.integrations.satellite import (
    SENTINEL_COLLECTION,
    process_sentinel_scene,
    public_scene_metadata,
    search_latest_sentinel_scene,
)
from app.integrations.terrain import process_dem_items, public_dem_metadata, search_dem_items
from app.models import (
    CellObservation,
    ForecastPoint,
    ForecastRun,
    H3Cell,
    IngestionRun,
    RawSourcePayload,
    SatelliteScene,
    SystemState,
    TelemetryObservation,
    WaterPoint,
)
from app.pilots import get_pilot

logger = structlog.get_logger(__name__)


def _safe_error_message(exc: Exception) -> str:
    return str(exc)[:1_000]


class IngestionService:
    def __init__(
        self, session: AsyncSession, settings: Settings, pilot_slug: str = "jkuat"
    ) -> None:
        self.session = session
        self.settings = settings
        self.pilot = get_pilot(pilot_slug)
        if self.pilot is None:
            raise ValueError(f"unsupported pilot: {pilot_slug}")
        self.pilot_slug = self.pilot.slug
        self.area = geodesic_buffer(
            self.pilot.longitude,
            self.pilot.latitude,
            self.pilot.radius_km,
        )

    async def _start_run(
        self, source: str, from_date: date | None = None, to_date: date | None = None
    ) -> IngestionRun:
        run = IngestionRun(
            pilot_slug=self.pilot_slug,
            source=source,
            status="running",
            requested_from=from_date,
            requested_to=to_date,
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def _finish_run(
        self,
        run: IngestionRun,
        *,
        status: str,
        records_seen: int = 0,
        records_written: int = 0,
        latency_ms: int | None = None,
        discovered_fields: list[str] | None = None,
        diagnostics: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> IngestionRun:
        run.status = status
        run.records_seen = records_seen
        run.records_written = records_written
        run.latency_ms = latency_ms
        run.discovered_fields = discovered_fields or []
        run.diagnostics = diagnostics or {}
        run.error_code = error_code
        run.error_message = error_message
        run.finished_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def _fail_run(
        self,
        run_id: UUID,
        *,
        error_code: str,
        error_message: str,
        latency_ms: int | None = None,
    ) -> IngestionRun:
        run = await self.session.get(IngestionRun, run_id)
        if run is None:
            raise RuntimeError(f"ingestion run {run_id} no longer exists")
        return await self._finish_run(
            run,
            status="failed",
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
        )

    async def ingest_conduit(self, from_date: date, to_date: date) -> IngestionRun:
        if self.pilot_slug != "jkuat":
            raise ValueError("Conduit ingestion is only configured for the JKUAT pilot")
        run = await self._start_run("conduit", from_date, to_date)
        run_id = run.id
        try:
            client = ConduitClient(
                self.settings.conduit_api_url,
                self.settings.conduit_api_key,
                self.settings.conduit_email,
            )
            fetched = await client.fetch(from_date, to_date)
            payload_insert = (
                insert(RawSourcePayload)
                .values(
                    pilot_slug=self.pilot_slug,
                    source="conduit",
                    requested_from=from_date,
                    requested_to=to_date,
                    checksum=fetched.checksum,
                    payload=fetched.payload,
                )
                .on_conflict_do_nothing(index_elements=[RawSourcePayload.checksum])
                .returning(RawSourcePayload.id)
            )
            raw_payload_id = (await self.session.execute(payload_insert)).scalar_one_or_none()
            if raw_payload_id is None:
                raw_payload_id = (
                    await self.session.execute(
                        select(RawSourcePayload.id).where(
                            RawSourcePayload.checksum == fetched.checksum
                        )
                    )
                ).scalar_one()

            records = normalize_records(
                fetched.payload,
                self.settings.conduit_field_map,
                self.settings.conduit_station_id,
            )
            written = 0
            for record in records:
                statement = (
                    insert(TelemetryObservation)
                    .values(
                        **record,
                        pilot_slug=self.pilot_slug,
                        raw_payload_id=raw_payload_id,
                    )
                    .on_conflict_do_update(
                        constraint="uq_telemetry_identity",
                        set_={
                            "value": record["value"],
                            "unit": record["unit"],
                            "quality_flags": record["quality_flags"],
                            "raw_payload_id": raw_payload_id,
                            "updated_at": datetime.now(UTC),
                        },
                    )
                )
                await self.session.execute(statement)
                written += 1
            await self.session.commit()
            mapping_required = not bool(self.settings.conduit_field_map)
            return await self._finish_run(
                run,
                status="mapping_required" if mapping_required else "success",
                records_seen=len(records),
                records_written=written,
                latency_ms=fetched.latency_ms,
                discovered_fields=fetched.discovered_fields,
                diagnostics={
                    "pilot_slug": self.pilot_slug,
                    "checksum": fetched.checksum,
                    "mapping_configured": not mapping_required,
                    "et0_status": "INSUFFICIENT_DATA",
                    "et0_reason": "EXPLICIT_DAILY_TMIN_TMAX_REQUIRED",
                },
            )
        except Exception as exc:
            await self.session.rollback()
            logger.exception(
                "conduit_ingestion_failed", run_id=str(run_id), error_type=type(exc).__name__
            )
            return await self._fail_run(
                run_id,
                error_code="CONDUIT_INGESTION_FAILED",
                error_message=_safe_error_message(exc),
            )

    async def remove_unverified_jkuat_observations(self) -> int:
        if self.pilot_slug != "jkuat":
            return 0
        result = await self.session.execute(
            delete(TelemetryObservation).where(
                TelemetryObservation.pilot_slug == self.pilot_slug,
                TelemetryObservation.station_id == self.settings.conduit_station_id,
                TelemetryObservation.metric.in_(
                    [
                        "battery_voltage_v",
                        "et0_mm_day",
                        "health_status",
                        "precipitation_gauge_2_mm",
                        "uv_index",
                        "wind_gust_direction_deg",
                    ]
                ),
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def ingest_geocsv(self, path: Path) -> IngestionRun:
        if self.pilot_slug != "jkuat":
            raise ValueError("FEWSNET GeoCSV ingestion is only configured for JKUAT")
        started = time.perf_counter()
        run = await self._start_run("conduit")
        run_id = run.id
        try:
            parsed = parse_geocsv(path, self.settings.conduit_station_id)
            if parsed.metadata.get("data collection site", "").strip().lower() != "site jkuat":
                raise ValueError("GeoCSV does not identify the JKUAT collection site")
            if not self.area.covers(Point(parsed.longitude, parsed.latitude)):
                raise ValueError("GeoCSV station coordinates fall outside the JKUAT pilot")

            run.requested_from = parsed.first_observed_at.date()
            run.requested_to = parsed.last_observed_at.date()
            raw_payload_id = (
                await self.session.execute(
                    select(RawSourcePayload.id).where(
                        RawSourcePayload.checksum == parsed.checksum
                    )
                )
            ).scalar_one_or_none()
            idempotent_replay = raw_payload_id is not None
            if raw_payload_id is None:
                raw_payload = RawSourcePayload(
                    pilot_slug=self.pilot_slug,
                    source="fewsnet_geocsv",
                    requested_from=parsed.first_observed_at.date(),
                    requested_to=parsed.last_observed_at.date(),
                    checksum=parsed.checksum,
                    payload={
                        "filename": parsed.filename,
                        "metadata": parsed.metadata,
                        "rows_seen": parsed.rows_seen,
                        "normalized_record_count": len(parsed.records),
                        "excluded_fields": EXCLUDED_FIELDS,
                    },
                )
                self.session.add(raw_payload)
                await self.session.flush()
                raw_payload_id = raw_payload.id

            records_written = 0
            batch_size = 1_000
            for offset in range(0, len(parsed.records), batch_size):
                batch = [
                    {
                        **record,
                        "pilot_slug": self.pilot_slug,
                        "raw_payload_id": raw_payload_id,
                    }
                    for record in parsed.records[offset : offset + batch_size]
                ]
                statement = insert(TelemetryObservation).values(batch)
                statement = statement.on_conflict_do_update(
                    constraint="uq_telemetry_identity",
                    set_={
                        "pilot_slug": statement.excluded.pilot_slug,
                        "value": statement.excluded.value,
                        "unit": statement.excluded.unit,
                        "source": statement.excluded.source,
                        "quality_flags": statement.excluded.quality_flags,
                        "model_version": statement.excluded.model_version,
                        "raw_payload_id": statement.excluded.raw_payload_id,
                        "updated_at": datetime.now(UTC),
                    },
                )
                await self.session.execute(statement)
                records_written += len(batch)
            await self.session.commit()
            return await self._finish_run(
                run,
                status="success",
                records_seen=parsed.rows_seen,
                records_written=records_written,
                latency_ms=round((time.perf_counter() - started) * 1_000),
                discovered_fields=sorted(
                    {source for source, _unit in VERIFIED_FIELDS.values()}
                ),
                diagnostics={
                    "input_format": "GeoCSV 2.0",
                    "filename": parsed.filename,
                    "checksum": parsed.checksum,
                    "idempotent_replay": idempotent_replay,
                    "station_id": self.settings.conduit_station_id,
                    "first_observed_at": parsed.first_observed_at.isoformat(),
                    "last_observed_at": parsed.last_observed_at.isoformat(),
                    "duplicate_timestamps": parsed.duplicate_timestamps,
                    "invalid_values_skipped": parsed.invalid_values_skipped,
                    "excluded_fields": EXCLUDED_FIELDS,
                    "et0_status": "INSUFFICIENT_DATA",
                },
            )
        except Exception as exc:
            await self.session.rollback()
            logger.exception(
                "geocsv_ingestion_failed",
                run_id=str(run_id),
                filename=path.name,
                error_type=type(exc).__name__,
            )
            return await self._fail_run(
                run_id,
                error_code="GEOCSV_INGESTION_FAILED",
                error_message=_safe_error_message(exc),
                latency_ms=round((time.perf_counter() - started) * 1_000),
            )

    async def ingest_forecast(self) -> IngestionRun:
        run = await self._start_run("forecast")
        run_id = run.id
        try:
            fetched = await OpenMeteoClient(self.settings.open_meteo_api_url).fetch(
                self.pilot.latitude,
                self.pilot.longitude,
                self.settings.forecast_hours,
            )
            existing = (
                await self.session.execute(
                    select(ForecastRun).where(
                        ForecastRun.pilot_slug == self.pilot_slug,
                        ForecastRun.checksum == fetched.checksum,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return await self._finish_run(
                    run,
                    status="success",
                    records_seen=0,
                    records_written=0,
                    latency_ms=fetched.latency_ms,
                    diagnostics={
                        "forecast_run_id": str(existing.id),
                        "checksum": fetched.checksum,
                        "idempotent_replay": True,
                    },
                )
            points = parse_forecast_points(fetched.payload)
            generated_at = fetched.fetched_at
            raw_generation = fetched.payload.get("generation_time")
            if raw_generation:
                try:
                    parsed_generation = datetime.fromisoformat(str(raw_generation))
                    generated_at = (
                        parsed_generation.replace(tzinfo=UTC)
                        if parsed_generation.tzinfo is None
                        else parsed_generation.astimezone(UTC)
                    )
                except ValueError:
                    pass
            forecast_run = ForecastRun(
                pilot_slug=self.pilot_slug,
                source="open-meteo",
                model=FORECAST_MODEL_VERSION,
                generated_at=generated_at,
                fetched_at=fetched.fetched_at,
                valid_from=points[0].valid_at,
                valid_to=points[-1].valid_at,
                checksum=fetched.checksum,
                status="success",
                units=fetched.payload.get("hourly_units", {}),
                raw_payload=fetched.payload,
            )
            self.session.add(forecast_run)
            await self.session.flush()
            for point in points:
                self.session.add(
                    ForecastPoint(
                        forecast_run_id=forecast_run.id,
                        valid_at=point.valid_at,
                        temperature_c=point.temperature_c,
                        relative_humidity_pct=point.relative_humidity_pct,
                        precipitation_probability_pct=point.precipitation_probability_pct,
                        precipitation_mm=point.precipitation_mm,
                        uv_index=point.uv_index,
                        wind_speed_m_s=point.wind_speed_m_s,
                        wind_gust_m_s=point.wind_gust_m_s,
                        et0_mm=point.et0_mm,
                        quality_flags=["FORECAST_NOT_OBSERVATION"],
                    )
                )
            await self.session.commit()
            return await self._finish_run(
                run,
                status="success",
                records_seen=len(points),
                records_written=len(points),
                latency_ms=fetched.latency_ms,
                diagnostics={
                    "pilot_slug": self.pilot_slug,
                    "forecast_run_id": str(forecast_run.id),
                    "checksum": fetched.checksum,
                    "model_version": FORECAST_MODEL_VERSION,
                    "valid_from": points[0].valid_at.isoformat(),
                    "valid_to": points[-1].valid_at.isoformat(),
                },
            )
        except Exception as exc:
            await self.session.rollback()
            logger.exception(
                "forecast_ingestion_failed", run_id=str(run_id), error_type=type(exc).__name__
            )
            return await self._fail_run(
                run_id,
                error_code="FORECAST_INGESTION_FAILED",
                error_message=_safe_error_message(exc),
            )

    async def ingest_public_observations(self, hours: int = 24) -> IngestionRun:
        run = await self._start_run("aviation_weather")
        run_id = run.id
        try:
            public_stations = tuple(
                station
                for station in self.pilot.stations
                if station.source == "NOAA Aviation Weather METAR"
            )
            fetched = await AviationWeatherClient(
                self.settings.aviation_weather_api_url
            ).fetch(tuple(station.station_id for station in public_stations), hours=hours)
            payload_insert = (
                insert(RawSourcePayload)
                .values(
                    pilot_slug=self.pilot_slug,
                    source="aviation_weather",
                    checksum=fetched.checksum,
                    payload=fetched.payload,
                )
                .on_conflict_do_nothing(index_elements=[RawSourcePayload.checksum])
                .returning(RawSourcePayload.id)
            )
            raw_payload_id = (await self.session.execute(payload_insert)).scalar_one_or_none()
            if raw_payload_id is None:
                raw_payload_id = (
                    await self.session.execute(
                        select(RawSourcePayload.id).where(
                            RawSourcePayload.checksum == fetched.checksum
                        )
                    )
                ).scalar_one()
            records = normalize_metar_records(
                fetched.payload,
                self.pilot_slug,
                tuple(station.station_id for station in public_stations),
                tuple(
                    station.station_id
                    for station in public_stations
                    if station.role == "regional_reference"
                ),
            )
            for record in records:
                await self.session.execute(
                    insert(TelemetryObservation)
                    .values(**record, raw_payload_id=raw_payload_id)
                    .on_conflict_do_update(
                        constraint="uq_telemetry_identity",
                        set_={
                            "pilot_slug": self.pilot_slug,
                            "value": record["value"],
                            "unit": record["unit"],
                            "source": record["source"],
                            "quality_flags": record["quality_flags"],
                            "model_version": record["model_version"],
                            "raw_payload_id": raw_payload_id,
                            "updated_at": datetime.now(UTC),
                        },
                    )
                )
            await self.session.commit()
            return await self._finish_run(
                run,
                status="success" if records else "no_data",
                records_seen=len(fetched.payload),
                records_written=len(records),
                latency_ms=fetched.latency_ms,
                diagnostics={
                    "pilot_slug": self.pilot_slug,
                    "station_ids": [station.station_id for station in public_stations],
                    "checksum": fetched.checksum,
                    "observed_metrics_only": True,
                },
            )
        except Exception as exc:
            await self.session.rollback()
            logger.exception(
                "aviation_weather_ingestion_failed",
                run_id=str(run_id),
                pilot_slug=self.pilot_slug,
                error_type=type(exc).__name__,
            )
            return await self._fail_run(
                run_id,
                error_code="AVIATION_WEATHER_INGESTION_FAILED",
                error_message=_safe_error_message(exc),
            )

    async def ensure_h3_grid(self) -> int:
        cells = h3_cells_for_polygon(self.area, self.settings.h3_resolution)
        written = 0
        for cell_id in cells:
            polygon = h3_polygon(cell_id)
            centroid = h3_centroid(cell_id)
            statement = (
                insert(H3Cell)
                .values(
                    h3_index=cell_id,
                    resolution=self.settings.h3_resolution,
                    area_ha=float(h3.cell_area(cell_id, unit="km^2") * 100),
                    geom=from_shape(polygon, srid=4326),
                    centroid=from_shape(centroid, srid=4326),
                )
                .on_conflict_do_nothing(index_elements=[H3Cell.h3_index])
            )
            result = await self.session.execute(statement)
            written += max(result.rowcount or 0, 0)
        await self.session.commit()
        return written

    async def ingest_satellite(self) -> IngestionRun:
        run = await self._start_run("satellite")
        run_id = run.id
        started = time.perf_counter()
        try:
            await self.ensure_h3_grid()
            end = datetime.now(UTC)
            start = end - timedelta(days=self.settings.stac_lookback_days)
            item = await asyncio.to_thread(
                search_latest_sentinel_scene,
                self.area,
                start,
                end,
                self.settings.stac_max_cloud_percent,
            )
            if item is None:
                return await self._finish_run(
                    run,
                    status="no_data",
                    latency_ms=round((time.perf_counter() - started) * 1_000),
                    diagnostics={
                        "pilot_slug": self.pilot_slug,
                        "lookback_days": self.settings.stac_lookback_days,
                    },
                )
            geometry = shape(item.geometry)
            if isinstance(geometry, Polygon):
                geometry = MultiPolygon([geometry])
            scene_values = {
                "id": item.id,
                "source": "microsoft-planetary-computer",
                "collection": SENTINEL_COLLECTION,
                "acquired_at": item.datetime or datetime.now(UTC),
                "cloud_cover_pct": item.properties.get("eo:cloud_cover"),
                "processing_status": "processing",
                "assets": public_scene_metadata(item),
                "properties": {
                    key: value
                    for key, value in item.properties.items()
                    if key
                    in {
                        "datetime",
                        "eo:cloud_cover",
                        "s2:processing_baseline",
                        "s2:nodata_pixel_percentage",
                    }
                },
                "footprint": from_shape(geometry, srid=4326),
            }
            await self.session.execute(
                insert(SatelliteScene)
                .values(**scene_values)
                .on_conflict_do_update(
                    index_elements=[SatelliteScene.id],
                    set_={**scene_values, "updated_at": datetime.now(UTC)},
                )
            )
            await self.session.commit()
            results = await asyncio.to_thread(
                process_sentinel_scene,
                item,
                self.area,
                self.settings.h3_resolution,
            )
            for result in results:
                await self.session.execute(
                    insert(CellObservation)
                    .values(
                        h3_index=result.h3_index,
                        scene_id=item.id,
                        observed_at=item.datetime or datetime.now(UTC),
                        ndvi=result.ndvi,
                        ndmi=result.ndmi,
                        valid_fraction=result.valid_fraction,
                        quality_flags=result.quality_flags,
                        model_version=SPECTRAL_MODEL_VERSION,
                    )
                    .on_conflict_do_update(
                        constraint="uq_cell_scene",
                        set_={
                            "ndvi": result.ndvi,
                            "ndmi": result.ndmi,
                            "valid_fraction": result.valid_fraction,
                            "quality_flags": result.quality_flags,
                            "updated_at": datetime.now(UTC),
                        },
                    )
                )
            valid_fractions = [result.valid_fraction for result in results]
            await self.session.execute(
                update(SatelliteScene)
                .where(SatelliteScene.id == item.id)
                .values(
                    processing_status="complete",
                    valid_fraction=(
                        sum(valid_fractions) / len(valid_fractions) if valid_fractions else 0
                    ),
                )
            )
            await self.session.commit()
            return await self._finish_run(
                run,
                status="success",
                records_seen=len(results),
                records_written=len(results),
                latency_ms=round((time.perf_counter() - started) * 1_000),
                diagnostics={
                    "pilot_slug": self.pilot_slug,
                    "scene_id": item.id,
                    "collection": SENTINEL_COLLECTION,
                },
            )
        except Exception as exc:
            await self.session.rollback()
            logger.exception(
                "satellite_ingestion_failed", run_id=str(run_id), error_type=type(exc).__name__
            )
            return await self._fail_run(
                run_id,
                latency_ms=round((time.perf_counter() - started) * 1_000),
                error_code="SATELLITE_INGESTION_FAILED",
                error_message=_safe_error_message(exc),
            )

    async def ingest_terrain(self) -> IngestionRun:
        run = await self._start_run("terrain")
        run_id = run.id
        started = time.perf_counter()
        try:
            await self.ensure_h3_grid()
            items = await asyncio.to_thread(search_dem_items, self.area)
            results = await asyncio.to_thread(
                process_dem_items,
                items,
                self.area,
                self.settings.h3_resolution,
            )
            written = 0
            for result in results:
                if result.elevation_m is None or result.slope_deg is None:
                    continue
                await self.session.execute(
                    update(H3Cell)
                    .where(H3Cell.h3_index == result.h3_index)
                    .values(
                        elevation_m=result.elevation_m,
                        slope_deg=result.slope_deg,
                        terrain_source="Copernicus DEM GLO-30",
                    )
                )
                written += 1
            await self._upsert_state("terrain_provenance", public_dem_metadata(items))
            await self.session.commit()
            return await self._finish_run(
                run,
                status="success" if results else "no_data",
                records_seen=len(results),
                records_written=written,
                latency_ms=round((time.perf_counter() - started) * 1_000),
                diagnostics={"pilot_slug": self.pilot_slug, **public_dem_metadata(items)},
            )
        except Exception as exc:
            await self.session.rollback()
            logger.exception(
                "terrain_ingestion_failed", run_id=str(run_id), error_type=type(exc).__name__
            )
            return await self._fail_run(
                run_id,
                latency_ms=round((time.perf_counter() - started) * 1_000),
                error_code="TERRAIN_INGESTION_FAILED",
                error_message=_safe_error_message(exc),
            )

    async def ingest_osm(self) -> IngestionRun:
        run = await self._start_run("osm")
        run_id = run.id
        started = time.perf_counter()
        try:
            await self.ensure_h3_grid()
            features = await fetch_water_features(self.settings.osm_overpass_url, self.area)
            for feature in features:
                values = {
                    "osm_id": feature.osm_id,
                    "name": feature.name,
                    "feature_type": feature.feature_type,
                    "geom": from_shape(Point(feature.longitude, feature.latitude), srid=4326),
                    "tags": feature.tags,
                    "fetched_at": feature.fetched_at,
                }
                await self.session.execute(
                    insert(WaterPoint)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[WaterPoint.osm_id],
                        set_={**values, "updated_at": datetime.now(UTC)},
                    )
                )
            if features:
                await self.session.execute(
                    text(
                        """
                        UPDATE h3_cells AS c
                        SET water_distance_m = (
                                SELECT ST_Distance(
                                    c.centroid::geography,
                                    w.geom::geography
                                )
                                FROM water_points AS w
                                ORDER BY c.centroid <-> w.geom
                                LIMIT 1
                            ),
                            water_source = 'OpenStreetMap / Overpass',
                            updated_at = now()
                        WHERE ST_DWithin(
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
            await self._upsert_state(
                "osm_water_provenance",
                {
                    "source": "OpenStreetMap contributors via Overpass API",
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "feature_count": len(features),
                    "coverage_warning": "OpenStreetMap water-feature coverage may be incomplete.",
                },
            )
            await self.session.commit()
            return await self._finish_run(
                run,
                status="success",
                records_seen=len(features),
                records_written=len(features),
                latency_ms=round((time.perf_counter() - started) * 1_000),
                diagnostics={
                    "pilot_slug": self.pilot_slug,
                    "coverage_warning": "OSM completeness is not guaranteed",
                },
            )
        except Exception as exc:
            await self.session.rollback()
            logger.exception(
                "osm_ingestion_failed", run_id=str(run_id), error_type=type(exc).__name__
            )
            return await self._fail_run(
                run_id,
                latency_ms=round((time.perf_counter() - started) * 1_000),
                error_code="OSM_INGESTION_FAILED",
                error_message=_safe_error_message(exc),
            )

    async def _upsert_state(self, key: str, value: dict[str, Any]) -> None:
        scoped_key = f"{key}:{self.pilot_slug}"
        await self.session.execute(
            insert(SystemState)
            .values(key=scoped_key, value={"pilot_slug": self.pilot_slug, **value})
            .on_conflict_do_update(
                index_elements=[SystemState.key],
                set_={
                    "value": {"pilot_slug": self.pilot_slug, **value},
                    "updated_at": datetime.now(UTC),
                },
            )
        )
