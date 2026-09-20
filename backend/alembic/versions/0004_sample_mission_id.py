"""Add mission_id to sample_submissions.

Revision ID: 0004_sample_mission_id
Revises: 0003_operational_app
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_sample_mission_id"
down_revision = "0003_operational_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sample_submissions",
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sample_submissions_mission_id",
        "sample_submissions",
        "missions",
        ["mission_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sample_submissions_mission_id",
        "sample_submissions",
        ["mission_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sample_submissions_mission_id", "sample_submissions")
    op.drop_constraint(
        "fk_sample_submissions_mission_id", "sample_submissions", type_="foreignkey"
    )
    op.drop_column("sample_submissions", "mission_id")
