from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from shapely.geometry import Polygon


import structlog

logger = structlog.get_logger(__name__)

FALLBACK_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]


@dataclass(frozen=True)
class OSMWaterFeature:
    osm_id: str
    longitude: float
    latitude: float
    name: str | None
    feature_type: str
    tags: dict[str, Any]
    fetched_at: datetime


async def fetch_water_features(
    endpoint: str,
    area: Polygon,
    timeout_s: float = 45,
) -> list[OSMWaterFeature]:
    min_lon, min_lat, max_lon, max_lat = area.bounds
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    query = f"""
    [out:json][timeout:30];
    (
      nwr["amenity"="drinking_water"]({bbox});
      nwr["amenity"="watering_place"]({bbox});
      nwr["waterway"="water_point"]({bbox});
      nwr["natural"="spring"]({bbox});
      nwr["natural"="water"]({bbox});
    );
    out center tags;
    """
    candidates = [endpoint] + [url for url in FALLBACK_OVERPASS_ENDPOINTS if url != endpoint]
    last_error: Exception | None = None
    payload: dict[str, Any] | None = None

    for target_url in candidates:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(
                    target_url,
                    data={"data": query},
                    headers={"User-Agent": "SolarShepherd/0.1 (research prototype)"},
                )
            if response.status_code in {429, 502, 503, 504}:
                logger.warning("overpass_server_busy_fallback", url=target_url, status=response.status_code)
                continue
            response.raise_for_status()
            payload = response.json()
            break
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("overpass_request_failed_trying_fallback", url=target_url, error=str(exc))
            last_error = exc
            continue

    if payload is None:
        if last_error:
            raise last_error
        raise RuntimeError("Failed to fetch water features from all Overpass endpoints")

    fetched_at = datetime.now(UTC)
    features: list[OSMWaterFeature] = []
    for element in payload.get("elements", []):
        longitude = element.get("lon") or element.get("center", {}).get("lon")
        latitude = element.get("lat") or element.get("center", {}).get("lat")
        if longitude is None or latitude is None:
            continue
        tags = element.get("tags", {})
        feature_type = next(
            (tags[key] for key in ("amenity", "waterway", "natural") if key in tags),
            "water",
        )
        features.append(
            OSMWaterFeature(
                osm_id=f"{element.get('type', 'element')}/{element['id']}",
                longitude=float(longitude),
                latitude=float(latitude),
                name=tags.get("name"),
                feature_type=str(feature_type),
                tags=tags,
                fetched_at=fetched_at,
            )
        )
    return features
