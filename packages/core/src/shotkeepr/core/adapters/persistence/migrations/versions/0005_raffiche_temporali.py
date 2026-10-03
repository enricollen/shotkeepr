"""temporal bursts

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shot_groups", sa.Column("camera_model", sa.String(120), nullable=True))
    op.add_column("shot_groups", sa.Column("camera_serial", sa.String(120), nullable=True))
    op.create_table(
        "burst_grouping",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("gap_seconds", sa.Float(), nullable=False),
        sa.Column("method_version", sa.String(120), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("grouped_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("burst_grouping")
    op.drop_column("shot_groups", "camera_serial")
    op.drop_column("shot_groups", "camera_model")
