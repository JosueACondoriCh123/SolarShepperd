"""Add response cases, updates, attachments and alert response mode.

Revision ID: 0007_response_center
Revises: 0006_jkuat_station_provenance
"""

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_response_center"
down_revision = "0006_jkuat_station_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. AlertRule extensions: severity and response_mode
    op.add_column(
        "alert_rules",
        sa.Column("severity", sa.String(16), server_default="warning", nullable=False),
    )
    op.add_column(
        "alert_rules",
        sa.Column("response_mode", sa.String(24), server_default="notify_only", nullable=False),
    )
    # Ensure all pre-existing rules are set to notify_only
    op.execute("UPDATE alert_rules SET response_mode = 'notify_only'")

    # 2. Response Cases table
    op.create_table(
        "response_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pilot_slug", sa.String(32), sa.ForeignKey("pilots.slug"), nullable=False),
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
            nullable=True,
        ),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), server_default="triage", nullable=False),
        sa.Column("severity", sa.String(16), server_default="warning", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("dismissal_reason", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "ix_response_cases_pilot_slug", "response_cases", ["pilot_slug"]
    )
    op.create_index(
        "ix_response_cases_owner_user_id", "response_cases", ["owner_user_id"]
    )
    op.create_index(
        "ix_response_cases_rule_id", "response_cases", ["rule_id"]
    )
    op.create_index(
        "ix_response_cases_mission_id", "response_cases", ["mission_id"]
    )
    op.create_index(
        "ix_response_cases_status", "response_cases", ["status"]
    )

    # 3. Response Updates table
    op.create_table(
        "response_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "response_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("response_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_response_updates_response_case_id", "response_updates", ["response_case_id"]
    )
    op.create_index(
        "ix_response_updates_author_user_id", "response_updates", ["author_user_id"]
    )
    op.create_index(
        "ix_response_updates_created_at", "response_updates", ["created_at"]
    )

    # 4. Response Attachments table
    op.create_table(
        "response_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "update_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("response_updates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(512), unique=True, nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_response_attachments_update_id", "response_attachments", ["update_id"]
    )

    # 5. Alert response_case_id link
    op.add_column(
        "alerts",
        sa.Column(
            "response_case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("response_cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_alerts_response_case_id", "alerts", ["response_case_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_response_case_id", "alerts")
    op.drop_column("alerts", "response_case_id")
    op.drop_table("response_attachments")
    op.drop_table("response_updates")
    op.drop_table("response_cases")
    op.drop_column("alert_rules", "response_mode")
    op.drop_column("alert_rules", "severity")
