"""将解析/判定 Agent 结果写入 workflow 日志控制台。"""

from __future__ import annotations

from packages.schemas.screening import ResumeParseOutput, ScreeningDecisionOutput, VisaScreeningOutput
from packages.workflow_events import emit
from services.agent_service.screening_display import format_screening_flag_text


def emit_resume_parse_logs(
    card_index: int,
    name: str | None,
    parse: ResumeParseOutput,
) -> None:
    label = name or "未知候选人"
    idx = card_index + 1
    emit(
        "info",
        f"#{idx} {label} — 解析 Agent 开始阅读在线简历",
        category="parse",
        meta={"card_index": card_index, "name": name, "phase": "start"},
    )
    emit(
        "info",
        f"#{idx} 【简历总结】{parse.resume_summary}",
        category="parse",
        meta={"card_index": card_index, "name": name, "phase": "summary", "summary": parse.resume_summary},
    )
    for h in parse.highlights:
        emit(
            "info",
            f"#{idx}   · {h}",
            category="parse",
            meta={"card_index": card_index, "phase": "highlight", "highlight": h},
        )
    if parse.languages:
        emit(
            "info",
            f"#{idx} 【语言】{', '.join(parse.languages)}",
            category="parse",
            meta={"card_index": card_index, "phase": "languages", "languages": parse.languages},
        )
    if parse.parse_notes:
        emit(
            "info",
            f"#{idx} 【解析说明】{parse.parse_notes}",
            category="parse",
            meta={"card_index": card_index, "phase": "notes", "parse_notes": parse.parse_notes},
        )
    emit(
        "success",
        f"#{idx} 解析 Agent 完成",
        category="parse",
        meta={"card_index": card_index, "name": name, "phase": "done"},
    )


def emit_decision_logs(
    card_index: int,
    name: str | None,
    decision: ScreeningDecisionOutput,
    *,
    parse: ResumeParseOutput | None = None,
    screening_criteria: str = "",
) -> None:
    label = name or "未知候选人"
    idx = card_index + 1
    flag_text = format_screening_flag_text(
        criteria_analysis=decision.criteria_analysis,
        parse=parse,
        legacy=decision,
        screening_criteria=screening_criteria,
    )
    suffix = f"  ({flag_text})" if flag_text else ""

    emit(
        "info",
        f"#{idx} {label} — 判定 Agent 对照 HR 标准",
        category="screen",
        meta={"card_index": card_index, "name": name, "phase": "start"},
    )
    if decision.criteria_analysis:
        emit(
            "info",
            f"#{idx} 【标准对照】{decision.criteria_analysis}",
            category="screen",
            meta={
                "card_index": card_index,
                "phase": "criteria_analysis",
                "criteria_analysis": decision.criteria_analysis,
            },
        )
    emit(
        "success" if decision.decision == "观察" else "info" if decision.decision == "追问" else "warn",
        f"#{idx} 【判定结果】{decision.decision}{suffix}",
        category="screen",
        meta={
            "card_index": card_index,
            "decision": decision.decision,
            "flag_text": flag_text,
            "phase": "decision",
        },
    )
    emit(
        "info",
        f"#{idx} 【判定理由】{decision.reason}",
        category="screen",
        meta={"card_index": card_index, "phase": "reason", "reason": decision.reason},
    )
    if decision.decision == "追问" and decision.followup_question:
        emit(
            "info",
            f"#{idx} 【待追问】{decision.followup_question}",
            category="screen",
            meta={"card_index": card_index, "phase": "followup", "followup": decision.followup_question},
        )


def emit_screening_complete(
    card_index: int,
    name: str | None,
    result: VisaScreeningOutput,
) -> None:
    idx = card_index + 1
    emit(
        "success",
        f"#{idx} {name or '未知'} 初筛完成 → 【{result.decision}】",
        category="screen",
        meta={
            "card_index": card_index,
            "name": name,
            "decision": result.decision,
            "summary": result.resume_summary,
            "reason": result.reason,
            "parse_notes": result.parse_notes,
            "criteria_analysis": result.criteria_analysis,
            "phase": "complete",
        },
    )
