from __future__ import annotations

from datetime import UTC, datetime
from xml.etree.ElementTree import Element, SubElement, tostring


def route_to_gpx(
    coordinates: list[tuple[float, float, float | None]],
    name: str,
) -> bytes:
    root = Element(
        "gpx",
        {
            "version": "1.1",
            "creator": "SolarShepherd",
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    metadata = SubElement(root, "metadata")
    SubElement(metadata, "time").text = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    track = SubElement(root, "trk")
    SubElement(track, "name").text = name
    segment = SubElement(track, "trkseg")
    for longitude, latitude, elevation in coordinates:
        point = SubElement(segment, "trkpt", {"lat": f"{latitude:.7f}", "lon": f"{longitude:.7f}"})
        if elevation is not None:
            SubElement(point, "ele").text = f"{elevation:.2f}"
    return tostring(root, encoding="utf-8", xml_declaration=True)
