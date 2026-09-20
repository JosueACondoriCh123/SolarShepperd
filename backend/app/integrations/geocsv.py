from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dateutil import parser as date_parser

GEOCSV_MODEL_VERSION = "fewsnet-geocsv-v1"

# Only fields whose meaning and units are explicit in the FEWSNET GeoCSV are
# normalized. Signals under review deliberately have no canonical mapping.
VERIFIED_FIELDS: dict[str, tuple[str, str]] = {
    "temperature_c": ("SHT Temperature", "°C"),
    "temperature_bmx_c": ("BMX Temperature 1", "°C"),
    "temperature_mcp_c": ("MCP Temperature 1", "°C"),
    "relative_humidity_pct": ("SHT Humidity", "%"),
    "pressure_hpa": ("BMX Pressure 1", "hPa"),
    "precipitation_mm": ("Rain Gauge 1 Total Today", "mm"),
    "precipitation_increment_mm": ("Rain Gauge 1", "mm"),
    "precipitation_prior_day_mm": ("Rain Gauge 1 Total Prior", "mm"),
    "wind_speed_m_s": ("Wind Speed", "m/s"),
    "wind_direction_deg": ("Wind Direction", "deg"),
    "wind_gust_m_s": ("Wind Gust", "m/s"),
    "heat_index_c": ("Heat Index", "°C"),
    "wet_bulb_temperature_c": ("Wet Bulb Temperature", "°C"),
    "wet_bulb_globe_temperature_c": ("Wet Bulb Globe Temperature", "°C"),
    "visible_light_count": ("SI1145 Visible 1", "count"),
    "infrared_light_count": ("SI1145 Infrared 1", "count"),
}

EXCLUDED_FIELDS: dict[str, str] = {
    "Battery Voltage": "EMPTY_IN_SOURCE",
    "Health": "BITFIELD_DEFINITION_REQUIRED",
    "Rain Gauge 2": "SECOND_GAUGE_STATUS_UNCONFIRMED",
    "Rain Gauge 2 Total Today": "SECOND_GAUGE_STATUS_UNCONFIRMED",
    "Rain Gauge 2 Total Prior": "SECOND_GAUGE_STATUS_UNCONFIRMED",
    "SI1145 Ultraviolet 1": "RAW_COUNT_NOT_CALIBRATED_UV_INDEX",
    "Wind Gust Direction": "SOURCE_VALUE_DUPLICATES_GUST_SPEED",
}

PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "temperature_c": (-60, 60),
    "temperature_bmx_c": (-60, 60),
    "temperature_mcp_c": (-60, 60),
    "relative_humidity_pct": (0, 100),
    "pressure_hpa": (300, 1_100),
    "precipitation_mm": (0, 2_000),
    "precipitation_increment_mm": (0, 500),
    "precipitation_prior_day_mm": (0, 2_000),
    "wind_speed_m_s": (0, 100),
    "wind_direction_deg": (0, 360),
    "wind_gust_m_s": (0, 150),
    "heat_index_c": (-80, 80),
    "wet_bulb_temperature_c": (-80, 80),
    "wet_bulb_globe_temperature_c": (-80, 100),
    "visible_light_count": (0, 10_000_000),
    "infrared_light_count": (0, 10_000_000),
}


@dataclass(frozen=True)
class GeoCSVImport:
    checksum: str
    filename: str
    metadata: dict[str, str]
    rows_seen: int
    records: list[dict[str, Any]]
    first_observed_at: datetime
    last_observed_at: datetime
    duplicate_timestamps: int
    invalid_values_skipped: int

    @property
    def latitude(self) -> float:
        return float(self.metadata["data collection latitude"])

    @property
    def longitude(self) -> float:
        return float(self.metadata["data collection longitude"])


def _metadata_and_data(payload: str) -> tuple[dict[str, str], str]:
    metadata: dict[str, str] = {}
    data_lines: list[str] = []
    for line in payload.splitlines():
        if line.startswith("#"):
            key, separator, value = line[1:].partition(":")
            if separator:
                metadata[key.strip().lower()] = value.strip()
        elif line.strip():
            data_lines.append(line)
    if not data_lines:
        raise ValueError("GeoCSV contains no tabular data")
    return metadata, "\n".join(data_lines)


def parse_geocsv(path: Path, station_id: str) -> GeoCSVImport:
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    payload = raw.decode("utf-8-sig")
    metadata, data = _metadata_and_data(payload)
    if metadata.get("dataset") != "GeoCSV 2.0":
        raise ValueError("Only GeoCSV 2.0 station exports are supported")
    for required in (
        "instrument_name",
        "sensor_id",
        "data collection site",
        "data collection latitude",
        "data collection longitude",
    ):
        if not metadata.get(required):
            raise ValueError(f"GeoCSV metadata is missing {required!r}")

    reader = csv.DictReader(io.StringIO(data))
    source_fields = set(reader.fieldnames or [])
    required_fields = {"Time", *(source for source, _ in VERIFIED_FIELDS.values())}
    missing = sorted(required_fields - source_fields)
    if missing:
        raise ValueError(f"GeoCSV is missing required fields: {', '.join(missing)}")

    normalized: dict[tuple[datetime, str], dict[str, Any]] = {}
    rows_seen = 0
    invalid_values = 0
    timestamps: list[datetime] = []
    seen_timestamps: set[datetime] = set()
    duplicate_timestamps = 0

    for row in reader:
        rows_seen += 1
        raw_time = (row.get("Time") or "").strip()
        try:
            observed_at = date_parser.parse(raw_time)
        except (TypeError, ValueError, OverflowError):
            invalid_values += 1
            continue
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
            time_flags = ["SOURCE_TIMEZONE_ASSUMED_UTC"]
        else:
            observed_at = observed_at.astimezone(UTC)
            time_flags = []
        if observed_at in seen_timestamps:
            duplicate_timestamps += 1
        else:
            seen_timestamps.add(observed_at)
            timestamps.append(observed_at)

        for metric, (source_field, unit) in VERIFIED_FIELDS.items():
            raw_value = (row.get(source_field) or "").strip()
            if not raw_value:
                continue
            try:
                value = float(raw_value)
            except ValueError:
                invalid_values += 1
                continue
            low, high = PLAUSIBLE_RANGES[metric]
            if not low <= value <= high:
                invalid_values += 1
                continue
            flags = ["HISTORICAL_BACKFILL", *time_flags]
            if metric == "precipitation_mm":
                flags.extend(["DAILY_ACCUMULATION", "RESET_TIMEZONE_UNCONFIRMED"])
            normalized[(observed_at, metric)] = {
                "station_id": station_id,
                "observed_at": observed_at,
                "metric": metric,
                "depth_cm": None,
                "value": value,
                "unit": unit,
                "source": "fewsnet_geocsv",
                "quality_flags": flags,
                "model_version": GEOCSV_MODEL_VERSION,
            }

    if not timestamps:
        raise ValueError("GeoCSV contains no valid timestamps")
    return GeoCSVImport(
        checksum=checksum,
        filename=path.name,
        metadata=metadata,
        rows_seen=rows_seen,
        records=list(normalized.values()),
        first_observed_at=min(timestamps),
        last_observed_at=max(timestamps),
        duplicate_timestamps=duplicate_timestamps,
        invalid_values_skipped=invalid_values,
    )
