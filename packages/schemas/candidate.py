from typing import Any

from pydantic import BaseModel, Field

from packages.schemas.workflow import LiepinSearchConfig


class CandidateCard(BaseModel):
    source_candidate_id: str | None = None
    source_url: str | None = None
    display_name: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    work_years: float | None = None
    education: str | None = None
    city: str | None = None
    skills: list[str] = Field(default_factory=list)
    summary: str | None = None


class CandidateSnapshotData(BaseModel):
    workflow_id: str
    platform: str
    source_candidate_id: str | None = None
    source_url: str | None = None
    display_name: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    work_years: float | None = None
    education: str | None = None
    city: str | None = None
    skills: list[str] = Field(default_factory=list)
    summary: str | None = None
    experience_summary: str | None = None
    project_summary: str | None = None
    raw_text: str = ""
    extraction_confidence: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)
    template_type: str = "liepin_resume_detail_v2"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FetchInput(BaseModel):
    platform: str = "liepin"
    workflow_id: str
    start_url: str = "https://lpt.liepin.com/search"
    target_count: int = 50
    max_pages: int = 5
    detail_required: bool = True
    browser_profile: str = "hr_default"
    search: LiepinSearchConfig = Field(default_factory=LiepinSearchConfig)
    job_id: str | None = None
    job_title: str | None = None  # 开聊岗位弹窗匹配用
    job_description: str | None = None
    screening_criteria: str = ""
    screening_min_score: float = 60.0
    collect_only: bool = False
    collect_parent_group: str = ""


class FetchOutput(BaseModel):
    fetch_task_id: str
    workflow_id: str
    captured_count: int
    candidate_snapshot_ids: list[str]
    failed_items: list[dict[str, str]] = Field(default_factory=list)


class CandidateSnapshotResponse(BaseModel):
    id: str
    workflow_id: str
    platform: str
    source_candidate_id: str | None
    source_url: str | None
    display_name: str | None
    current_title: str | None
    current_company: str | None
    work_years: float | None
    education: str | None
    city: str | None
    skills: list[str]
    summary: str | None
    experience_summary: str | None
    project_summary: str | None
    raw_text: str
    extraction_confidence: float | None
    captured_at: str
