"""Tests for LPT screening merge and persistence mapping."""

from packages.schemas.screening import ResumeParseOutput, ScreeningDecisionOutput, VisaScreeningOutput
from services.agent_service.visa_screening_agent import merge_parse_and_decision, visa_result_to_screening


def test_merge_observe():
    parse = ResumeParseOutput(
        candidate_snapshot_id="s1",
        resume_summary="张三，深圳，5年海外销售，西班牙语流利，持美签。",
        highlights=["美签", "西班牙语", "销售经验"],
        parse_notes="从工作经历与技能栏提取。",
    )
    decision = ScreeningDecisionOutput(
        decision="观察",
        fit_score=92,
        score_rationale="硬性条件与销售经历充分匹配",
        reason="满足美签+西班牙语+销售三项标准",
        criteria_analysis="美签：有；西班牙语：有；销售：有",
        has_us_visa=True,
        has_spanish=True,
        has_sales=True,
    )
    merged = merge_parse_and_decision(parse, decision)
    assert merged.decision == "观察"
    assert merged.resume_summary == parse.resume_summary
    assert merged.reason == decision.reason

    out = visa_result_to_screening("s1", merged)
    assert out.level == "observe"
    assert out.total_score == 92
    assert out.score_detail["resume_summary"] == parse.resume_summary
    assert out.score_detail["reason"] == decision.reason


def test_merge_followup():
    parse = ResumeParseOutput(
        resume_summary="李四，有留学经历，西语销售背景，未写美签。",
        parse_notes="教育经历含海外院校。",
    )
    decision = ScreeningDecisionOutput(
        decision="追问",
        fit_score=71,
        score_rationale="核心经历匹配，但签证信息缺失",
        reason="无美签但有留学，需确认签证",
        criteria_analysis="美签：未提及；留学：有",
        followup_question="是否持有有效美签？",
        has_study_abroad=True,
    )
    merged = merge_parse_and_decision(parse, decision)
    out = visa_result_to_screening("s2", merged)
    assert out.level == "followup"
    assert out.total_score == 71
    assert "美签" in out.missing_info[0].question
    assert out.score_detail.get("followup_question") == "是否持有有效美签？"


def test_merge_exclude():
    visa = VisaScreeningOutput(
        decision="排除",
        fit_score=18,
        score_rationale="无相关经历",
        reason="不满足 HR 评判标准",
        resume_summary="王五，纯技术背景。",
        criteria_analysis="无销售与语言匹配",
    )
    out = visa_result_to_screening("s3", visa)
    assert out.level == "exclude"
    assert out.total_score == 18
    assert out.score_detail["reason"] == "不满足 HR 评判标准"
