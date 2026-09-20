from pathlib import Path

from app.integrations.geocsv import EXCLUDED_FIELDS, VERIFIED_FIELDS, parse_geocsv


def _fixture() -> str:
    columns = [
        "Time",
        *[source for source, _unit in VERIFIED_FIELDS.values()],
        *EXCLUDED_FIELDS,
    ]
    values = {
        "Time": "2026-09-11T00:00:01Z",
        "SHT Temperature": "17.1",
        "BMX Temperature 1": "16.7",
        "MCP Temperature 1": "16.8",
        "SHT Humidity": "82.6",
        "BMX Pressure 1": "851.8",
        "Rain Gauge 1 Total Today": "0.4",
        "Rain Gauge 1": "0.2",
        "Rain Gauge 1 Total Prior": "0",
        "Wind Speed": "0.9",
        "Wind Direction": "88",
        "Wind Gust": "1.3",
        "Heat Index": "17.1",
        "Wet Bulb Temperature": "15.1",
        "Wet Bulb Globe Temperature": "12.8",
        "SI1145 Visible 1": "258",
        "SI1145 Infrared 1": "252",
        "SI1145 Ultraviolet 1": "4.9",
        "Wind Gust Direction": "1.3",
        "Battery Voltage": "",
        "Health": "33501705",
        "Rain Gauge 2": "0",
        "Rain Gauge 2 Total Today": "0",
        "Rain Gauge 2 Total Prior": "0",
    }
    row = ",".join(values.get(column, "") for column in columns)
    return "\n".join(
        [
            "# dataset: GeoCSV 2.0",
            "# instrument_name: Kenya Kiambu JKUAT IOT AWS - Conduti@Empathy1",
            "# sensor_id: 61",
            "# data collection site: Site JKUAT",
            "# data collection longitude: 37.014528",
            "# data collection latitude: -1.099736",
            ",".join(columns),
            row,
            row,
        ]
    )


def test_geocsv_normalizes_verified_fields_and_deduplicates(tmp_path: Path) -> None:
    source = tmp_path / "jkuat.csv"
    source.write_text(_fixture(), encoding="utf-8")
    parsed = parse_geocsv(source, "jkuat-conduit")

    metrics = {record["metric"]: record for record in parsed.records}
    assert parsed.rows_seen == 2
    assert parsed.duplicate_timestamps == 1
    assert len(parsed.records) == len(VERIFIED_FIELDS)
    assert metrics["temperature_c"]["value"] == 17.1
    assert metrics["precipitation_mm"]["value"] == 0.4
    assert "RESET_TIMEZONE_UNCONFIRMED" in metrics["precipitation_mm"]["quality_flags"]


def test_geocsv_leaves_unverified_observations_unmapped(tmp_path: Path) -> None:
    source = tmp_path / "jkuat.csv"
    source.write_text(_fixture(), encoding="utf-8")
    metrics = {record["metric"] for record in parse_geocsv(source, "station").records}

    assert "uv_index" not in metrics
    assert "wind_gust_direction_deg" not in metrics
    assert "battery_voltage_v" not in metrics
    assert "health_status" not in metrics
