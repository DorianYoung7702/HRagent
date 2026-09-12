"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recruiting_workflows",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("start_url", sa.Text(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("fetch_task_id", sa.String(), nullable=True),
        sa.Column("shortlist_id", sa.String(), nullable=True),
        sa.Column("temporal_workflow_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "candidate_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("source_candidate_id", sa.String(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("current_title", sa.String(), nullable=True),
        sa.Column("current_company", sa.String(), nullable=True),
        sa.Column("work_years", sa.Numeric(), nullable=True),
        sa.Column("education", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("skills", postgresql.JSONB(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("experience_summary", sa.Text(), nullable=True),
        sa.Column("project_summary", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("raw_text_hash", sa.String(), nullable=True),
        sa.Column("extraction_confidence", sa.Numeric(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["recruiting_workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_snapshots_workflow_id", "candidate_snapshots", ["workflow_id"])
    op.create_index("ix_candidate_snapshots_raw_text_hash", "candidate_snapshots", ["raw_text_hash"])

    op.create_table(
        "candidate_supplemental_info",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("candidate_snapshot_id", sa.String(), nullable=False),
        sa.Column("source_channel", sa.String(), nullable=False),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("extracted_fields", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["recruiting_workflows.id"]),
        sa.ForeignKeyConstraint(["candidate_snapshot_id"], ["candidate_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "candidate_profiles_current",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("candidate_snapshot_id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("merged_profile", postgresql.JSONB(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["candidate_snapshot_id"], ["candidate_snapshots.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["recruiting_workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "candidate_screening_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("candidate_snapshot_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("screening_round", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Numeric(), nullable=True),
        sa.Column("level", sa.String(), nullable=True),
        sa.Column("score_detail", postgresql.JSONB(), nullable=True),
        sa.Column("matched_points", postgresql.JSONB(), nullable=True),
        sa.Column("gaps", postgresql.JSONB(), nullable=True),
        sa.Column("missing_info", postgresql.JSONB(), nullable=True),
        sa.Column("suggested_action", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["recruiting_workflows.id"]),
        sa.ForeignKeyConstraint(["candidate_snapshot_id"], ["candidate_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "shortlists",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("total_candidates", sa.Integer(), nullable=True),
        sa.Column("selected_count", sa.Integer(), nullable=True),
        sa.Column("min_score", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["recruiting_workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "shortlist_candidates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("shortlist_id", sa.String(), nullable=False),
        sa.Column("candidate_snapshot_id", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Numeric(), nullable=True),
        sa.Column("level", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["shortlist_id"], ["shortlists.id"]),
        sa.ForeignKeyConstraint(["candidate_snapshot_id"], ["candidate_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "outreach_conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("candidate_snapshot_id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_round", sa.Integer(), nullable=False),
        sa.Column("missing_info", postgresql.JSONB(), nullable=True),
        sa.Column("temporal_workflow_id", sa.String(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("last_reply_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["recruiting_workflows.id"]),
        sa.ForeignKeyConstraint(["candidate_snapshot_id"], ["candidate_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "outreach_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("candidate_snapshot_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("platform_message_id", sa.String(), nullable=True),
        sa.Column("extracted_fields", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["outreach_conversations.id"]),
        sa.ForeignKeyConstraint(["candidate_snapshot_id"], ["candidate_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("outreach_messages")
    op.drop_table("outreach_conversations")
    op.drop_table("shortlist_candidates")
    op.drop_table("shortlists")
    op.drop_table("candidate_screening_results")
    op.drop_table("candidate_profiles_current")
    op.drop_table("candidate_supplemental_info")
    op.drop_index("ix_candidate_snapshots_raw_text_hash", table_name="candidate_snapshots")
    op.drop_index("ix_candidate_snapshots_workflow_id", table_name="candidate_snapshots")
    op.drop_table("candidate_snapshots")
    op.drop_table("recruiting_workflows")
