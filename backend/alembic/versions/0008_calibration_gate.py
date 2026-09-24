"""Add pilot_slug, algorithm, training_sample_ids, notes, activated_by_user_id to model_versions.

Revision ID: 0008_calibration_gate
Revises: 0007_response_center
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_calibration_gate"
down_revision = "0007_response_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_versions",
        sa.Column(
            "pilot_slug",
            sa.String(32),
            sa.ForeignKey("pilots.slug", ondelete="CASCADE"),
            nullable=True,
            server_default="jkuat",
        ),
    )
    op.add_column(
        "model_versions",
        sa.Column(
            "algorithm",
            sa.String(64),
            nullable=True,
            server_default="linear_ndvi",
        ),
    )
    op.add_column(
        "model_versions",
        sa.Column(
            "training_sample_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "model_versions",
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "model_versions",
        sa.Column(
            "activated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.auth_user_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_model_versions_pilot_status",
        "model_versions",
        ["pilot_slug", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_versions_pilot_status", table_name="model_versions")
    op.drop_column("model_versions", "activated_by_user_id")
    op.drop_column("model_versions", "notes")
    op.drop_column("model_versions", "training_sample_ids")
    op.drop_column("model_versions", "algorithm")
    op.drop_column("model_versions", "pilot_slug")
