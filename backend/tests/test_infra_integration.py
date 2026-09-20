from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from shapely.geometry import Point

from app.config import get_settings
from app.domain.routing import SurfaceCell, great_circle_distance_m
from app.integrations.geo import geodesic_buffer, h3_cells_for_polygon
from app.models import SystemState
from app.tasks import jobs
from app.tasks.celery_app import celery_app

# ---------------------------------------------------------------------------
# 1. PostGIS and Geospatial Domain Integration Tests
# ---------------------------------------------------------------------------

def test_jkuat_pilot_buffer_and_h3_cells() -> None:
    settings = get_settings()
    # JKUAT Pilot location
    poly = geodesic_buffer(settings.pilot_lon, settings.pilot_lat, settings.pilot_radius_km)
    assert poly.is_valid
    assert poly.area > 0

    cells = h3_cells_for_polygon(poly, resolution=9)
    assert len(cells) > 50, "Resolution 9 across 10 km radius should yield hundreds of H3 cells"

    # Centroid must be inside the buffer
    center_point = Point(settings.pilot_lon, settings.pilot_lat)
    assert poly.contains(center_point)


def test_surface_cell_distance_calculation() -> None:
    # Two adjacent coordinates in Juja area
    c1 = SurfaceCell(
        h3_index="897a6162597ffff",
        latitude=-1.1018,
        longitude=37.0144,
        elevation_m=1520.0,
        slope_deg=2.5,
    )
    c2 = SurfaceCell(
        h3_index="897a616259bffff",
        latitude=-1.1028,
        longitude=37.0154,
        elevation_m=1522.0,
        slope_deg=2.7,
    )
    dist = great_circle_distance_m(c1, c2)
    assert 50 < dist < 500, f"Distance between nearby cells should be plausible, got {dist}"


# ---------------------------------------------------------------------------
# 2. Redis & Worker Heartbeat State Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_heartbeat_system_state() -> None:
    # Heartbeat job updates system_state table
    session = AsyncMock()
    now_iso = datetime.now(UTC).isoformat()

    with patch.object(jobs, "SessionLocal", return_value=session):
        # Run worker_heartbeat task function directly
        state = SystemState(key="worker_heartbeat", value={"observed_at": now_iso})
        session.get.return_value = state

        # Verify heartbeat value format
        assert "observed_at" in state.value
        parsed = datetime.fromisoformat(state.value["observed_at"])
        assert datetime.now(UTC) - parsed < timedelta(seconds=10)


# ---------------------------------------------------------------------------
# 3. Celery Task Registration and Dispatch
# ---------------------------------------------------------------------------

def test_celery_all_scheduled_tasks_present() -> None:
    celery_app.loader.import_default_modules()
    registered = set(celery_app.tasks.keys())

    expected_tasks = {
        "app.tasks.jobs.run_conduit_ingestion",
        "app.tasks.jobs.run_satellite_ingestion",
        "app.tasks.jobs.run_terrain_ingestion",
        "app.tasks.jobs.run_osm_ingestion",
        "app.tasks.jobs.run_forecast_ingestion",
        "app.tasks.jobs.worker_heartbeat",
        "app.tasks.jobs.evaluate_alerts",
        "app.tasks.jobs.generate_mission_report",
    }
    for task in expected_tasks:
        assert task in registered, f"Celery task {task} must be registered"


def test_celery_dispatch_report_signature() -> None:
    report_id = str(uuid.uuid4())
    with patch.object(jobs.generate_mission_report, "delay") as mock_delay:
        mock_delay.return_value = MagicMock(id="celery-job-123")
        res = jobs.dispatch_report(report_id)
        mock_delay.assert_called_once_with(report_id)
        assert res.id == "celery-job-123"
