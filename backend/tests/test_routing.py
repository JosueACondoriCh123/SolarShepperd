import h3
import pytest

from app.domain.routing import (
    NoRouteError,
    RoutingParameters,
    SurfaceCell,
    edge_cost,
    find_route,
    tobler_speed_kmh,
)


def make_surface() -> tuple[list[SurfaceCell], str, str]:
    center = h3.latlng_to_cell(-1.1018, 37.0144, 9)
    neighbors = [item for item in h3.grid_disk(center, 1) if item != center]
    end = neighbors[0]
    ids = list(h3.grid_disk(center, 2))
    cells = []
    for index, cell_id in enumerate(ids):
        latitude, longitude = h3.cell_to_latlng(cell_id)
        cells.append(
            SurfaceCell(
                h3_index=cell_id,
                latitude=latitude,
                longitude=longitude,
                elevation_m=1_500 + index * 0.2,
                slope_deg=3,
                uv_index=7,
                forage_index=0.6,
                water_distance_m=1_000,
            )
        )
    return cells, center, end


def test_tobler_speed_is_positive_and_bounded() -> None:
    assert 0 < tobler_speed_kmh(0) <= 6
    assert 0 < tobler_speed_kmh(3) <= 6


def test_edge_cost_is_strictly_positive() -> None:
    cells, start, end = make_surface()
    by_id = {cell.h3_index: cell for cell in cells}
    segment, _ = edge_cost(by_id[start], by_id[end], RoutingParameters())
    assert segment.cost_s > 0
    assert segment.time_s > 0
    assert segment.distance_m > 0


def test_fastest_profile_neutralizes_environmental_multiplier() -> None:
    cells, start, end = make_surface()
    by_id = {cell.h3_index: cell for cell in cells}
    params = RoutingParameters(uv_weight=0, forage_weight=0, water_weight=0)
    segment, _ = edge_cost(by_id[start], by_id[end], params)
    assert segment.multiplier == 1
    assert segment.cost_s == segment.time_s


def test_a_star_includes_start_and_destination() -> None:
    cells, start, end = make_surface()
    result = find_route(cells, start, end, RoutingParameters())
    assert result.cells[0] == start
    assert result.cells[-1] == end
    assert result.total_distance_m > 0
    assert all(segment.cost_s > 0 for segment in result.segments)


def test_a_star_reports_missing_environment_as_neutral_flags() -> None:
    cells, start, end = make_surface()
    neutral_cells = [
        SurfaceCell(
            h3_index=cell.h3_index,
            latitude=cell.latitude,
            longitude=cell.longitude,
            elevation_m=cell.elevation_m,
            slope_deg=cell.slope_deg,
        )
        for cell in cells
    ]
    result = find_route(neutral_cells, start, end, RoutingParameters())
    assert "WATER_DATA_MISSING_NEUTRAL" in result.quality_flags
    assert "FORAGE_DATA_MISSING_NEUTRAL" in result.quality_flags
    assert "UV_DATA_MISSING_NEUTRAL" in result.quality_flags


def test_a_star_fails_when_destination_exceeds_slope_limit() -> None:
    cells, start, end = make_surface()
    blocked = [
        SurfaceCell(**{**cell.__dict__, "slope_deg": 40}) if cell.h3_index == end else cell
        for cell in cells
    ]
    with pytest.raises(NoRouteError):
        find_route(blocked, start, end, RoutingParameters(max_slope_deg=18))
