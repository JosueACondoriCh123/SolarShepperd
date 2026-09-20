"""Record the verified JKUAT FEWSNET station location and provenance.

Revision ID: 0006_jkuat_station_provenance
Revises: 0005_multi_pilot
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0006_jkuat_station_provenance"
down_revision = "0005_multi_pilot"
branch_labels = None
depends_on = None


VERIFIED_STATIONS = [
    {
        "station_id": "jkuat-conduit",
        "name": "Kenya Kiambu JKUAT IoT AWS · Conduit@Empathy1",
        "latitude": -1.099736,
        "longitude": 37.014528,
        "source": "FEWSNET GeoCSV / Conduit",
        "role": "primary",
    },
    {
        "station_id": "HKJK",
        "name": "Nairobi Jomo Kenyatta International Airport",
        "latitude": -1.3192,
        "longitude": 36.9278,
        "source": "NOAA Aviation Weather METAR",
        "role": "regional_reference",
    },
]

PREVIOUS_STATIONS = [
    {
        "station_id": "jkuat-conduit",
        "name": "JKUAT configured field station",
        "latitude": -1.1018,
        "longitude": 37.0144,
        "source": "Conduit",
        "role": "primary",
    },
    VERIFIED_STATIONS[1],
]


def _set_stations(stations: list[dict[str, object]]) -> None:
    op.execute(
        sa.text(
            "UPDATE pilots SET observation_stations = CAST(:stations AS jsonb) "
            "WHERE slug = 'jkuat'"
        ).bindparams(stations=json.dumps(stations))
    )


def upgrade() -> None:
    _set_stations(VERIFIED_STATIONS)


def downgrade() -> None:
    _set_stations(PREVIOUS_STATIONS)
