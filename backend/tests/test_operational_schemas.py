from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.operational_schemas import AlertRuleCreate, MissionCreate, SampleSubmissionCreate


def test_mission_requires_timezone_and_ordered_schedule() -> None:
    start = datetime.now(UTC)

    with pytest.raises(ValidationError):
        MissionCreate(title="Survey", scheduled_start=start.replace(tzinfo=None))

    with pytest.raises(ValidationError):
        MissionCreate(
            title="Survey",
            scheduled_start=start,
            scheduled_end=start - timedelta(hours=1),
        )


def test_sample_requires_timezone_and_positive_scientific_values() -> None:
    base = {
        "sampled_at": datetime.now(UTC),
        "latitude": -1.1018,
        "longitude": 37.0144,
        "dry_matter_kg_ha": 1250,
        "method": "oven-dried quadrat",
        "quadrat_area_m2": 1,
    }

    with pytest.raises(ValidationError):
        SampleSubmissionCreate(**{**base, "sampled_at": datetime.now()})

    with pytest.raises(ValidationError):
        SampleSubmissionCreate(**{**base, "dry_matter_kg_ha": -1})

    with pytest.raises(ValidationError):
        SampleSubmissionCreate(**{**base, "quadrat_area_m2": 0})


def test_alert_thresholds_are_explicit_and_supported() -> None:
    with pytest.raises(ValidationError):
        AlertRuleCreate(name="Hot", kind="forecast_threshold", metric="temperature_c")

    with pytest.raises(ValidationError):
        AlertRuleCreate(
            name="Unknown",
            kind="forecast_threshold",
            metric="biomass_kg_ha",
            comparator=">",
            threshold=100,
        )

    rule = AlertRuleCreate(
        name="High UV",
        kind="forecast_threshold",
        metric="uv_index",
        comparator=">=",
        threshold=8,
        channels=["in_app", "email"],
    )
    assert rule.threshold == 8
    assert rule.channels == ["in_app", "email"]
