"""Operational product accounts, missions, samples, reports and alerts.

Revision ID: 0003_operational_app
Revises: 0002_secondary_features
"""

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_operational_app"
down_revision = "0002_secondary_features"
branch_labels = None
depends_on = None


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("auth_user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320)),
        sa.Column(
            "display_name", sa.String(120), nullable=False, server_default="SolarShepherd member"
        ),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Africa/Nairobi"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_system_owner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "notification_preferences", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_index("ix_user_profiles_email", "user_profiles", ["email"])
    op.create_index("ix_user_profiles_status", "user_profiles", ["status"])
    op.create_index("ix_user_profiles_is_system_owner", "user_profiles", ["is_system_owner"])

    op.add_column("route_runs", sa.Column("owner_user_id", postgresql.UUID(as_uuid=True)))
    op.add_column("route_runs", sa.Column("name", sa.String(180)))
    op.create_foreign_key(
        "fk_route_runs_owner_user_id",
        "route_runs",
        "user_profiles",
        ["owner_user_id"],
        ["auth_user_id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_route_runs_owner_user_id", "route_runs", ["owner_user_id"])

    op.create_table(
        "missions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("scheduled_start", sa.DateTime(timezone=True)),
        sa.Column("scheduled_end", sa.DateTime(timezone=True)),
        sa.Column(
            "route_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("route_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("herd_tlu", sa.Float()),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    for column in ("owner_user_id", "status", "scheduled_start", "route_run_id"):
        op.create_index(f"ix_missions_{column}", "missions", [column])

    op.create_table(
        "sample_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sample_code", sa.String(40), nullable=False, unique=True),
        sa.Column("external_reference", sa.String(128)),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("dry_matter_kg_ha", sa.Float(), nullable=False),
        sa.Column("method", sa.String(180), nullable=False),
        sa.Column("quadrat_area_m2", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("review_notes", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "reviewed_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "calibration_sample_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calibration_samples.id", ondelete="SET NULL"),
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *timestamps(),
        sa.UniqueConstraint(
            "owner_user_id", "external_reference", name="uq_sample_owner_reference"
        ),
    )
    for column in ("owner_user_id", "sample_code", "sampled_at", "status"):
        op.create_index(f"ix_sample_submissions_{column}", "sample_submissions", [column])
    op.create_index(
        "ix_sample_submissions_geom", "sample_submissions", ["geom"], postgresql_using="gist"
    )

    op.create_table(
        "sample_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "submission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sample_submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_sample_attachments_submission_id", "sample_attachments", ["submission_id"])

    op.create_table(
        "report_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("evidence_manifest", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("pdf_object_key", sa.String(512)),
        sa.Column("json_object_key", sa.String(512)),
        sa.Column("error_message", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    for column in ("owner_user_id", "mission_id", "status"):
        op.create_index(f"ix_report_runs_{column}", "report_runs", [column])

    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("metric", sa.String(64)),
        sa.Column("comparator", sa.String(8)),
        sa.Column("threshold", sa.Float()),
        sa.Column("lookahead_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("channels", postgresql.JSONB(), nullable=False, server_default='["in_app"]'),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    for column in ("owner_user_id", "kind", "enabled"):
        op.create_index(f"ix_alert_rules_{column}", "alert_rules", [column])

    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alert_rules.id", ondelete="SET NULL"),
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("dedupe_key", sa.String(180), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
    )
    for column in ("owner_user_id", "rule_id", "kind", "created_at"):
        op.create_index(f"ix_alerts_{column}", "alerts", [column])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "alert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("provider_id", sa.String(180)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_notification_deliveries_alert_id", "notification_deliveries", ["alert_id"])
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(180)),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    for column in ("actor_user_id", "action", "occurred_at"):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])

    op.create_table(
        "data_source_settings",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("schedule", sa.String(96)),
        sa.Column("mapping", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="SET NULL"),
        ),
        *timestamps(),
    )


def downgrade() -> None:
    for table in (
        "data_source_settings",
        "audit_events",
        "notification_deliveries",
        "alerts",
        "alert_rules",
        "report_runs",
        "sample_attachments",
        "sample_submissions",
        "missions",
    ):
        op.drop_table(table)
    op.drop_index("ix_route_runs_owner_user_id", table_name="route_runs")
    op.drop_constraint("fk_route_runs_owner_user_id", "route_runs", type_="foreignkey")
    op.drop_column("route_runs", "name")
    op.drop_column("route_runs", "owner_user_id")
    op.drop_table("user_profiles")
