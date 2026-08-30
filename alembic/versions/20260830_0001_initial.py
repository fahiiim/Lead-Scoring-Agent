"""Create lead scoring persistence tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260830_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "research_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("lead_id", sa.String(length=64), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_sessions_lead_id",
        "research_sessions",
        ["lead_id"],
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("research_session_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("relevance", sa.Float(), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["research_session_id"],
            ["research_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_research_session_id",
        "evidence",
        ["research_session_id"],
    )
    op.create_table(
        "lead_facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("research_session_id", sa.String(length=64), nullable=False),
        sa.Column("field", sa.String(length=100), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("alternatives_json", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["research_session_id"],
            ["research_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lead_facts_research_session_id",
        "lead_facts",
        ["research_session_id"],
    )
    op.create_table(
        "score_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(length=10), nullable=False),
        sa.Column("research_confidence", sa.Float(), nullable=False),
        sa.Column("scoring_confidence", sa.Float(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id"),
    )
    op.create_index("ix_score_results_lead_id", "score_results", ["lead_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_score_results_lead_id", table_name="score_results")
    op.drop_table("score_results")
    op.drop_index("ix_lead_facts_research_session_id", table_name="lead_facts")
    op.drop_table("lead_facts")
    op.drop_index("ix_evidence_research_session_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_research_sessions_lead_id", table_name="research_sessions")
    op.drop_table("research_sessions")
    op.drop_table("leads")
