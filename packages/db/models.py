import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class RecruitingWorkflow(Base):
    __tablename__ = "recruiting_workflows"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    start_url: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False, default="CREATED")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    fetch_task_id: Mapped[str | None] = mapped_column(String)
    shortlist_id: Mapped[str | None] = mapped_column(String)
    temporal_workflow_id: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CandidateSnapshot(Base):
    __tablename__ = "candidate_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        String, ForeignKey("recruiting_workflows.id"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String, nullable=False)
    source_candidate_id: Mapped[str | None] = mapped_column(String)
    source_url: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String)
    current_title: Mapped[str | None] = mapped_column(String)
    current_company: Mapped[str | None] = mapped_column(String)
    work_years: Mapped[float | None] = mapped_column(Numeric)
    education: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    experience_summary: Mapped[str | None] = mapped_column(Text)
    project_summary: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    raw_text_hash: Mapped[str | None] = mapped_column(String, index=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Numeric)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CandidateSupplementalInfo(Base):
    __tablename__ = "candidate_supplemental_info"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(String, ForeignKey("recruiting_workflows.id"), index=True)
    candidate_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("candidate_snapshots.id"), index=True
    )
    source_channel: Mapped[str] = mapped_column(String, nullable=False)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CandidateProfileCurrent(Base):
    __tablename__ = "candidate_profiles_current"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    candidate_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("candidate_snapshots.id"), index=True
    )
    workflow_id: Mapped[str] = mapped_column(String, ForeignKey("recruiting_workflows.id"), index=True)
    merged_profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TalentArchiveProfile(Base):
    """Cross-workflow internal talent archive; never exposed in the console UI."""

    __tablename__ = "talent_archive_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    identity_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    platform: Mapped[str | None] = mapped_column(String)
    source_snapshot_id: Mapped[str | None] = mapped_column(String, index=True)
    latest_workflow_id: Mapped[str | None] = mapped_column(String, index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String, index=True)
    current_title: Mapped[str | None] = mapped_column(String, index=True)
    current_company: Mapped[str | None] = mapped_column(String)
    work_years: Mapped[float | None] = mapped_column(Numeric)
    education: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String, index=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    experience_summary: Mapped[str | None] = mapped_column(Text)
    project_summary: Mapped[str | None] = mapped_column(Text)
    resume_raw_text: Mapped[str] = mapped_column(Text, default="")
    profile_data: Mapped[dict] = mapped_column(JSON, default=dict)
    best_score: Mapped[float | None] = mapped_column(Numeric)
    last_score: Mapped[float | None] = mapped_column(Numeric)
    last_level: Mapped[str | None] = mapped_column(String)
    source_workflow_ids: Mapped[list] = mapped_column(JSON, default=list)
    first_archived_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_archived_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CandidateScreeningResult(Base):
    __tablename__ = "candidate_screening_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(String, ForeignKey("recruiting_workflows.id"), index=True)
    candidate_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("candidate_snapshots.id"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(String)
    screening_round: Mapped[int] = mapped_column(Integer, default=1)
    total_score: Mapped[float | None] = mapped_column(Numeric)
    level: Mapped[str | None] = mapped_column(String)
    score_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    matched_points: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    missing_info: Mapped[list] = mapped_column(JSON, default=list)
    suggested_action: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Shortlist(Base):
    __tablename__ = "shortlists"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(String, ForeignKey("recruiting_workflows.id"), index=True)
    job_id: Mapped[str | None] = mapped_column(String)
    total_candidates: Mapped[int | None] = mapped_column(Integer)
    selected_count: Mapped[int | None] = mapped_column(Integer)
    min_score: Mapped[float | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ShortlistCandidate(Base):
    __tablename__ = "shortlist_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    shortlist_id: Mapped[str] = mapped_column(String, ForeignKey("shortlists.id"), index=True)
    candidate_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("candidate_snapshots.id"), index=True
    )
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Numeric)
    level: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OutreachConversation(Base):
    __tablename__ = "outreach_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(String, ForeignKey("recruiting_workflows.id"), index=True)
    candidate_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("candidate_snapshots.id"), index=True
    )
    channel: Mapped[str] = mapped_column(String, nullable=False, default="im_center")
    conversation_type: Mapped[str] = mapped_column(String, nullable=False, default="followup")
    status: Mapped[str] = mapped_column(String, nullable=False, default="CREATED")
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    missing_info: Mapped[list] = mapped_column(JSON, default=list)
    im_contact_key: Mapped[str | None] = mapped_column(String)
    last_agent_reason: Mapped[str | None] = mapped_column(Text)
    need_resume_request: Mapped[bool] = mapped_column(Boolean, default=False)
    temporal_workflow_id: Mapped[str | None] = mapped_column(String)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("outreach_conversations.id"), index=True
    )
    candidate_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("candidate_snapshots.id"), index=True
    )
    direction: Mapped[str] = mapped_column(String, nullable=False)  # outbound / inbound
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="drafted")
    platform_message_id: Mapped[str | None] = mapped_column(String)
    extracted_fields: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    round: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
