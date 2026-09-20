from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import mapping

from app.integrations.geo import geodesic_buffer


@dataclass(frozen=True)
class ObservationStation:
    station_id: str
    name: str
    latitude: float
    longitude: float
    source: str
    role: str = "primary"


@dataclass(frozen=True)
class PilotDefinition:
    slug: str
    name: str
    latitude: float
    longitude: float
    radius_km: float
    timezone: str
    stations: tuple[ObservationStation, ...]

    @property
    def boundary(self):
        return geodesic_buffer(self.longitude, self.latitude, self.radius_km)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return self.boundary.bounds

    @property
    def station_ids(self) -> tuple[str, ...]:
        return tuple(station.station_id for station in self.stations)

    def public_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "center": {"latitude": self.latitude, "longitude": self.longitude},
            "radius_km": self.radius_km,
            "timezone": self.timezone,
            "bbox": list(self.bbox),
            "boundary": mapping(self.boundary),
            "observation_sources": sorted({station.source for station in self.stations}),
        }


PILOTS: tuple[PilotDefinition, ...] = (
    PilotDefinition(
        slug="jkuat",
        name="JKUAT",
        latitude=-1.1018,
        longitude=37.0144,
        radius_km=10.0,
        timezone="Africa/Nairobi",
        stations=(
            ObservationStation(
                station_id="jkuat-conduit",
                name="Kenya Kiambu JKUAT IoT AWS · Conduit@Empathy1",
                latitude=-1.099736,
                longitude=37.014528,
                source="FEWSNET GeoCSV / Conduit",
            ),
            ObservationStation(
                station_id="HKJK",
                name="Nairobi Jomo Kenyatta International Airport",
                latitude=-1.3192,
                longitude=36.9278,
                source="NOAA Aviation Weather METAR",
                role="regional_reference",
            ),
        ),
    ),
    PilotDefinition(
        slug="garissa",
        name="Garissa",
        latitude=-0.4635,
        longitude=39.6483,
        radius_km=10.0,
        timezone="Africa/Nairobi",
        stations=(
            ObservationStation(
                station_id="HKGA",
                name="Garissa Airport",
                latitude=-0.4635,
                longitude=39.6483,
                source="NOAA Aviation Weather METAR",
            ),
        ),
    ),
    PilotDefinition(
        slug="lodwar",
        name="Lodwar",
        latitude=3.1220,
        longitude=35.6087,
        radius_km=10.0,
        timezone="Africa/Nairobi",
        stations=(
            ObservationStation(
                station_id="HKLO",
                name="Lodwar Airport",
                latitude=3.1220,
                longitude=35.6087,
                source="NOAA Aviation Weather METAR",
            ),
        ),
    ),
)

PILOTS_BY_SLUG = {pilot.slug: pilot for pilot in PILOTS}


def get_pilot(slug: str | None) -> PilotDefinition | None:
    return PILOTS_BY_SLUG.get((slug or "jkuat").strip().lower())
