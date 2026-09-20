"""Initial scientific and operational schema.

Revision ID: 0001_initial
Revises:
"""

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("requested_from", sa.Date()),
        sa.Column("requested_to", sa.Date()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("discovered_fields", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_ingestion_runs_source", "ingestion_runs", ["source"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])

    op.create_table(
        "raw_source_payloads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("requested_from", sa.Date()),
        sa.Column("requested_to", sa.Date()),
        sa.Column("checksum", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_raw_source_payloads_source", "raw_source_payloads", ["source"])

    op.create_table(
        "telemetry_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("station_id", sa.String(96), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("depth_cm", sa.Float()),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("model_version", sa.String(64)),
        sa.Column(
            "raw_payload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_source_payloads.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "station_id",
            "observed_at",
            "metric",
            "depth_cm",
            name="uq_telemetry_identity",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_telemetry_observations_station_id", "telemetry_observations", ["station_id"]
    )
    op.create_index(
        "ix_telemetry_observations_observed_at", "telemetry_observations", ["observed_at"]
    )
    op.create_index("ix_telemetry_observations_metric", "telemetry_observations", ["metric"])
    op.create_index("ix_telemetry_metric_time", "telemetry_observations", ["metric", "observed_at"])

    op.create_table(
        "satellite_scenes",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("collection", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cloud_cover_pct", sa.Float()),
        sa.Column("processing_status", sa.String(32), nullable=False),
        sa.Column("valid_fraction", sa.Float()),
        sa.Column("assets", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("properties", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("footprint", geoalchemy2.Geometry("MULTIPOLYGON", srid=4326)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_satellite_scenes_acquired_at", "satellite_scenes", ["acquired_at"])
    op.create_index(
        "ix_satellite_scenes_footprint", "satellite_scenes", ["footprint"], postgresql_using="gist"
    )

    op.create_table(
        "h3_cells",
        sa.Column("h3_index", sa.String(16), primary_key=True),
        sa.Column("resolution", sa.Integer(), nullable=False),
        sa.Column("area_ha", sa.Float(), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("POLYGON", srid=4326), nullable=False),
        sa.Column("centroid", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("elevation_m", sa.Float()),
        sa.Column("slope_deg", sa.Float()),
        sa.Column("water_distance_m", sa.Float()),
        sa.Column("terrain_source", sa.String(96)),
        sa.Column("water_source", sa.String(96)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_h3_cells_resolution", "h3_cells", ["resolution"])
    op.create_index("ix_h3_cells_geom", "h3_cells", ["geom"], postgresql_using="gist")
    op.create_index("ix_h3_cells_centroid", "h3_cells", ["centroid"], postgresql_using="gist")

    op.create_table(
        "cell_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "h3_index",
            sa.String(16),
            sa.ForeignKey("h3_cells.h3_index", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_id",
            sa.String(180),
            sa.ForeignKey("satellite_scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ndvi", sa.Float()),
        sa.Column("ndmi", sa.Float()),
        sa.Column("valid_fraction", sa.Float(), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("h3_index", "scene_id", name="uq_cell_scene"),
    )
    op.create_index("ix_cell_observations_h3_index", "cell_observations", ["h3_index"])
    op.create_index("ix_cell_observations_scene_id", "cell_observations", ["scene_id"])
    op.create_index("ix_cell_observation_time", "cell_observations", ["observed_at"])

    op.create_table(
        "water_points",
        sa.Column("osm_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(180)),
        sa.Column("feature_type", sa.String(64), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_water_points_geom", "water_points", ["geom"], postgresql_using="gist")

    op.create_table(
        "route_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("start_point", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("end_point", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("total_distance_m", sa.Float()),
        sa.Column("total_time_s", sa.Float()),
        sa.Column("geojson", postgresql.JSONB()),
        sa.Column("elevation_profile", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(64)),
    )

    op.create_table(
        "calibration_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_sample_id", sa.String(128), nullable=False, unique=True),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("dry_matter_kg_ha", sa.Float(), nullable=False),
        sa.Column("method", sa.String(180), nullable=False),
        sa.Column("quadrat_area_m2", sa.Float(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_calibration_samples_sampled_at", "calibration_samples", ["sampled_at"])
    op.create_index(
        "ix_calibration_samples_geom", "calibration_samples", ["geom"], postgresql_using="gist"
    )

    op.create_table(
        "model_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("coefficients", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("kind", "version", name="uq_model_kind_version"),
    )
    op.create_index("ix_model_versions_kind", "model_versions", ["kind"])

    op.create_table(
        "system_state",
        sa.Column("key", sa.String(96), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    for table in (
        "system_state",
        "model_versions",
        "calibration_samples",
        "route_runs",
        "water_points",
        "cell_observations",
        "h3_cells",
        "satellite_scenes",
        "telemetry_observations",
        "raw_source_payloads",
        "ingestion_runs",
    ):
        op.drop_table(table)
