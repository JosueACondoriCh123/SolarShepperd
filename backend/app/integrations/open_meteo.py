from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from dateutil.parser import isoparse

FORECAST_MODEL_VERSION = "open-meteo-best-match-v1"
HOURLY_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "uv_index",
    "wind_speed_10m",
    "wind_gusts_10m",
    "et0_fao_evapotranspiration",
)


@dataclass(frozen=True)
class ForecastFetch:
    payload: dict[str, Any]
    checksum: str
    latency_ms: int
    fetched_at: datetime


@dataclass(frozen=True)
class ForecastValue:
    valid_at: datetime
    temperature_c: float | None
    relative_humidity_pct: float | None
    precipitation_probability_pct: float | None
    precipitation_mm: float | None
    uv_index: float | None
    wind_speed_m_s: float | None
    wind_gust_m_s: float | None
    et0_mm: float | None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _at(values: Any, index: int) -> float | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    return _number(values[index])


def parse_forecast_points(payload: dict[str, Any]) -> list[ForecastValue]:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        raise ValueError("Open-Meteo response is missing hourly.time")
    points: list[ForecastValue] = []
    for index, timestamp in enumerate(hourly["time"]):
        parsed = isoparse(str(timestamp))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        points.append(
            ForecastValue(
                valid_at=parsed.astimezone(UTC),
                temperature_c=_at(hourly.get("temperature_2m"), index),
                relative_humidity_pct=_at(hourly.get("relative_humidity_2m"), index),
                precipitation_probability_pct=_at(hourly.get("precipitation_probability"), index),
                precipitation_mm=_at(hourly.get("precipitation"), index),
                uv_index=_at(hourly.get("uv_index"), index),
                wind_speed_m_s=_at(hourly.get("wind_speed_10m"), index),
                wind_gust_m_s=_at(hourly.get("wind_gusts_10m"), index),
                et0_mm=_at(hourly.get("et0_fao_evapotranspiration"), index),
            )
        )
    if not points:
        raise ValueError("Open-Meteo returned no hourly forecast points")
    return points


class OpenMeteoClient:
    def __init__(self, api_url: str) -> None:
        self.api_url = api_url

    async def fetch(self, latitude: float, longitude: float, hours: int) -> ForecastFetch:
        started = time.perf_counter()
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(HOURLY_FIELDS),
            "forecast_hours": hours,
            "timezone": "UTC",
            "wind_speed_unit": "ms",
            "models": "best_match",
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(self.api_url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Open-Meteo response must be a JSON object")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return ForecastFetch(
            payload=payload,
            checksum=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            latency_ms=round((time.perf_counter() - started) * 1_000),
            fetched_at=datetime.now(UTC),
        )
