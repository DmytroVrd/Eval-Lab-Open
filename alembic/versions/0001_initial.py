"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_sets_id"), "test_sets", ["id"], unique=False)

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("test_set_id", sa.Integer(), nullable=False),
        sa.Column("target_model", sa.String(length=300), nullable=False),
        sa.Column("judge_model", sa.String(length=300), nullable=False),
        sa.Column("judge_provider", sa.String(length=30), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "done", "failed", name="run_status"), nullable=False),
        sa.Column("avg_score", sa.Float(), nullable=True),
        sa.Column("pass_rate", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["test_set_id"], ["test_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runs_id"), "runs", ["id"], unique=False)
    op.create_index(op.f("ix_runs_status"), "runs", ["status"], unique=False)
    op.create_index(op.f("ix_runs_test_set_id"), "runs", ["test_set_id"], unique=False)

    op.create_table(
        "test_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("test_set_id", sa.Integer(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["test_set_id"], ["test_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_cases_id"), "test_cases", ["id"], unique=False)
    op.create_index(op.f("ix_test_cases_test_set_id"), "test_cases", ["test_set_id"], unique=False)

    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("judge_reason", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_results_id"), "results", ["id"], unique=False)
    op.create_index(op.f("ix_results_run_id"), "results", ["run_id"], unique=False)
    op.create_index(op.f("ix_results_test_case_id"), "results", ["test_case_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index(op.f("ix_results_test_case_id"), table_name="results")
    op.drop_index(op.f("ix_results_run_id"), table_name="results")
    op.drop_index(op.f("ix_results_id"), table_name="results")
    op.drop_table("results")
    op.drop_index(op.f("ix_test_cases_test_set_id"), table_name="test_cases")
    op.drop_index(op.f("ix_test_cases_id"), table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_index(op.f("ix_runs_test_set_id"), table_name="runs")
    op.drop_index(op.f("ix_runs_status"), table_name="runs")
    op.drop_index(op.f("ix_runs_id"), table_name="runs")
    op.drop_table("runs")
    op.drop_index(op.f("ix_test_sets_id"), table_name="test_sets")
    op.drop_table("test_sets")
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS run_status")
