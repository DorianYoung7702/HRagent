"""Tests for resume parse validation and merge."""

import pytest

from packages.schemas.screening import ResumeParseOutput, ScreeningDecisionOutput
from services.agent_service.agent_errors import AgentInferenceError
from services.agent_service.resume_parser_agent import validate_parse_output
from services.agent_service.screening_decision_agent import validate_decision_output
from services.agent_service.visa_screening_agent import merge_parse_and_decision


def test_validate_parse_requires_summary():
    with pytest.raises(AgentInferenceError, match="resume_summary"):
        validate_parse_output(ResumeParseOutput(parse_notes="ok"))


def test_validate_decision_requires_reason():
    with pytest.raises(AgentInferenceError, match="reason"):
        validate_decision_output(
            ScreeningDecisionOutput(decision="观察", criteria_analysis="分析", fit_score=80, score_rationale="匹配")
        )


def test_merge_preserves_ai_text():
    parse = ResumeParseOutput(
        resume_summary="AI 生成的总结内容",
        current_company="海康威视",
        parse_notes="AI 解析说明",
        highlights=["要点1"],
    )
    decision = ScreeningDecisionOutput(
        decision="排除",
        reason="AI 判定理由",
        criteria_analysis="AI 标准对照",
    )
    merged = merge_parse_and_decision(parse, decision)
    assert merged.resume_summary == "AI 生成的总结内容"
    assert merged.current_company == "海康威视"
    assert merged.reason == "AI 判定理由"
    assert merged.criteria_analysis == "AI 标准对照"
