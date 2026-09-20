from __future__ import annotations

import heapq
import math
from collections.abc import Iterable
from dataclasses import dataclass, field

import h3

ROUTING_MODEL_VERSION = "tobler-bounded-cost-v1"
MAX_TOBLER_SPEED_KMH = 6.0
MIN_COST_MULTIPLIER = 0.60


class NoRouteError(RuntimeError):
    pass


@dataclass(frozen=True)
class SurfaceCell:
    h3_index: str
    latitude: float
    longitude: float
    elevation_m: float
    slope_deg: float
    uv_index: float | None = None
    forage_index: float | None = None
    water_distance_m: float | None = None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutingParameters:
    max_slope_deg: float = 18.0
    uv_weight: float = 0.6
    forage_weight: float = 0.25
    water_weight: float = 0.2
    water_scale_m: float = 2_000.0


@dataclass(frozen=True)
class RouteSegment:
    from_cell: str
    to_cell: str
    distance_m: float
    time_s: float
    cost_s: float
    directional_slope: float
    multiplier: float


@dataclass
class RouteResult:
    cells: list[str]
    segments: list[RouteSegment]
    total_distance_m: float
    estimated_time_s: float
    total_cost_s: float
    visited_nodes: int
    quality_flags: list[str] = field(default_factory=list)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def tobler_speed_kmh(directional_slope: float) -> float:
    """Tobler walking speed for a rise/run gradient, bounded away from zero."""
    if not math.isfinite(directional_slope):
        raise ValueError("directional_slope must be finite")
    speed = 6.0 * math.exp(-3.5 * abs(directional_slope + 0.05))
    return clamp(speed, 0.2, MAX_TOBLER_SPEED_KMH)


def environmental_multiplier(
    cell: SurfaceCell, params: RoutingParameters
) -> tuple[float, list[str]]:
    flags: list[str] = []
    uv_norm = 0.0
    if cell.uv_index is None:
        flags.append("UV_DATA_MISSING_NEUTRAL")
    else:
        uv_norm = clamp(cell.uv_index / 11.0, 0.0, 1.0)

    forage_norm = 0.0
    if cell.forage_index is None:
        flags.append("FORAGE_DATA_MISSING_NEUTRAL")
    else:
        forage_norm = clamp(cell.forage_index, 0.0, 1.0)

    water_score = 0.0
    if cell.water_distance_m is None:
        flags.append("WATER_DATA_MISSING_NEUTRAL")
    else:
        water_score = math.exp(-max(0.0, cell.water_distance_m) / params.water_scale_m)

    multiplier = (
        (1.0 + params.uv_weight * uv_norm)
        * (1.0 - params.forage_weight * forage_norm)
        * (1.0 - params.water_weight * water_score)
    )
    return max(MIN_COST_MULTIPLIER, multiplier), flags


def great_circle_distance_m(first: SurfaceCell, second: SurfaceCell) -> float:
    return float(
        h3.great_circle_distance(
            (first.latitude, first.longitude),
            (second.latitude, second.longitude),
            unit="m",
        )
    )


def edge_cost(
    current: SurfaceCell,
    neighbor: SurfaceCell,
    params: RoutingParameters,
) -> tuple[RouteSegment, list[str]]:
    if abs(neighbor.slope_deg) > params.max_slope_deg:
        raise ValueError("neighbor exceeds maximum allowed slope")
    distance_m = great_circle_distance_m(current, neighbor)
    if distance_m <= 0:
        raise ValueError("neighbor distance must be positive")
    directional_slope = (neighbor.elevation_m - current.elevation_m) / distance_m
    speed_m_s = tobler_speed_kmh(directional_slope) / 3.6
    travel_time_s = distance_m / speed_m_s
    multiplier, flags = environmental_multiplier(neighbor, params)
    cost_s = travel_time_s * multiplier
    if cost_s <= 0 or not math.isfinite(cost_s):
        raise ValueError("routing cost must be finite and strictly positive")
    return (
        RouteSegment(
            from_cell=current.h3_index,
            to_cell=neighbor.h3_index,
            distance_m=distance_m,
            time_s=travel_time_s,
            cost_s=cost_s,
            directional_slope=directional_slope,
            multiplier=multiplier,
        ),
        flags,
    )


def _heuristic(cell: SurfaceCell, destination: SurfaceCell) -> float:
    distance_m = great_circle_distance_m(cell, destination)
    best_case_time = distance_m / (MAX_TOBLER_SPEED_KMH / 3.6)
    return best_case_time * MIN_COST_MULTIPLIER


def find_route(
    cells: Iterable[SurfaceCell],
    start_index: str,
    end_index: str,
    params: RoutingParameters,
) -> RouteResult:
    surface = {cell.h3_index: cell for cell in cells}
    if start_index not in surface or end_index not in surface:
        raise NoRouteError("start and end cells must both exist in the cost surface")
    if start_index == end_index:
        return RouteResult([start_index], [], 0.0, 0.0, 0.0, 1)

    destination = surface[end_index]
    frontier: list[tuple[float, str]] = [(0.0, start_index)]
    came_from: dict[str, str | None] = {start_index: None}
    segment_to: dict[str, RouteSegment] = {}
    cost_so_far: dict[str, float] = {start_index: 0.0}
    all_flags: set[str] = set()
    visited = 0

    while frontier:
        _, current_index = heapq.heappop(frontier)
        visited += 1
        if current_index == end_index:
            break
        current = surface[current_index]
        for neighbor_index in h3.grid_disk(current_index, 1):
            if neighbor_index == current_index or neighbor_index not in surface:
                continue
            neighbor = surface[neighbor_index]
            if abs(neighbor.slope_deg) > params.max_slope_deg:
                continue
            segment, flags = edge_cost(current, neighbor, params)
            all_flags.update(flags)
            new_cost = cost_so_far[current_index] + segment.cost_s
            if neighbor_index not in cost_so_far or new_cost < cost_so_far[neighbor_index]:
                cost_so_far[neighbor_index] = new_cost
                priority = new_cost + _heuristic(neighbor, destination)
                heapq.heappush(frontier, (priority, neighbor_index))
                came_from[neighbor_index] = current_index
                segment_to[neighbor_index] = segment

    if end_index not in came_from:
        raise NoRouteError("no traversable route connects the selected cells")

    path = [end_index]
    segments: list[RouteSegment] = []
    while path[-1] != start_index:
        current_index = path[-1]
        segments.append(segment_to[current_index])
        previous = came_from[current_index]
        if previous is None:
            raise NoRouteError("route reconstruction failed")
        path.append(previous)
    path.reverse()
    segments.reverse()

    return RouteResult(
        cells=path,
        segments=segments,
        total_distance_m=sum(segment.distance_m for segment in segments),
        estimated_time_s=sum(segment.time_s for segment in segments),
        total_cost_s=sum(segment.cost_s for segment in segments),
        visited_nodes=visited,
        quality_flags=sorted(all_flags),
    )
