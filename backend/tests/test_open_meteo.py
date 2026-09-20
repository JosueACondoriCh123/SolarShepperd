from app.integrations.open_meteo import parse_forecast_points


def test_forecast_parser_preserves_utc_and_missing_values() -> None:
    points = parse_forecast_points(
        {
            "hourly": {
                "time": ["2026-09-19T10:00", "2026-09-19T11:00"],
                "temperature_2m": [24.2, None],
                "relative_humidity_2m": [61, 64],
                "precipitation_probability": [10, 20],
                "precipitation": [0, 0.2],
                "uv_index": [5.1, 5.7],
                "wind_speed_10m": [2.3, 2.8],
                "wind_gusts_10m": [4.2, 4.9],
                "et0_fao_evapotranspiration": [0.12, 0.14],
            }
        }
    )
    assert len(points) == 2
    assert points[0].valid_at.utcoffset().total_seconds() == 0
    assert points[0].temperature_c == 24.2
    assert points[1].temperature_c is None
    assert points[1].precipitation_mm == 0.2


def test_forecast_parser_rejects_missing_hourly_time() -> None:
    try:
        parse_forecast_points({"hourly": {}})
    except ValueError as exc:
        assert "hourly.time" in str(exc)
    else:
        raise AssertionError("invalid forecast payload must be rejected")
