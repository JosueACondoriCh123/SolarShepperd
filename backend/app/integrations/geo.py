from __future__ import annotations

from collections.abc import Iterable

import h3
from pyproj import Geod
from shapely.geometry import Point, Polygon, mapping


def geodesic_buffer(
    longitude: float, latitude: float, radius_km: float, vertices: int = 96
) -> Polygon:
    geod = Geod(ellps="WGS84")
    ring: list[tuple[float, float]] = []
    for azimuth in range(0, 360, max(1, 360 // vertices)):
        lon, lat, _ = geod.fwd(longitude, latitude, azimuth, radius_km * 1_000)
        ring.append((lon, lat))
    ring.append(ring[0])
    return Polygon(ring)


def h3_cells_for_polygon(polygon: Polygon, resolution: int) -> list[str]:
    return sorted(h3.geo_to_cells(mapping(polygon), resolution))


def h3_polygon(cell_index: str) -> Polygon:
    # h3 boundaries are (latitude, longitude); GeoJSON/Shapely uses (longitude, latitude).
    return Polygon(
        [(longitude, latitude) for latitude, longitude in h3.cell_to_boundary(cell_index)]
    )


def h3_centroid(cell_index: str) -> Point:
    latitude, longitude = h3.cell_to_latlng(cell_index)
    return Point(longitude, latitude)


def bbox_tuple(polygon: Polygon) -> tuple[float, float, float, float]:
    minimum_x, minimum_y, maximum_x, maximum_y = polygon.bounds
    return minimum_x, minimum_y, maximum_x, maximum_y


def points_bbox(points: Iterable[Point]) -> tuple[float, float, float, float]:
    values = list(points)
    if not values:
        raise ValueError("at least one point is required")
    return (
        min(point.x for point in values),
        min(point.y for point in values),
        max(point.x for point in values),
        max(point.y for point in values),
    )
