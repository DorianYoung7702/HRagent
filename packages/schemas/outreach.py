from pydantic import BaseModel, Field


class OutreachMessageOutput(BaseModel):
    candidate_snapshot_id: str
    round: int
    message_text: str
    questions_asked: list[str] = Field(default_factory=list)
    wait_for_reply: bool = True
    next_expected_fields: list[str] = Field(default_factory=list)


class ReplyParserOutput(BaseModel):
    candidate_snapshot_id: str
    extracted_fields: dict = Field(default_factory=dict)
    answered_fields: list[str] = Field(default_factory=list)
    remaining_missing_fields: list[str] = Field(default_factory=list)
    candidate_intent: str = "unclear"  # interested / not_interested / unclear
    confidence: float = 0.0
    suggested_next_action: str = "wait"


class ReplyIngestionPayload(BaseModel):
    candidate_snapshot_id: str
    message_text: str
    platform_message_id: str | None = None


class FollowupConversationOutput(BaseModel):
    candidate_snapshot_id: str = ""
    action: str = "draft_message"  # draft_message | wait_reply | recommend_to_hr | reject | no_action
    message_text: str = ""
    questions_asked: list[str] = Field(default_factory=list)
    reason: str = ""
    auto_send_allowed: bool = False
    round: int = 1


class CandidateDialogueOutput(BaseModel):
    candidate_snapshot_id: str = ""
    action: str = "no_action"  # auto_reply | draft_only | escalate_to_hr | no_action
    message_text: str = ""
    question_type: str = "unknown"
    answer_source: str = ""
    reason: str = ""
    confidence: float = 0.0
    auto_send_allowed: bool = False
    history_used: bool = False


class FollowupReplyEnrichmentOutput(BaseModel):
    candidate_snapshot_id: str = ""
    extracted_fields: dict = Field(default_factory=dict)
    answered_fields: list[str] = Field(default_factory=list)
    updated_level: str = "followup"  # observe | followup | exclude
    need_resume_request: bool = False
    resume_request_reason: str = ""
    summary_for_list: str = ""
    remaining_missing_info: list[dict] = Field(default_factory=list)
    confidence: float = 0.0


class ReplySummaryCandidateOutput(BaseModel):
    candidate_snapshot_id: str = ""
    display_name: str | None = None
    rank: int = 0
    priority: str = "medium"  # high / medium / low
    recommendation: str = ""
    risk_points: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)
    followup_passed: bool = False
    score: float = Field(ge=0, le=100)


class ReplyJudgmentSummaryOutput(BaseModel):
    workflow_id: str = ""
    generated_at: str = ""
    ranked_candidates: list[ReplySummaryCandidateOutput] = Field(default_factory=list)
    summary: str = ""


class ResumeRequestOutput(BaseModel):
    candidate_snapshot_id: str = ""
    message_text: str = ""
    reason: str = ""


class OutreachMessageResponse(BaseModel):
    id: str
    conversation_id: str
    candidate_snapshot_id: str
    direction: str
    message_text: str
    status: str
    round: int | None = None
    created_at: str
