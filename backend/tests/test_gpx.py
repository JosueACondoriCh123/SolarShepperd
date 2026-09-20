from app.domain.gpx import route_to_gpx


def test_gpx_contains_route_points() -> None:
    result = route_to_gpx([(37.0, -1.1, 1500), (37.01, -1.11, 1510)], "Test route")
    text = result.decode("utf-8")
    assert "Test route" in text
    assert 'lat="-1.1000000"' in text
    assert "<ele>1500.00</ele>" in text
