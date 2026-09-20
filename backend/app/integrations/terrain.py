from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

import numpy as np
import planetary_computer
import pystac
import rasterio
from pyproj import Transformer
from pystac_client import Client
from rasterio.merge import merge
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_geom
from rasterstats import zonal_stats
from shapely.geometry import Polygon, mapping
from shapely.ops import transform as shapely_transform

from app.integrations.geo import h3_cells_for_polygon, h3_polygon
from app.integrations.satellite import STAC_URL

DEM_COLLECTION = "cop-dem-glo-30"


@dataclass(frozen=True)
class CellTerrainResult:
    h3_index: str
    elevation_m: float | None
    slope_deg: float | None
    quality_flags: list[str]


def search_dem_items(area: Polygon) -> list[pystac.Item]:
    catalog = Client.open(STAC_URL)
    return list(
        catalog.search(
            collections=[DEM_COLLECTION],
            intersects=mapping(area),
            max_items=20,
        ).items()
    )


def _asset_for_item(item: pystac.Item) -> pystac.Asset:
    for key in ("data", "dem", "elevation"):
        if key in item.assets:
            return item.assets[key]
    for asset in item.assets.values():
        roles = asset.roles or []
        if "data" in roles:
            return asset
    raise ValueError(f"DEM item {item.id} contains no supported elevation asset")


def process_dem_items(
    items: list[pystac.Item],
    area: Polygon,
    h3_resolution: int,
    target_crs: str = "EPSG:32737",
) -> list[CellTerrainResult]:
    if not items:
        return []
    signed_items = [planetary_computer.sign(item) for item in items]
    with ExitStack() as stack:
        sources = [
            stack.enter_context(rasterio.open(_asset_for_item(item).href)) for item in signed_items
        ]
        source_crs = sources[0].crs
        area_in_source = transform_geom("EPSG:4326", source_crs, mapping(area))
        area_bounds = Polygon(area_in_source["coordinates"][0]).bounds
        mosaic, mosaic_transform = merge(
            sources,
            bounds=area_bounds,
            nodata=np.nan,
            dtype="float32",
            masked=False,
        )

    elevation_source = mosaic[0]
    src_height, src_width = elevation_source.shape
    left, bottom, right, top = array_bounds(src_height, src_width, mosaic_transform)
    destination_transform, destination_width, destination_height = calculate_default_transform(
        source_crs,
        target_crs,
        src_width,
        src_height,
        left,
        bottom,
        right,
        top,
        resolution=30,
    )
    elevation = np.full((destination_height, destination_width), np.nan, dtype="float32")
    reproject(
        source=elevation_source,
        destination=elevation,
        src_transform=mosaic_transform,
        src_crs=source_crs,
        dst_transform=destination_transform,
        dst_crs=target_crs,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    y_resolution = abs(destination_transform.e)
    x_resolution = abs(destination_transform.a)
    safe_elevation = np.where(np.isfinite(elevation), elevation, np.nan)
    gradient_y, gradient_x = np.gradient(safe_elevation, y_resolution, x_resolution)
    slope = np.degrees(np.arctan(np.hypot(gradient_x, gradient_y))).astype("float32")

    cell_ids = h3_cells_for_polygon(area, h3_resolution)
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    projected_polygons = [
        shapely_transform(transformer.transform, h3_polygon(cell_id)) for cell_id in cell_ids
    ]
    elevation_stats = zonal_stats(
        projected_polygons,
        safe_elevation,
        affine=destination_transform,
        nodata=np.nan,
        stats=["mean", "count"],
    )
    slope_stats = zonal_stats(
        projected_polygons,
        slope,
        affine=destination_transform,
        nodata=np.nan,
        stats=["mean", "count"],
    )
    results: list[CellTerrainResult] = []
    for cell_id, elevation_stat, slope_stat in zip(
        cell_ids, elevation_stats, slope_stats, strict=True
    ):
        flags: list[str] = []
        if not elevation_stat.get("count") or not slope_stat.get("count"):
            flags.append("TERRAIN_DATA_MISSING")
        results.append(
            CellTerrainResult(
                h3_index=cell_id,
                elevation_m=(
                    float(elevation_stat["mean"])
                    if elevation_stat.get("mean") is not None
                    else None
                ),
                slope_deg=(
                    float(slope_stat["mean"]) if slope_stat.get("mean") is not None else None
                ),
                quality_flags=flags,
            )
        )
    return results


def public_dem_metadata(items: list[pystac.Item]) -> dict[str, Any]:
    return {
        "collection": DEM_COLLECTION,
        "item_ids": [item.id for item in items],
        "source": "Copernicus DEM GLO-30 via Microsoft Planetary Computer",
    }
