import logging
import re

from pydantic_ai import Agent
from packages.schemas.screening import MissingInfo, ScreeningOutput, VisaScreeningOutput
from packages.screening_defaults import DEFAULT_FOLLOWUP_QUESTION, DEFAULT_SCREENING_CRITERIA
from services.agent_service.llm import get_deepseek_model

logger = logging.getLogger(__name__)


def build_screening_system_prompt(screening_criteria: str = "") -> str:
    criteria = (screening_criteria or "").strip() or DEFAULT_SCREENING_CRITERIA
    return f"""你是招聘初筛助手。根据在线简历内容与 HR 评判标准输出结构化判断。

## HR 评判标准（必须严格遵循，决定 observation/追问/排除）
{criteria}

## 输出字段
- decision：观察 | 追问 | 排除（三选一，严格按 HR 标准）
- fit_score：0-100 的综合匹配分，按证据充分度和岗位匹配度给分，不能按 decision 固定赋值
- score_rationale：评分的主要加分与扣分依据
- has_us_visa：简历是否体现美签/美国签证
- has_spanish：是否体现西班牙语能力
- has_sales：是否体现销售/商务经验
- has_study_abroad：是否有留学/海外就读经历
- followup_question：decision=追问时，写出需向候选人确认的问题
- resume_summary：3-5句在线简历总结（不编造）
- reason：一句话说明判断依据，对照 HR 标准逐项说明"""

_VISA_POSITIVE = re.compile(
    r"美签|美国签证|B1/?B2|H1B|H-1B|L1签证|持美签|有美签|valid\s*us\s*visa",
    re.I,
)
_VISA_NEGATIVE = re.compile(r"无美签|没有美签|无美国签证|没有美国签证", re.I)
_SPANISH = re.compile(r"西班牙语|西语|DELE|Spanish|español|拉美语", re.I)
_SALES = re.compile(r"海外销售|销售|商务|客户经理|B2B|渠道|市场拓展|business\s+development", re.I)
_STUDY_ABROAD = re.compile(
    r"留学|海外留学|出国留学|交换生|访学|海外就读|留美|留欧|赴美留学|赴.*?留学",
    re.I,
)
_STUDY_ABROAD_NEGATIVE = re.compile(r"无留学|没有留学|未留学|无海外留学|没有海外留学", re.I)

def create_visa_screening_agent(
    model_name: str | None = None,
    screening_criteria: str = "",
) -> Agent[None, VisaScreeningOutput]:
    model = get_deepseek_model(model_name) if model_name else get_deepseek_model()
    prompt = build_screening_system_prompt(screening_criteria)
    return Agent(model, output_type=VisaScreeningOutput, system_prompt=prompt)


def _detect_flags(text: str) -> dict[str, bool]:
    if _VISA_NEGATIVE.search(text):
        has_visa = False
    else:
        has_visa = bool(_VISA_POSITIVE.search(text))
    if _STUDY_ABROAD_NEGATIVE.search(text):
        has_study_abroad = False
    else:
        has_study_abroad = bool(_STUDY_ABROAD.search(text))
    return {
        "has_us_visa": has_visa,
        "has_spanish": bool(_SPANISH.search(text)),
        "has_sales": bool(_SALES.search(text)),
        "has_study_abroad": has_study_abroad,
    }


def _uses_legacy_rules(screening_criteria: str) -> bool:
    c = (screening_criteria or "").strip()
    if not c:
        return True
    legacy_markers = ("美签", "西班牙语", "销售", "留学")
    return all(m in c for m in legacy_markers)


def finalize_screening_output(output: VisaScreeningOutput) -> VisaScreeningOutput:
    """校验 AI 输出，不覆盖自定义标准下的 decision。"""
    if output.decision not in ("观察", "追问", "排除"):
        output.decision = "排除"
    if output.decision == "追问" and not output.followup_question:
        output.followup_question = DEFAULT_FOLLOWUP_QUESTION
    if not output.reason:
        parts = [
            f"美签:{'有' if output.has_us_visa else '无'}",
            f"西班牙语:{'有' if output.has_spanish else '无'}",
            f"销售:{'有' if output.has_sales else '无'}",
            f"留学:{'有' if output.has_study_abroad else '无'}",
        ]
        output.reason = "；".join(parts)
    return output


def apply_decision_rules(output: VisaScreeningOutput) -> VisaScreeningOutput:
    """代码层强制决策（仅默认美签+西语+销售规则兜底）。"""
    if output.has_us_visa and output.has_spanish and output.has_sales:
        output.decision = "观察"
    elif not output.has_us_visa and output.has_study_abroad:
        output.decision = "追问"
        if not output.followup_question:
            output.followup_question = DEFAULT_FOLLOWUP_QUESTION
    else:
        output.decision = "排除"

    if not output.reason:
        parts = [
            f"美签:{'有' if output.has_us_visa else '无'}",
            f"西班牙语:{'有' if output.has_spanish else '无'}",
            f"销售:{'有' if output.has_sales else '无'}",
            f"留学:{'有' if output.has_study_abroad else '无'}",
        ]
        output.reason = "；".join(parts)
    return output


def _score_detail_base(visa: VisaScreeningOutput) -> dict:
    return {
        "has_us_visa": visa.has_us_visa,
        "has_spanish": visa.has_spanish,
        "has_sales": visa.has_sales,
        "has_study_abroad": visa.has_study_abroad,
        "decision": visa.decision,
        "fit_score": visa.fit_score,
        "score_rationale": visa.score_rationale,
        "reason": visa.reason,
        "followup_question": visa.followup_question,
        "resume_summary": visa.resume_summary,
        "parse_highlights": visa.parse_highlights,
        "parse_notes": visa.parse_notes,
        "criteria_analysis": visa.criteria_analysis,
        "current_company": visa.current_company,
        "screening_mode": "lpt_parse_decide",
    }


def merge_parse_and_decision(parse, decision) -> VisaScreeningOutput:
    from packages.schemas.screening import ResumeParseOutput, ScreeningDecisionOutput

    p: ResumeParseOutput = parse
    d: ScreeningDecisionOutput = decision
    return VisaScreeningOutput(
        candidate_snapshot_id=p.candidate_snapshot_id,
        resume_summary=p.resume_summary,
        current_company=(p.current_company or "").strip(),
        parse_highlights=p.highlights,
        parse_notes=p.parse_notes,
        display_name=(p.display_name or "").strip(),
        current_title=(p.current_title or "").strip(),
        work_years=p.work_years,
        education=(p.education or "").strip(),
        city=(p.city or "").strip(),
        skills=p.skills,
        experience_summary=(p.experience_summary or "").strip(),
        project_summary=(p.project_summary or "").strip(),
        criteria_analysis=d.criteria_analysis,
        decision=d.decision,
        fit_score=d.fit_score,
        score_rationale=d.score_rationale,
        reason=d.reason,
        followup_question=d.followup_question,
        has_us_visa=d.has_us_visa,
        has_spanish=d.has_spanish,
        has_sales=d.has_sales,
        has_study_abroad=d.has_study_abroad,
    )


def visa_result_to_screening(snap_id: str, visa: VisaScreeningOutput) -> ScreeningOutput:
    fit_score = float(visa.fit_score or 0)
    if visa.decision == "观察":
        return ScreeningOutput(
            candidate_snapshot_id=snap_id,
            total_score=fit_score,
            level="observe",
            score_detail=_score_detail_base(visa),
            matched_points=[visa.reason],
            suggested_action="contact_now",
        )

    if visa.decision == "追问":
        question = (visa.followup_question or "").strip() or DEFAULT_FOLLOWUP_QUESTION
        gap_field = "followup"
        if "西语" in question or "西班牙语" in question:
            gap_field = "spanish_work_language"
        elif "美签" in question or "签证" in question:
            gap_field = "us_visa"
        return ScreeningOutput(
            candidate_snapshot_id=snap_id,
            total_score=fit_score,
            level="followup",
            score_detail=_score_detail_base(visa),
            matched_points=[visa.reason or "部分满足 HR 标准，需追问确认"],
            gaps=[visa.reason or "待追问确认"],
            missing_info=[
                MissingInfo(field=gap_field, question=question, importance="high"),
            ],
            suggested_action="ask_for_more_info",
        )

    return ScreeningOutput(
        candidate_snapshot_id=snap_id,
        total_score=fit_score,
        level="exclude",
        score_detail=_score_detail_base(visa),
        gaps=[visa.reason or "不满足 HR 评判标准"],
        suggested_action="reject",
    )


def build_resume_summary(candidate_fields: dict, resume_text: str = "") -> str:
    parts = [
        candidate_fields.get("display_name") or "未知姓名",
        candidate_fields.get("current_title") or "",
        f"{candidate_fields.get('work_years')}年经验" if candidate_fields.get("work_years") else "",
        candidate_fields.get("city") or "",
        candidate_fields.get("education") or "",
        (candidate_fields.get("experience_summary") or resume_text[:200] or "")[:200],
    ]
    return "；".join(p for p in parts if p)


def rule_based_visa_screen(
    candidate_snapshot_id: str,
    resume_text: str,
    candidate_fields: dict,
    screening_criteria: str = "",
) -> VisaScreeningOutput:
    text = resume_text or ""
    summary = build_resume_summary(candidate_fields, text)
    flags = _detect_flags(text)

    output = VisaScreeningOutput(
        candidate_snapshot_id=candidate_snapshot_id,
        resume_summary=summary,
        **flags,
    )
    if _uses_legacy_rules(screening_criteria):
        return apply_decision_rules(output)
    output.decision = "排除"
    output.reason = output.reason or "规则兜底仅支持默认评判标准，请检查 AI 配置"
    return finalize_screening_output(output)


def _normalize_visa_output(
    output: VisaScreeningOutput,
    candidate_fields: dict,
    resume_text: str,
    screening_criteria: str = "",
) -> VisaScreeningOutput:
    text = resume_text or ""
    flags = _detect_flags(text)
    output.has_us_visa = output.has_us_visa or flags["has_us_visa"]
    output.has_spanish = output.has_spanish or flags["has_spanish"]
    output.has_sales = output.has_sales or flags["has_sales"]
    output.has_study_abroad = output.has_study_abroad or flags["has_study_abroad"]

    if not output.resume_summary:
        output.resume_summary = build_resume_summary(candidate_fields, resume_text)

    if _uses_legacy_rules(screening_criteria):
        output = apply_decision_rules(output)
    else:
        output = finalize_screening_output(output)
    return output


async def screen_visa_only(
    candidate_snapshot_id: str,
    resume_text: str,
    candidate_fields: dict,
    screening_criteria: str = "",
    *,
    card_index: int | None = None,
    display_name: str | None = None,
) -> VisaScreeningOutput:
    """两阶段初筛：解析 Agent → 判定 Agent（无规则兜底，AI 失败即抛错）。"""
    from services.agent_service.agent_errors import AgentInferenceError
    from services.agent_service.resume_parser_agent import parse_resume_online
    from services.agent_service.screening_decision_agent import decide_candidate
    from services.agent_service.screening_log import (
        emit_decision_logs,
        emit_resume_parse_logs,
        emit_screening_complete,
    )

    criteria = (screening_criteria or "").strip() or DEFAULT_SCREENING_CRITERIA
    name = display_name or candidate_fields.get("display_name")

    parse_out = await parse_resume_online(candidate_snapshot_id, resume_text, candidate_fields)
    if card_index is not None:
        emit_resume_parse_logs(card_index, name, parse_out)

    decision_out = await decide_candidate(parse_out, resume_text, criteria)
    if card_index is not None:
        emit_decision_logs(
            card_index,
            name,
            decision_out,
            parse=parse_out,
            screening_criteria=criteria,
        )

    result = merge_parse_and_decision(parse_out, decision_out)
    if not result.resume_summary.strip() or not result.reason.strip():
        raise AgentInferenceError("AI 初筛结果缺少简历总结或判定理由")

    if card_index is not None:
        emit_screening_complete(card_index, name, result)
    return result


