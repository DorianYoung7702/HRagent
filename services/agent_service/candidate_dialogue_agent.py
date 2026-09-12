"""Candidate-facing persistent IM dialogue agent.

This module is intentionally rule-first: candidate-visible replies are only
auto-sent when the answer is explicitly present in the job QA profile.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from packages.schemas.outreach import CandidateDialogueOutput

_QUESTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("salary", ("salary", "pay", "compensation", "薪", "薪资", "工资", "待遇")),
    (
        "work_location",
        ("location", "office", "where", "base", "workplace", "地址", "地点", "在哪", "办公", "城市"),
    ),
    (
        "responsibilities",
        ("responsibility", "responsibilities", "duties", "role", "做什么", "职责", "工作内容"),
    ),
    (
        "work_mode",
        ("remote", "onsite", "hybrid", "work mode", "工作模式", "远程", "坐班", "出差", "双休"),
    ),
    (
        "interview_process",
        ("interview", "process", "面试", "流程", "几轮", "多久反馈"),
    ),
    ("company_intro", ("company", "公司", "企业", "平台", "规模")),
    ("team_intro", ("team", "团队", "部门", "leader", "负责人")),
    ("start_time", ("start", "onboard", "入职", "到岗", "什么时候到岗")),
    ("recruiting_status", ("still open", "hiring", "还招", "还在招", "hc", "名额")),
)

_SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "salary": ("salary_range",),
    "work_location": ("work_location",),
    "responsibilities": ("responsibilities",),
    "work_mode": ("work_mode",),
    "interview_process": ("interview_process",),
    "company_intro": ("company_intro", "custom_notes"),
    "team_intro": ("team_intro", "custom_notes"),
    "start_time": ("start_time",),
    "recruiting_status": ("recruiting_status",),
}

_REPLY_LABELS = {
    "salary": "薪资范围",
    "work_location": "工作地点",
    "responsibilities": "岗位职责",
    "work_mode": "工作模式",
    "interview_process": "面试流程",
    "company_intro": "公司情况",
    "team_intro": "团队情况",
    "start_time": "到岗时间",
    "recruiting_status": "招聘状态",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_profile(profile: Mapping[str, Any] | None, workflow_config: Mapping[str, Any] | None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if workflow_config:
        cfg_profile = workflow_config.get("job_qa_profile")
        if isinstance(cfg_profile, Mapping):
            data.update(cfg_profile)
    if profile:
        data.update(dict(profile))
    return data


def _history_text(conversation_history: Sequence[Any]) -> str:
    lines: list[str] = []
    for item in conversation_history[-8:]:
        if isinstance(item, Mapping):
            direction = _text(item.get("direction"))
            text = _text(item.get("message_text") or item.get("text"))
            if text:
                lines.append(f"{direction}:{text}" if direction else text)
        else:
            text = _text(item)
            if text:
                lines.append(text)
    return "\n".join(lines)


def detect_question_type(message: str) -> str:
    text = _text(message).lower()
    if not text:
        return "unknown"
    for question_type, keywords in _QUESTION_RULES:
        if any(keyword.lower() in text for keyword in keywords):
            return question_type
    return "unknown"


def _answer_from_profile(profile: Mapping[str, Any], question_type: str) -> tuple[str, str]:
    for field in _SOURCE_FIELDS.get(question_type, ()):
        answer = _text(profile.get(field))
        if answer:
            return answer, f"job_qa_profile.{field}"
    return "", ""


def _safe_auto_reply(question_type: str, answer: str) -> str:
    label = _REPLY_LABELS.get(question_type, "岗位信息")
    return f"您好，这个岗位的{label}是：{answer}"


def generate_candidate_dialogue_reply(
    *,
    candidate_snapshot_id: str,
    latest_message: str,
    conversation_history: Sequence[Any],
    candidate_profile: Mapping[str, Any] | None,
    workflow_config: Mapping[str, Any] | None,
    job_qa_profile: Mapping[str, Any] | None,
    hr_preference_memory: Mapping[str, Any] | None,
) -> CandidateDialogueOutput:
    profile = _normalize_profile(job_qa_profile, workflow_config)
    question_type = detect_question_type(latest_message)
    history = _history_text(conversation_history or [])
    history_used = bool(history)

    if question_type == "unknown":
        return CandidateDialogueOutput(
            candidate_snapshot_id=candidate_snapshot_id,
            action="no_action",
            question_type="unknown",
            reason="Candidate message is not a whitelisted basic job question.",
            confidence=0.0,
            auto_send_allowed=False,
            history_used=history_used,
        )

    answer, source = _answer_from_profile(profile, question_type)
    if answer:
        return CandidateDialogueOutput(
            candidate_snapshot_id=candidate_snapshot_id,
            action="auto_reply",
            message_text=_safe_auto_reply(question_type, answer),
            question_type=question_type,
            answer_source=source,
            reason="Answer found in job QA profile.",
            confidence=0.95,
            auto_send_allowed=True,
            history_used=history_used,
        )

    label = _REPLY_LABELS.get(question_type, "这个问题")
    return CandidateDialogueOutput(
        candidate_snapshot_id=candidate_snapshot_id,
        action="escalate_to_hr",
        message_text=f"您好，{label}我这边再和 HR confirm 一下，确认后尽快回复您。",
        question_type=question_type,
        answer_source="",
        reason=f"No explicit answer found for {question_type}.",
        confidence=0.4,
        auto_send_allowed=False,
        history_used=history_used,
    )
