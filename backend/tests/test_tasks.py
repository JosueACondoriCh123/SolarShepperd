from types import SimpleNamespace

import pytest

from app.tasks import jobs
from app.tasks.celery_app import celery_app


def test_ingestion_tasks_are_registered() -> None:
    celery_app.loader.import_default_modules()

    assert {
        "app.tasks.jobs.run_conduit_ingestion",
        "app.tasks.jobs.run_satellite_ingestion",
        "app.tasks.jobs.run_terrain_ingestion",
        "app.tasks.jobs.run_osm_ingestion",
        "app.tasks.jobs.run_forecast_ingestion",
        "app.tasks.jobs.worker_heartbeat",
    }.issubset(celery_app.tasks)


@pytest.mark.asyncio
async def test_task_run_disposes_async_engine_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    disposed = False

    class SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    class Service:
        def __init__(self, *_: object) -> None:
            pass

        async def ingest_osm(self) -> SimpleNamespace:
            return SimpleNamespace(id="run-id")

    class Engine:
        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    monkeypatch.setattr(jobs, "SessionLocal", SessionContext)
    monkeypatch.setattr(jobs, "IngestionService", Service)
    monkeypatch.setattr(jobs, "engine", Engine())

    assert await jobs._run("osm") == "run-id"
    assert disposed is True
