from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from celery.result import AsyncResult
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import SystemState
from app.pilots import PILOTS
from app.services.alerts import evaluate_alert_rules
from app.services.ingestion import IngestionService
from app.services.reporting import build_report
from app.tasks.celery_app import celery_app


async def _run(
    source: str,
    from_date: date | None = None,
    to_date: date | None = None,
    pilot_slug: str = "jkuat",
) -> str:
    settings = get_settings()
    try:
        async with SessionLocal() as session:
            service = IngestionService(session, settings, pilot_slug)
            if source == "conduit":
                today = datetime.now(UTC).date()
                result = await service.ingest_conduit(
                    from_date or today - timedelta(days=1), to_date or today
                )
            elif source == "satellite":
                result = await service.ingest_satellite()
            elif source == "terrain":
                result = await service.ingest_terrain()
            elif source == "osm":
                result = await service.ingest_osm()
            elif source == "forecast":
                result = await service.ingest_forecast()
            elif source == "aviation_weather":
                result = await service.ingest_public_observations()
            else:
                raise ValueError(f"unsupported ingestion source: {source}")
            return str(result.id)
    finally:
        # Celery prefork workers call asyncio.run() for every task. Connections
        # created by asyncpg belong to that task's event loop, so they must not
        # remain pooled for the next asyncio.run() invocation in the process.
        await engine.dispose()


@celery_app.task(name="app.tasks.jobs.run_conduit_ingestion")
def run_conduit_ingestion(from_date: str | None = None, to_date: str | None = None) -> str:
    return asyncio.run(
        _run(
            "conduit",
            date.fromisoformat(from_date) if from_date else None,
            date.fromisoformat(to_date) if to_date else None,
        )
    )


@celery_app.task(name="app.tasks.jobs.run_satellite_ingestion")
def run_satellite_ingestion(pilot_slug: str = "jkuat") -> str:
    return asyncio.run(_run("satellite", pilot_slug=pilot_slug))


@celery_app.task(name="app.tasks.jobs.run_terrain_ingestion")
def run_terrain_ingestion(pilot_slug: str = "jkuat") -> str:
    return asyncio.run(_run("terrain", pilot_slug=pilot_slug))


@celery_app.task(name="app.tasks.jobs.run_osm_ingestion")
def run_osm_ingestion(pilot_slug: str = "jkuat") -> str:
    return asyncio.run(_run("osm", pilot_slug=pilot_slug))


@celery_app.task(name="app.tasks.jobs.run_forecast_ingestion")
def run_forecast_ingestion(pilot_slug: str = "jkuat") -> str:
    return asyncio.run(_run("forecast", pilot_slug=pilot_slug))


@celery_app.task(name="app.tasks.jobs.run_public_observation_ingestion")
def run_public_observation_ingestion(pilot_slug: str | None = None) -> list[str]:
    pilots = [pilot for pilot in PILOTS if pilot_slug in (None, pilot.slug)]
    return [
        asyncio.run(_run("aviation_weather", pilot_slug=pilot.slug))
        for pilot in pilots
    ]


async def _write_worker_heartbeat() -> str:
    try:
        async with SessionLocal() as session:
            now = datetime.now(UTC)
            await session.execute(
                insert(SystemState)
                .values(key="worker_heartbeat", value={"observed_at": now.isoformat()})
                .on_conflict_do_update(
                    index_elements=[SystemState.key],
                    set_={"value": {"observed_at": now.isoformat()}, "updated_at": now},
                )
            )
            await session.commit()
            return now.isoformat()
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.jobs.worker_heartbeat")
def worker_heartbeat() -> str:
    return asyncio.run(_write_worker_heartbeat())


async def _generate_report(report_id: str) -> str:
    try:
        async with SessionLocal() as session:
            await build_report(session, get_settings(), UUID(report_id))
        return report_id
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.jobs.generate_mission_report")
def generate_mission_report(report_id: str) -> str:
    return asyncio.run(_generate_report(report_id))


async def _evaluate_alerts() -> int:
    try:
        async with SessionLocal() as session:
            return await evaluate_alert_rules(session, get_settings())
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.jobs.evaluate_alerts")
def evaluate_alerts() -> int:
    return asyncio.run(_evaluate_alerts())


def dispatch_report(report_id: str) -> AsyncResult[Any]:
    return generate_mission_report.delay(report_id)


def dispatch_ingestion(
    source: str,
    from_date: str | None = None,
    to_date: str | None = None,
    pilot_slug: str = "jkuat",
) -> AsyncResult[Any]:
    if source == "conduit":
        return run_conduit_ingestion.apply_async(args=(from_date, to_date), retry=False)
    if source == "satellite":
        return run_satellite_ingestion.apply_async(args=(pilot_slug,), retry=False)
    if source == "terrain":
        return run_terrain_ingestion.apply_async(args=(pilot_slug,), retry=False)
    if source == "osm":
        return run_osm_ingestion.apply_async(args=(pilot_slug,), retry=False)
    if source == "forecast":
        return run_forecast_ingestion.apply_async(args=(pilot_slug,), retry=False)
    if source == "aviation_weather":
        return run_public_observation_ingestion.apply_async(args=(pilot_slug,), retry=False)
    raise ValueError(f"unsupported ingestion source: {source}")
