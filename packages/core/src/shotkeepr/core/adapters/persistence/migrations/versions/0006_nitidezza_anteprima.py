"""preview sharpness

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sharpness_measurements",
        sa.Column("shot_id", sa.Uuid(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("preview_sha256", sa.String(64), nullable=False),
        sa.Column("analyzer_version", sa.String(120), nullable=False),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("laplacian_variance", sa.Float(), nullable=False),
        sa.Column("gradient_energy", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("shot_id"),
    )


def downgrade() -> None:
    op.drop_table("sharpness_measurements")
