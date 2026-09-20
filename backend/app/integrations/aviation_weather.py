from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

METAR_SOURCE = "NOAA Aviation Weather METAR"
METAR_RH_MODEL_VERSION = "magnus-rh-from-temp-dewpoint-v1"
KNOT_TO_M_S = 0.514444


@dataclass(frozen=True)
class FetchedMetar:
    payload: list[dict[str, Any]]
    checksum: str
    latency_ms: int
    fetched_at: datetime


class AviationWeatherClient:
    def __init__(self, api_url: str) -> None:
        self.api_url = api_url.rstrip("/")

    async def fetch(self, station_ids: tuple[str, ...], hours: int = 24) -> FetchedMetar:
        if not station_ids:
            return FetchedMetar([], hashlib.sha256(b"[]").hexdigest(), 0, datetime.now(UTC))
        started = time.perf_counter()
        headers = {"User-Agent": "SolarShepherd/0.2 scientific-pilot"}
        params = {"ids": ",".join(station_ids), "format": "json", "hours": hours}
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            response = await client.get(self.api_url, params=params)
        latency_ms = round((time.perf_counter() - started) * 1_000)
        if response.status_code == 204:
            payload: list[dict[str, Any]] = []
        else:
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, list):
                raise ValueError("Aviation Weather returned a non-list METAR payload")
            payload = [item for item in value if isinstance(item, dict)]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return FetchedMetar(
            payload=payload,
            checksum=hashlib.sha256(canonical).hexdigest(),
            latency_ms=latency_ms,
            fetched_at=datetime.now(UTC),
        )


def relative_humidity_percent(temperature_c: float, dew_point_c: float) -> float:
    numerator = math.exp((17.625 * dew_point_c) / (243.04 + dew_point_c))
    denominator = math.exp((17.625 * temperature_c) / (243.04 + temperature_c))
    return max(0.0, min(100.0, 100.0 * numerator / denominator))


def _observation_time(item: dict[str, Any]) -> datetime:
    raw = item.get("obsTime")
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    raw = item.get("reportTime")
    if isinstance(raw, str):
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(UTC)
    raise ValueError("METAR observation has no usable observation time")


def normalize_metar_records(
    payload: list[dict[str, Any]],
    pilot_slug: str,
    allowed_station_ids: tuple[str, ...],
    regional_station_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    allowed = set(allowed_station_ids)
    regional = set(regional_station_ids)
    records: list[dict[str, Any]] = []
    for item in payload:
        station_id = str(item.get("icaoId") or "").upper()
        if station_id not in allowed:
            continue
        try:
            observed_at = _observation_time(item)
        except (TypeError, ValueError, OSError):
            continue
        base_flags = ["AVIATION_STATION_OBSERVATION"]
        if station_id in regional:
            base_flags.append("REGIONAL_REFERENCE_OUTSIDE_PILOT")
        qc_value = item.get("qcField")
        if qc_value not in (None, 0, "0"):
            base_flags.append(f"SOURCE_QC_FLAG_{qc_value}")

        def append(
            metric: str,
            value: Any,
            unit: str,
            *,
            multiplier: float = 1.0,
            bound_station_id: str = station_id,
            bound_observed_at: datetime = observed_at,
            bound_flags: tuple[str, ...] = tuple(base_flags),
        ) -> None:
            if not isinstance(value, (int, float)):
                return
            records.append(
                {
                    "pilot_slug": pilot_slug,
                    "station_id": bound_station_id,
                    "observed_at": bound_observed_at,
                    "metric": metric,
                    "depth_cm": None,
                    "value": float(value) * multiplier,
                    "unit": unit,
                    "source": METAR_SOURCE,
                    "quality_flags": list(bound_flags),
                    "model_version": None,
                }
            )

        append("temperature_c", item.get("temp"), "°C")
        append("dew_point_c", item.get("dewp"), "°C")
        append("wind_speed_m_s", item.get("wspd"), "m/s", multiplier=KNOT_TO_M_S)
        append("wind_gust_m_s", item.get("wgst"), "m/s", multiplier=KNOT_TO_M_S)
        append("wind_direction_deg", item.get("wdir"), "degrees")
        append("pressure_hpa", item.get("altim"), "hPa")
        temperature = item.get("temp")
        dew_point = item.get("dewp")
        if isinstance(temperature, (int, float)) and isinstance(dew_point, (int, float)):
            records.append(
                {
                    "pilot_slug": pilot_slug,
                    "station_id": station_id,
                    "observed_at": observed_at,
                    "metric": "relative_humidity_pct",
                    "depth_cm": None,
                    "value": relative_humidity_percent(float(temperature), float(dew_point)),
                    "unit": "%",
                    "source": METAR_SOURCE,
                    "quality_flags": [*base_flags, "DERIVED_FROM_TEMPERATURE_AND_DEW_POINT"],
                    "model_version": METAR_RH_MODEL_VERSION,
                }
            )
    return records
