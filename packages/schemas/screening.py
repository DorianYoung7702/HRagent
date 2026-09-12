from typing import Any

from pydantic import BaseModel, Field


class MissingInfo(BaseModel):
    field: str
    question: str
    importance: str = "high"  # high / medium / low；LLM 偶发省略时默认 high


class ScreeningOutput(BaseModel):
    candidate_snapshot_id: str
    total_score: float
    level: str  # recommend / backup / reject / observe / exclude / followup
    score_detail: dict[str, Any] = Field(default_factory=dict)
    matched_points: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    missing_info: list[MissingInfo] = Field(default_factory=list)
    suggested_action: str = "ask_for_more_info"


class ResumeParseOutput(BaseModel):
    """解析 Agent：从在线简历提取结构化理解与总结。"""

    candidate_snapshot_id: str = ""
    resume_summary: str = ""
    current_company: str = ""  # 当前/最近雇主，仅公司名
    highlights: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    visa_info: str = ""
    sales_info: str = ""
    education_abroad: str = ""
    parse_notes: str = ""
    display_name: str = ""
    current_title: str = ""
    work_years: float | None = None
    education: str = ""
    city: str = ""
    skills: list[str] = Field(default_factory=list)
    experience_summary: str = ""
    project_summary: str = ""


class ScreeningDecisionOutput(BaseModel):
    """判定 Agent：对照 HR 标准输出观察/追问/排除。"""

    decision: str = "排除"  # 观察 | 排除 | 追问
    fit_score: float | None = Field(default=None, ge=0, le=100)
    score_rationale: str = ""
    reason: str = ""
    criteria_analysis: str = ""
    followup_question: str = ""
    has_us_visa: bool = False
    has_spanish: bool = False
    has_sales: bool = False
    has_study_abroad: bool = False


class VisaScreeningOutput(BaseModel):
    """LPT 初筛合并结果（解析 + 判定）。"""

    candidate_snapshot_id: str = ""
    has_us_visa: bool = False
    has_spanish: bool = False
    has_sales: bool = False
    has_study_abroad: bool = False
    decision: str = "排除"  # 观察 | 排除 | 追问
    fit_score: float | None = Field(default=None, ge=0, le=100)
    score_rationale: str = ""
    reason: str = ""
    resume_summary: str = ""
    current_company: str = ""
    followup_question: str = ""
    parse_highlights: list[str] = Field(default_factory=list)
    parse_notes: str = ""
    criteria_analysis: str = ""
    display_name: str = ""
    current_title: str = ""
    work_years: float | None = None
    education: str = ""
    city: str = ""
    skills: list[str] = Field(default_factory=list)
    experience_summary: str = ""
    project_summary: str = ""


class ShortlistCandidate(BaseModel):
    candidate_snapshot_id: str
    rank: int
    score: float
    level: str
    display_name: str | None = None
    matched_points: list[str] = Field(default_factory=list)
    missing_info: list[MissingInfo] = Field(default_factory=list)


class ScreeningBatchResult(BaseModel):
    workflow_id: str
    shortlist_id: str
    screened_count: int
    shortlist: list[ShortlistCandidate]
    results: list[ScreeningOutput]


class RescreeningOutput(BaseModel):
    candidate_snapshot_id: str
    old_score: float
    new_score: float
    level: str
    decision: str  # recommend_to_hr / ask_followup / reject / wait
    reasons: list[str] = Field(default_factory=list)
    remaining_missing_info: list[MissingInfo] = Field(default_factory=list)
