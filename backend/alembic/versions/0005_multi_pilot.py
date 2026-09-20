"""Add the three operational pilots and scope operational records.

Revision ID: 0005_multi_pilot
Revises: 0004_sample_mission_id
"""

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_multi_pilot"
down_revision = "0004_sample_mission_id"
branch_labels = None
depends_on = None


PILOT_SCOPED_TABLES = (
    "ingestion_runs",
    "raw_source_payloads",
    "telemetry_observations",
    "forecast_runs",
    "route_runs",
    "missions",
    "sample_submissions",
    "report_runs",
    "alert_rules",
    "alerts",
    "calibration_samples",
    "calibration_imports",
)


def upgrade() -> None:
    op.create_table(
        "pilots",
        sa.Column("slug", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(96), nullable=False, unique=True),
        sa.Column("center", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("boundary", geoalchemy2.Geometry("POLYGON", srid=4326), nullable=False),
        sa.Column("radius_km", sa.Float(), nullable=False, server_default="10"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Africa/Nairobi"),
        sa.Column(
            "observation_stations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_pilots_active", "pilots", ["active"])
    op.create_index("ix_pilots_center", "pilots", ["center"], postgresql_using="gist")
    op.create_index("ix_pilots_boundary", "pilots", ["boundary"], postgresql_using="gist")
    op.execute(
        """
        INSERT INTO pilots
            (slug, name, center, boundary, radius_km, timezone, observation_stations, active)
        VALUES
          ('jkuat', 'JKUAT',
           ST_SetSRID(ST_MakePoint(37.0144, -1.1018), 4326),
           ST_Buffer(ST_SetSRID(ST_MakePoint(37.0144, -1.1018), 4326)::geography, 10000)::geometry,
           10, 'Africa/Nairobi',
           '[{"station_id":"jkuat-conduit","source":"Conduit","role":"primary"},
             {"station_id":"HKJK","source":"NOAA Aviation Weather METAR",
              "role":"regional_reference"}]', true),
          ('garissa', 'Garissa',
           ST_SetSRID(ST_MakePoint(39.6483, -0.4635), 4326),
           ST_Buffer(ST_SetSRID(ST_MakePoint(39.6483, -0.4635), 4326)::geography, 10000)::geometry,
           10, 'Africa/Nairobi',
           '[{"station_id":"HKGA","source":"NOAA Aviation Weather METAR","role":"primary"}]', true),
          ('lodwar', 'Lodwar',
           ST_SetSRID(ST_MakePoint(35.6087, 3.1220), 4326),
           ST_Buffer(ST_SetSRID(ST_MakePoint(35.6087, 3.1220), 4326)::geography, 10000)::geometry,
           10, 'Africa/Nairobi',
           '[{"station_id":"HKLO","source":"NOAA Aviation Weather METAR","role":"primary"}]', true)
        """
    )

    for table in PILOT_SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column("pilot_slug", sa.String(32), nullable=False, server_default="jkuat"),
        )
        op.create_foreign_key(
            f"fk_{table}_pilot_slug",
            table,
            "pilots",
            ["pilot_slug"],
            ["slug"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_pilot_slug", table, ["pilot_slug"])

    op.add_column(
        "user_profiles",
        sa.Column("default_pilot_slug", sa.String(32), nullable=False, server_default="jkuat"),
    )
    op.create_foreign_key(
        "fk_user_profiles_default_pilot_slug",
        "user_profiles",
        "pilots",
        ["default_pilot_slug"],
        ["slug"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "data_source_settings",
        sa.Column("pilot_slug", sa.String(32), nullable=False, server_default="jkuat"),
    )
    op.drop_constraint("data_source_settings_pkey", "data_source_settings", type_="primary")
    op.create_primary_key(
        "data_source_settings_pkey", "data_source_settings", ["pilot_slug", "source"]
    )
    op.create_foreign_key(
        "fk_data_source_settings_pilot_slug",
        "data_source_settings",
        "pilots",
        ["pilot_slug"],
        ["slug"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_data_source_settings_pilot_slug", "data_source_settings", type_="foreignkey"
    )
    op.drop_constraint("data_source_settings_pkey", "data_source_settings", type_="primary")
    op.create_primary_key("data_source_settings_pkey", "data_source_settings", ["source"])
    op.drop_column("data_source_settings", "pilot_slug")

    op.drop_constraint(
        "fk_user_profiles_default_pilot_slug", "user_profiles", type_="foreignkey"
    )
    op.drop_column("user_profiles", "default_pilot_slug")

    for table in reversed(PILOT_SCOPED_TABLES):
        op.drop_index(f"ix_{table}_pilot_slug", table_name=table)
        op.drop_constraint(f"fk_{table}_pilot_slug", table, type_="foreignkey")
        op.drop_column(table, "pilot_slug")

    op.drop_index("ix_pilots_boundary", table_name="pilots")
    op.drop_index("ix_pilots_center", table_name="pilots")
    op.drop_index("ix_pilots_active", table_name="pilots")
    op.drop_table("pilots")
