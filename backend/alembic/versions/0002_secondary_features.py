"""Forecast and calibration import support.

Revision ID: 0002_secondary_features
Revises: 0001_initial
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_secondary_features"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("model", sa.String(96), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="success"),
        sa.Column("units", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_forecast_runs_checksum", "forecast_runs", ["checksum"])
    op.create_table(
        "forecast_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "forecast_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("forecast_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature_c", sa.Float()),
        sa.Column("relative_humidity_pct", sa.Float()),
        sa.Column("precipitation_probability_pct", sa.Float()),
        sa.Column("precipitation_mm", sa.Float()),
        sa.Column("uv_index", sa.Float()),
        sa.Column("wind_speed_m_s", sa.Float()),
        sa.Column("wind_gust_m_s", sa.Float()),
        sa.Column("et0_mm", sa.Float()),
        sa.Column(
            "quality_flags",
            postgresql.JSONB(),
            nullable=False,
            server_default='["FORECAST_NOT_OBSERVATION"]',
        ),
        sa.UniqueConstraint("forecast_run_id", "valid_at", name="uq_forecast_run_valid_at"),
    )
    op.create_index("ix_forecast_points_forecast_run_id", "forecast_points", ["forecast_run_id"])
    op.create_index("ix_forecast_point_valid_at", "forecast_points", ["valid_at"])

    op.create_table(
        "calibration_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("checksum", sa.String(64), nullable=False, unique=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="success"),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_calibration_imports_checksum", "calibration_imports", ["checksum"])
    op.add_column(
        "calibration_samples",
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_calibration_samples_import_id",
        "calibration_samples",
        "calibration_imports",
        ["import_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_calibration_samples_import_id", "calibration_samples", ["import_id"])


def downgrade() -> None:
    op.drop_index("ix_calibration_samples_import_id", table_name="calibration_samples")
    op.drop_constraint(
        "fk_calibration_samples_import_id", "calibration_samples", type_="foreignkey"
    )
    op.drop_column("calibration_samples", "import_id")
    op.drop_index("ix_calibration_imports_checksum", table_name="calibration_imports")
    op.drop_table("calibration_imports")
    op.drop_index("ix_forecast_point_valid_at", table_name="forecast_points")
    op.drop_index("ix_forecast_points_forecast_run_id", table_name="forecast_points")
    op.drop_table("forecast_points")
    op.drop_index("ix_forecast_runs_checksum", table_name="forecast_runs")
    op.drop_table("forecast_runs")
