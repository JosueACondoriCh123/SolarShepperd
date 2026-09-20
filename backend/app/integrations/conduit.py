from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, date
from typing import Any

import httpx
from dateutil import parser as date_parser


class ConduitConfigurationError(RuntimeError):
    pass


class ConduitResponseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConduitFetchResult:
    payload: dict[str, Any] | list[Any]
    checksum: str
    latency_ms: int
    discovered_fields: list[str]


UNITS = {
    "temperature_c": "°C",
    "soil_moisture_surface_pct": "%",
    "soil_moisture_deep_pct": "%",
    "uv_index": "index",
    "precipitation_mm": "mm",
    "solar_radiation_w_m2": "W/m²",
    "relative_humidity_pct": "%",
    "wind_speed_m_s": "m/s",
}


class ConduitClient:
    def __init__(self, url: str, api_key: str, email: str, timeout_s: float = 30) -> None:
        if not api_key or not email:
            raise ConduitConfigurationError(
                "CONDUIT_API_KEY and CONDUIT_EMAIL must both be configured"
            )
        self.url = url
        self.api_key = api_key
        self.email = email
        self.timeout_s = timeout_s

    async def fetch(self, from_date: date, to_date: date) -> ConduitFetchResult:
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=False) as client:
            response = await client.post(
                self.url,
                data={
                    "apikey": self.api_key,
                    "email": self.email,
                    "fromdate": from_date.isoformat(),
                    "todate": to_date.isoformat(),
                },
                headers={"Accept": "application/json", "User-Agent": "SolarShepherd/0.1"},
            )
        latency_ms = round((time.perf_counter() - started) * 1_000)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConduitResponseError("Conduit returned a non-JSON response") from exc
        if not isinstance(payload, (dict, list)):
            raise ConduitResponseError("Conduit JSON must be an object or an array")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return ConduitFetchResult(
            payload=payload,
            checksum=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            latency_ms=latency_ms,
            discovered_fields=discover_field_paths(payload),
        )


def discover_field_paths(value: Any, prefix: str = "", limit: int = 200) -> list[str]:
    found: set[str] = set()

    def visit(current: Any, path: str) -> None:
        if len(found) >= limit:
            return
        if isinstance(current, dict):
            for key, child in current.items():
                next_path = f"{path}.{key}" if path else str(key)
                if isinstance(child, (dict, list)):
                    visit(child, next_path)
                else:
                    found.add(next_path)
        elif isinstance(current, list) and current:
            visit(current[0], path)

    visit(value, prefix)
    return sorted(found)


def extract_records(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    for key in ("data", "records", "results", "weather", "observations"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            for nested in candidate.values():
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return [payload]


def get_path(record: dict[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def normalize_records(
    payload: dict[str, Any] | list[Any],
    field_map: dict[str, str],
    station_id: str,
) -> list[dict[str, Any]]:
    if not field_map or "observed_at" not in field_map:
        return []
    normalized: list[dict[str, Any]] = []
    for record in extract_records(payload):
        raw_time = get_path(record, field_map["observed_at"])
        if raw_time in (None, ""):
            continue
        try:
            observed_at = date_parser.parse(str(raw_time))
        except (TypeError, ValueError, OverflowError):
            continue
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        else:
            observed_at = observed_at.astimezone(UTC)

        for canonical_name, source_path in field_map.items():
            if canonical_name == "observed_at" or canonical_name not in UNITS:
                continue
            raw_value = get_path(record, source_path)
            if raw_value in (None, ""):
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if not (-1e9 < value < 1e9):
                continue
            depth_cm = None
            if canonical_name == "soil_moisture_surface_pct":
                depth_cm = 10.0
            elif canonical_name == "soil_moisture_deep_pct":
                depth_cm = 30.0
            normalized.append(
                {
                    "station_id": station_id,
                    "observed_at": observed_at,
                    "metric": canonical_name,
                    "depth_cm": depth_cm,
                    "value": value,
                    "unit": UNITS[canonical_name],
                    "source": "conduit",
                    "quality_flags": [],
                    "model_version": None,
                }
            )
    return normalized
