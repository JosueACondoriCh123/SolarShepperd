from datetime import UTC, datetime

import pytest

from app.integrations.aviation_weather import (
    KNOT_TO_M_S,
    METAR_RH_MODEL_VERSION,
    normalize_metar_records,
    relative_humidity_percent,
)
from app.pilots import PILOTS, get_pilot


def test_pilot_registry_contains_the_three_real_locations() -> None:
    assert [pilot.slug for pilot in PILOTS] == ["jkuat", "garissa", "lodwar"]
    for pilot in PILOTS:
        assert pilot.radius_km == 10
        assert pilot.boundary.contains(pilot.boundary.centroid)
        assert len(pilot.bbox) == 4
        assert pilot.stations


def test_unknown_pilot_is_not_silently_mapped_to_jkuat() -> None:
    assert get_pilot("not-a-pilot") is None
    assert get_pilot(None) == get_pilot("jkuat")


def test_metar_normalization_uses_canonical_units_and_provenance() -> None:
    observed_at = datetime(2026, 9, 19, 9, tzinfo=UTC)
    records = normalize_metar_records(
        [{
            "icaoId": "HKGA",
            "obsTime": observed_at.timestamp(),
            "temp": 30.0,
            "dewp": 20.0,
            "wspd": 10,
            "wgst": 14,
            "wdir": 80,
            "altim": 1_012.4,
        }],
        "garissa",
        ("HKGA",),
    )
    by_metric = {record["metric"]: record for record in records}
    assert by_metric["wind_speed_m_s"]["value"] == pytest.approx(10 * KNOT_TO_M_S)
    assert by_metric["temperature_c"]["unit"] == "°C"
    assert by_metric["relative_humidity_pct"]["model_version"] == METAR_RH_MODEL_VERSION
    assert by_metric["relative_humidity_pct"]["pilot_slug"] == "garissa"
    assert by_metric["relative_humidity_pct"]["observed_at"] == observed_at


def test_regional_metar_is_explicitly_flagged() -> None:
    records = normalize_metar_records(
        [{"icaoId": "HKJK", "obsTime": 1_789_808_400, "temp": 21, "dewp": 12}],
        "jkuat",
        ("HKJK",),
        ("HKJK",),
    )
    assert records
    assert all("REGIONAL_REFERENCE_OUTSIDE_PILOT" in row["quality_flags"] for row in records)


def test_relative_humidity_is_physically_bounded() -> None:
    assert relative_humidity_percent(25, 25) == pytest.approx(100)
    assert 0 < relative_humidity_percent(30, 10) < 100
