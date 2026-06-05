"""add result sub-scores

Revision ID: 0003_result_subscores
Revises: 0002_run_controls
Create Date: 2026-06-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_result_subscores"
down_revision = "0002_run_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("results", sa.Column("correctness_score", sa.Float(), nullable=True))
    op.add_column("results", sa.Column("relevance_score", sa.Float(), nullable=True))
    op.add_column("results", sa.Column("completeness_score", sa.Float(), nullable=True))
    op.add_column("results", sa.Column("prompt_quality_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("results", "prompt_quality_score")
    op.drop_column("results", "completeness_score")
    op.drop_column("results", "relevance_score")
    op.drop_column("results", "correctness_score")
