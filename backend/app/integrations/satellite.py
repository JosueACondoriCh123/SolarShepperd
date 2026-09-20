from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import numpy as np
import planetary_computer
import pystac
import rasterio
from pyproj import Transformer
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom
from rasterio.windows import Window
from rasterio.windows import from_bounds as window_from_bounds
from rasterstats import zonal_stats
from shapely.geometry import Polygon, mapping
from shapely.ops import transform as shapely_transform

from app.integrations.geo import h3_cells_for_polygon, h3_polygon

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SENTINEL_COLLECTION = "sentinel-2-l2a"
INVALID_SCL_CLASSES = {0, 1, 3, 8, 9, 10, 11}


@dataclass(frozen=True)
class CellSpectralResult:
    h3_index: str
    ndvi: float | None
    ndmi: float | None
    valid_fraction: float
    quality_flags: list[str]


def search_latest_sentinel_scene(
    area: Polygon,
    start: datetime,
    end: datetime,
    max_cloud_percent: float,
) -> pystac.Item | None:
    catalog = Client.open(STAC_URL)
    search = catalog.search(
        collections=[SENTINEL_COLLECTION],
        intersects=mapping(area),
        datetime=f"{start.astimezone(UTC).isoformat()}/{end.astimezone(UTC).isoformat()}",
        query={"eo:cloud_cover": {"lte": max_cloud_percent}},
        sortby=[{"field": "properties.datetime", "direction": "desc"}],
        max_items=10,
    )
    for item in search.items():
        if all(key in item.assets for key in ("B04", "B08", "B11", "SCL")):
            return item
    return None


def public_scene_metadata(item: pystac.Item) -> dict[str, Any]:
    return {
        key: {
            "title": asset.title,
            "media_type": asset.media_type,
            "roles": asset.roles,
        }
        for key, asset in item.assets.items()
        if key in {"B04", "B08", "B11", "SCL", "visual", "rendered_preview", "tilejson"}
    }


def public_scene_tilejson_url(item_id: str) -> str:
    query = urlencode(
        {
            "collection": SENTINEL_COLLECTION,
            "item": item_id,
            "assets": "visual",
        }
    )
    return f"https://planetarycomputer.microsoft.com/api/data/v1/item/tilejson.json?{query}"


def _scale_offset(asset: pystac.Asset) -> tuple[float, float]:
    bands = asset.extra_fields.get("raster:bands", [])
    if bands and isinstance(bands[0], dict):
        return float(bands[0].get("scale", 0.0001)), float(bands[0].get("offset", 0.0))
    return 0.0001, 0.0


def _bounded_window(
    dataset: rasterio.DatasetReader, bounds: tuple[float, float, float, float]
) -> Window:
    raw = window_from_bounds(*bounds, transform=dataset.transform)
    full = Window(0, 0, dataset.width, dataset.height)
    return raw.round_offsets().round_lengths().intersection(full)


def process_sentinel_scene(
    item: pystac.Item,
    area: Polygon,
    h3_resolution: int,
) -> list[CellSpectralResult]:
    signed = planetary_computer.sign(item)
    red_asset = signed.assets["B04"]
    with rasterio.open(red_asset.href) as red_source:
        area_projected_json = transform_geom("EPSG:4326", red_source.crs, mapping(area))
        projected_bounds = Polygon(area_projected_json["coordinates"][0]).bounds
        window = _bounded_window(red_source, projected_bounds)
        transform = red_source.window_transform(window)
        height, width = round(window.height), round(window.width)
        red = red_source.read(1, window=window).astype("float32")
        target_crs = red_source.crs

        def read_aligned(key: str, resampling: Resampling) -> np.ndarray:
            asset = signed.assets[key]
            with rasterio.open(asset.href) as source:
                with WarpedVRT(
                    source,
                    crs=target_crs,
                    transform=transform,
                    width=width,
                    height=height,
                    resampling=resampling,
                ) as aligned:
                    return aligned.read(1).astype("float32")

        nir = read_aligned("B08", Resampling.bilinear)
        swir = read_aligned("B11", Resampling.bilinear)
        scl = read_aligned("SCL", Resampling.nearest).astype("uint8")

    red_scale, red_offset = _scale_offset(item.assets["B04"])
    nir_scale, nir_offset = _scale_offset(item.assets["B08"])
    swir_scale, swir_offset = _scale_offset(item.assets["B11"])
    red = red * red_scale + red_offset
    nir = nir * nir_scale + nir_offset
    swir = swir * swir_scale + swir_offset

    inside_aoi = geometry_mask(
        [area_projected_json], out_shape=(height, width), transform=transform, invert=True
    )
    valid = inside_aoi & ~np.isin(scl, list(INVALID_SCL_CLASSES))
    ndvi_array = np.full((height, width), np.nan, dtype="float32")
    ndmi_array = np.full((height, width), np.nan, dtype="float32")
    with np.errstate(divide="ignore", invalid="ignore"):
        np.divide(nir - red, nir + red, out=ndvi_array, where=valid & (np.abs(nir + red) > 1e-6))
        np.divide(nir - swir, nir + swir, out=ndmi_array, where=valid & (np.abs(nir + swir) > 1e-6))
    ndvi_array[(ndvi_array < -1) | (ndvi_array > 1)] = np.nan
    ndmi_array[(ndmi_array < -1) | (ndmi_array > 1)] = np.nan

    cell_ids = h3_cells_for_polygon(area, h3_resolution)
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    projected_polygons = [
        shapely_transform(transformer.transform, h3_polygon(cell_id)) for cell_id in cell_ids
    ]
    ndvi_stats = zonal_stats(
        projected_polygons,
        ndvi_array,
        affine=transform,
        nodata=np.nan,
        stats=["mean", "count"],
    )
    ndmi_stats = zonal_stats(
        projected_polygons,
        ndmi_array,
        affine=transform,
        nodata=np.nan,
        stats=["mean", "count"],
    )
    pixel_area = abs(transform.a * transform.e)
    results: list[CellSpectralResult] = []
    for cell_id, polygon, ndvi_stat, ndmi_stat in zip(
        cell_ids, projected_polygons, ndvi_stats, ndmi_stats, strict=True
    ):
        expected_count = max(1.0, polygon.area / pixel_area)
        valid_count = min(ndvi_stat.get("count", 0), ndmi_stat.get("count", 0))
        valid_fraction = min(1.0, max(0.0, valid_count / expected_count))
        flags: list[str] = []
        if valid_fraction < 0.5:
            flags.append("LOW_VALID_PIXEL_COVERAGE")
        results.append(
            CellSpectralResult(
                h3_index=cell_id,
                ndvi=float(ndvi_stat["mean"]) if ndvi_stat.get("mean") is not None else None,
                ndmi=float(ndmi_stat["mean"]) if ndmi_stat.get("mean") is not None else None,
                valid_fraction=valid_fraction,
                quality_flags=flags,
            )
        )
    return results
