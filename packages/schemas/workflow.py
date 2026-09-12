from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RecruitingWorkflowStatus(str, Enum):
    CREATED = "CREATED"
    FETCHING = "FETCHING"
    FETCH_COMPLETED = "FETCH_COMPLETED"
    SCREENING = "SCREENING"
    SCREENING_COMPLETED = "SCREENING_COMPLETED"
    CONVERSATIONS_STARTED = "CONVERSATIONS_STARTED"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"


class ConversationStatus(str, Enum):
    CREATED = "CREATED"
    MISSING_INFO_DETECTED = "MISSING_INFO_DETECTED"
    MESSAGE_DRAFTED = "MESSAGE_DRAFTED"
    MESSAGE_SENT = "MESSAGE_SENT"
    WAITING_REPLY = "WAITING_REPLY"
    REPLY_RECEIVED = "REPLY_RECEIVED"
    REPLY_PARSED = "REPLY_PARSED"
    PROFILE_UPDATED = "PROFILE_UPDATED"
    RESCREENED = "RESCREENED"
    FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"
    READY_FOR_HR = "READY_FOR_HR"
    AUTO_REPLY_SENT = "AUTO_REPLY_SENT"
    DRAFT_READY = "DRAFT_READY"
    NEEDS_HR = "NEEDS_HR"
    NO_REPLY = "NO_REPLY"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class LptEducationFilters(BaseModel):
    degree: str = ""
    school_tiers: list[str] = Field(default_factory=list)


class LptOtherFilters(BaseModel):
    activity: str = ""
    job_seeking: str = ""
    job_hop: str = ""
    age: str = ""
    gender: str = ""
    language: str = ""
    grad_industry: str = ""
    current_industry: str = ""
    expected_industry: str = ""


class LiepinSearchConfig(BaseModel):
    mode: str = "url_direct"  # lpt_search | url_direct
    keywords: str = "西班牙语 美签 海外销售"
    city: str = "深圳"
    cities: list[str] = Field(default_factory=list)  # 期望城市多选，最多 5 个
    current_cities: list[str] = Field(default_factory=list)  # 目前/当前城市
    experience: str = "3-5年"
    education: LptEducationFilters = Field(default_factory=LptEducationFilters)
    other_filters: LptOtherFilters = Field(default_factory=LptOtherFilters)
    entry_url: str = "https://lpt.liepin.com/search"
    auto_screen: bool = False


class FetchConfig(BaseModel):
    target_count: int = 50
    max_pages: int = 5
    detail_required: bool = True
    browser_profile: str = "hr_default"
    collect_only: bool = False
    collect_parent_group: str = ""
    search: LiepinSearchConfig = Field(default_factory=LiepinSearchConfig)


class JobConfig(BaseModel):
    job_id: str
    description: str
    title: str | None = None
    requirements: list[str] = Field(default_factory=list)
    screening_criteria: str = ""  # HR 评判标准，用于拿到简历后 AI 初筛


class ScreeningConfig(BaseModel):
    top_k: int = 10
    min_score: float = 70.0


class OutreachConfig(BaseModel):
    enabled: bool = True
    send_mode: str = "draft_first"  # draft_first | auto_send
    im_review_required: bool = False  # True = all IM outbound stay drafted until HR sends
    max_rounds: int = 3
    reply_timeout_days: int = 2


class JobQaProfile(BaseModel):
    responsibilities: str = ""
    work_location: str = ""
    salary_range: str = ""
    work_mode: str = ""
    interview_process: str = ""
    company_intro: str = ""
    team_intro: str = ""
    start_time: str = ""
    recruiting_status: str = ""
    custom_notes: str = ""


class JobQaProfileUpdateRequest(BaseModel):
    profile: JobQaProfile


class RecruitingWorkflowCreate(BaseModel):
    name: str
    platform: str = "liepin"
    start_url: str = "https://lpt.liepin.com/search"
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    job: JobConfig
    screening: ScreeningConfig = Field(default_factory=ScreeningConfig)
    outreach: OutreachConfig = Field(default_factory=OutreachConfig)
    job_qa_profile: JobQaProfile | None = None


class SearchIntentRequest(BaseModel):
    """统一输入 unified_requirement 时，Agent 从一段话拆出搜索词/筛选/HR 偏好。"""

    unified_requirement: str = ""
    search_requirement: str = ""
    screening_criteria: str = ""  # HR 评判标准（简历抽取后 AI 判定用）
    position_name: str = ""  # 主页筛选需求岗位名；锁定 title / 开聊岗位，AI 不推断


class SearchIntentOutput(BaseModel):
    keywords: str
    city: str = "深圳"
    cities: list[str] = Field(default_factory=list)
    current_cities: list[str] = Field(default_factory=list)
    experience: str = "3-5年"
    education: LptEducationFilters = Field(default_factory=LptEducationFilters)
    other_filters: LptOtherFilters = Field(default_factory=LptOtherFilters)
    target_count: int = 20
    search_requirement: str = ""  # 用户提交给解析 Agent 的原始需求（对照用）
    screening_criteria: str = ""
    job_description: str = ""
    chat_job_title: str = ""  # 立即开聊弹窗内要匹配的岗位名
    name: str = "AI 筛选任务"
    parse_summary: str = ""


class HRPreferenceMemory(BaseModel):
    must_have: list[str] = Field(default_factory=list)
    quick_reject_rules: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    reject_rules: list[str] = Field(default_factory=list)
    followup_questions: list[str] = Field(default_factory=list)
    preference_summary: str = ""
    screening_criteria: str = ""
    assistant_message: str = ""
    ready: bool = False
    criteria_version: int = 1


class HRPreferenceMemoryRequest(BaseModel):
    current_requirement: str = ""
    parsed_intent: dict[str, Any] = Field(default_factory=dict)
    screening_criteria: str = ""
    preset_memory: HRPreferenceMemory | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)


class HRPreferenceChatRequest(HRPreferenceMemoryRequest):
    pass


class HRPreferenceUpdateRequest(BaseModel):
    memory: HRPreferenceMemory
    apply_to_platform_group: bool = True


class ConsoleStartRequest(BaseModel):
    """Console start: parsed intent with optional overrides."""

    platforms: list[str] = Field(default_factory=lambda: ["liepin"])
    search_requirement: str = ""
    screening_criteria: str = ""
    keywords: str
    city: str = "深圳"
    cities: list[str] = Field(default_factory=list)
    current_cities: list[str] = Field(default_factory=list)
    experience: str = "3-5年"
    education: LptEducationFilters = Field(default_factory=LptEducationFilters)
    other_filters: LptOtherFilters = Field(default_factory=LptOtherFilters)
    target_count: int = 20
    job_description: str = ""
    chat_job_title: str = ""
    name: str = "AI 筛选任务"
    parse_summary: str = ""
    job_id: str = "console_search"
    min_score: float = 60.0
    top_k: int = 10
    collect_only: bool = False
    im_review_required: bool = False
    collect_parent_group: str = ""
    preset_id: str = ""
    preset_label: str = ""
    hr_preference_memory: HRPreferenceMemory | None = None
    job_qa_profile: JobQaProfile | None = None


class PdfImportStartRequest(BaseModel):
    """一次性 PDF 导入任务的岗位与筛选配置，不包含任何文件信息。"""

    name: str = "PDF 简历筛选"
    job_id: str = "local_pdf_import"
    job_description: str = ""
    screening_criteria: str = ""
    min_score: float = 60.0
    top_k: int = 10
    preset_id: str = ""
    preset_label: str = ""
    hr_preference_memory: HRPreferenceMemory | None = None


class WorkflowRuntimeOptionsUpdate(BaseModel):
    """运行中可切换：仅收藏 / IM 是否自动回复。"""

    collect_only: bool | None = None
    im_auto_reply: bool | None = None  # True=自动发送；False=人工确认后再发


class LiepinLptDemoRequest(BaseModel):
    name: str = "拉美中方销售"
    keywords: str = "西班牙语 美签 海外销售"
    city: str = "深圳"
    cities: list[str] = Field(default_factory=list)
    current_cities: list[str] = Field(default_factory=list)
    experience: str = "3-5年"
    education: LptEducationFilters = Field(default_factory=LptEducationFilters)
    other_filters: LptOtherFilters = Field(default_factory=LptOtherFilters)
    target_count: int = 20
    job_id: str = "demo_latam_sales"
    job_description: str = "岗位：拉美中方销售。要求西班牙语工作语言、拉美市场及电子类产品销售经验。"
    chat_job_title: str = ""
    screening_criteria: str = ""  # 运行时空值回退见 packages.screening_defaults
    min_score: float = 60.0
    top_k: int = 3
    collect_only: bool = False
    im_review_required: bool = False
    collect_parent_group: str = ""
    job_qa_profile: JobQaProfile | None = None


class RecruitingWorkflowConfig(BaseModel):
    workflow_id: str
    name: str
    platform: str
    start_url: str
    fetch: FetchConfig
    job: JobConfig
    screening: ScreeningConfig
    outreach: OutreachConfig


class WorkflowLogSummary(BaseModel):
    event_count: int = 0
    last_message: str = ""
    last_ts: str | None = None
    last_level: str = "info"
    persisted: bool = False


class RecruitingWorkflowResponse(BaseModel):
    id: str
    name: str
    platform: str
    start_url: str
    status: RecruitingWorkflowStatus
    config: dict[str, Any]
    fetch_task_id: str | None = None
    shortlist_id: str | None = None
    created_at: datetime
    updated_at: datetime
    log_summary: WorkflowLogSummary | None = None


class CandidateConversationInput(BaseModel):
    workflow_id: str
    candidate_snapshot_id: str
    screening_result: dict[str, Any]
    outreach_config: OutreachConfig


class ConversationState(BaseModel):
    conversation_id: str
    candidate_snapshot_id: str
    workflow_id: str
    status: ConversationStatus = ConversationStatus.CREATED
    round: int = 0
    missing_info: list[dict[str, Any]] = Field(default_factory=list)
    decision: str | None = None
    latest_score: float | None = None
    level: str | None = None


class HRReportCandidate(BaseModel):
    candidate_snapshot_id: str
    display_name: str | None
    total_score: float
    level: str
    decision: str
    matched_points: list[str]
    reasons: list[str]


class HRReport(BaseModel):
    workflow_id: str
    job_id: str
    generated_at: datetime
    total_candidates: int
    recommended: list[HRReportCandidate]
    backup: list[HRReportCandidate]
    rejected_count: int
    summary: str
