"""Tests for the Scientific Calibration Gate & Biomass Activation Pipeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.errors import APIError
from app.models import ModelVersion
from app.services.calibration import (
    _calculate_regression,
    activate_model_version,
    calculate_grazing_capacity,
    fit_candidate_model,
)

USER_OWNER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def test_calculate_regression_linear_perfect_fit() -> None:
    x = [0.2, 0.4, 0.6, 0.8]
    y = [500.0, 1000.0, 1500.0, 2000.0]
    slope, intercept, metrics = _calculate_regression(x, y)

    assert pytest.approx(slope, rel=1e-3) == 2500.0
    assert pytest.approx(intercept, abs=1e-3) == 0.0
    assert pytest.approx(metrics["r2"], rel=1e-3) == 1.0
    assert pytest.approx(metrics["rmse"], abs=1e-3) == 0.0
    assert metrics["n_samples"] == 4


def test_calculate_regression_noisy_data() -> None:
    x = [0.1, 0.3, 0.5, 0.7, 0.9]
    y = [310.0, 680.0, 1150.0, 1620.0, 2100.0]
    slope, intercept, metrics = _calculate_regression(x, y)

    assert slope > 2000.0
    assert metrics["r2"] > 0.98
    assert metrics["rmse"] < 50.0
    assert metrics["n_samples"] == 5


def test_calculate_regression_insufficient_data() -> None:
    with pytest.raises(APIError) as exc_info:
        _calculate_regression([0.5], [1000.0])
    assert exc_info.value.code == "INSUFFICIENT_DATA"


@pytest.mark.asyncio
async def test_fit_candidate_model_insufficient_samples() -> None:
    session = AsyncMock()
    with patch(
        "app.services.calibration.match_samples_with_satellite_data",
        new=AsyncMock(
            return_value=[
                {"is_matched": True, "ndvi": 0.4, "dry_matter_kg_ha": 1200.0, "sample_id": "s1"}
            ]
        ),
    ):
        with pytest.raises(APIError) as exc_info:
            await fit_candidate_model(session, pilot_slug="jkuat")
        assert exc_info.value.code == "INSUFFICIENT_SAMPLES"


@pytest.mark.asyncio
async def test_fit_candidate_model_success() -> None:
    session = AsyncMock()
    session.scalar.return_value = 0
    matched_data = [
        {"is_matched": True, "ndvi": 0.2, "dry_matter_kg_ha": 500.0, "sample_id": "s1"},
        {"is_matched": True, "ndvi": 0.4, "dry_matter_kg_ha": 1050.0, "sample_id": "s2"},
        {"is_matched": True, "ndvi": 0.6, "dry_matter_kg_ha": 1480.0, "sample_id": "s3"},
        {"is_matched": True, "ndvi": 0.8, "dry_matter_kg_ha": 2020.0, "sample_id": "s4"},
    ]

    with patch(
        "app.services.calibration.match_samples_with_satellite_data",
        new=AsyncMock(return_value=matched_data),
    ):
        model = await fit_candidate_model(
            session,
            pilot_slug="jkuat",
            algorithm="linear_ndvi",
            user_id=USER_OWNER_ID,
            notes="First calibrated batch.",
        )

    assert model.pilot_slug == "jkuat"
    assert model.kind == "dry_matter"
    assert model.status == "candidate"
    assert model.version == "dm-linear-v1"
    assert model.metrics["r2"] > 0.95
    assert len(model.training_sample_ids) == 4
    session.add.assert_called()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_activate_model_version_deprecates_previous() -> None:
    session = AsyncMock()

    candidate_id = uuid.uuid4()
    candidate_model = ModelVersion(
        id=candidate_id,
        pilot_slug="jkuat",
        kind="dry_matter",
        version="dm-linear-v2",
        status="candidate",
        coefficients={"slope": 2450.0, "intercept": 20.0},
        metrics={"r2": 0.88, "rmse": 140.0},
    )

    prev_active = ModelVersion(
        id=uuid.uuid4(),
        pilot_slug="jkuat",
        kind="dry_matter",
        version="dm-linear-v1",
        status="active",
        activated_at=datetime.now(UTC),
    )

    session.get.return_value = candidate_model
    prev_result = MagicMock()
    prev_result.scalars.return_value = [prev_active]
    session.execute.return_value = prev_result

    activated = await activate_model_version(
        session,
        model_id=candidate_id,
        user_id=USER_OWNER_ID,
        pilot_slug="jkuat",
        notes="Verified against holdout plots.",
    )

    assert activated.status == "active"
    assert activated.activated_at is not None
    assert activated.activated_by_user_id == USER_OWNER_ID
    assert activated.notes == "Verified against holdout plots."
    assert prev_active.status == "deprecated"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_calculate_grazing_capacity_requires_active_model() -> None:
    session = AsyncMock()
    no_model_result = MagicMock()
    no_model_result.scalar_one_or_none.return_value = None
    session.execute.return_value = no_model_result

    with pytest.raises(APIError) as exc_info:
        await calculate_grazing_capacity(session, pilot_slug="jkuat", herd_tlu=20.0)
    assert exc_info.value.code == "CALIBRATION_REQUIRED"


@pytest.mark.asyncio
async def test_calculate_grazing_capacity_success() -> None:
    session = AsyncMock()

    active_model = ModelVersion(
        id=uuid.uuid4(),
        pilot_slug="jkuat",
        kind="dry_matter",
        version="dm-linear-v1",
        status="active",
        coefficients={"slope": 2000.0, "intercept": 100.0},
        metrics={"r2": 0.85},
        activated_at=datetime.now(UTC),
    )

    model_exec = MagicMock()
    model_exec.scalar_one_or_none.return_value = active_model

    cells_exec = MagicMock()
    cells_exec.mappings.return_value.all.return_value = [
        {"h3_index": "8928308280fffff", "area_ha": 0.5, "ndvi": 0.5},
        {"h3_index": "8928308281fffff", "area_ha": 0.5, "ndvi": 0.6},
    ]

    session.execute.side_effect = [model_exec, cells_exec]

    result = await calculate_grazing_capacity(
        session,
        pilot_slug="jkuat",
        herd_tlu=10.0,
        utilization_factor=0.40,
    )

    # Cell 1: ndvi 0.5 -> dm_ha = 2000*0.5 + 100 = 1100 kg/ha -> biomass = 1100 * 0.5 = 550 kg
    # Cell 2: ndvi 0.6 -> dm_ha = 2000*0.6 + 100 = 1300 kg/ha -> biomass = 1300 * 0.5 = 650 kg
    # Total biomass: 1200 kg DM
    # Usable forage (40%): 480 kg DM
    # Daily demand: 10 TLU * 6.25 kg/day = 62.5 kg/day
    # Horizon days: 480 / 62.5 = 7.68 -> 7.7 days
    assert result["pilot_slug"] == "jkuat"
    assert result["model_version"] == "dm-linear-v1"
    assert result["total_biomass_kg_dm"] == 1200.0
    assert result["usable_forage_kg_dm"] == 480.0
    assert result["daily_consumption_kg_dm"] == 62.5
    assert pytest.approx(result["grazing_horizon_days"], abs=0.1) == 7.7
    assert result["cell_count"] == 2
