from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from shapely.geometry import Polygon


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
    timeout_s: float = 90,
) -> list[OSMWaterFeature]:
    min_lon, min_lat, max_lon, max_lat = area.bounds
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    query = f"""
    [out:json][timeout:60];
    (
      nwr[\"amenity\"=\"drinking_water\"]({bbox});
      nwr[\"amenity\"=\"watering_place\"]({bbox});
      nwr[\"waterway\"=\"water_point\"]({bbox});
      nwr[\"natural\"=\"spring\"]({bbox});
      nwr[\"natural\"=\"water\"]({bbox});
    );
    out center tags;
    """
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            endpoint,
            data={"data": query},
            headers={"User-Agent": "SolarShepherd/0.1 (research prototype)"},
        )
    response.raise_for_status()
    payload = response.json()
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
