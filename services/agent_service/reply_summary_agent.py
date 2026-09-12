"""Final reply-judgment summary ranking agent."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic_ai import Agent

from packages.agent_context import hr_agent_system_prefix
from packages.candidate_identity import dedupe_candidate_records, snapshot_identity_key
from packages.db.repositories import CandidateRepository, ScreeningRepository, WorkflowRepository
from packages.db.session import async_session_factory
from packages.schemas.outreach import ReplyJudgmentSummaryOutput
from packages.screening_defaults import resolve_screening_criteria
from packages.workflow_events import emit
from services.agent_service.llm import get_deepseek_model
from services.fetch_worker.im_contact_match import candidate_display_name

SUMMARY_SYSTEM = hr_agent_system_prefix(
    extra_rules="""## 角色
你是招聘最终候选人总结排名 Agent。

## 任务
1. 对 observe（观察）与 followup（追问）候选人统一排序；追问项保留 level 标记。
2. 追问通过后升级为 observe 的候选人保留 followup_passed 标记。
3. 排序依据是 HR 招聘需求、候选人经验、追问补充信息、风险点和可沟通价值。
4. 每个候选人必须输出 0-100 的复核 score、推荐理由、风险点、沟通切入点；score 不能机械复用初筛分数。
5. 不要编造候选人没有提供的信息；信息不足时写成风险点。""",
)


def create_reply_summary_agent() -> Agent[None, ReplyJudgmentSummaryOutput]:
    return Agent(
        get_deepseek_model(),
        output_type=ReplyJudgmentSummaryOutput,
        system_prompt=SUMMARY_SYSTEM,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_display_name(snap) -> str | None:
    try:
        return candidate_display_name(snap)
    except AttributeError:
        return getattr(snap, "display_name", None)


async def list_reply_summary_candidates(
    workflow_id: str,
    *,
    candidate_levels: frozenset[str] = frozenset({"observe", "followup"}),
) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        candidate_repo = CandidateRepository(session)
        screening_repo = ScreeningRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError(f"Workflow not found: {workflow_id}")

        snapshots = await candidate_repo.list_by_workflow(workflow_id)
        rows: list[dict[str, Any]] = []
        for snap in snapshots:
            screening = await screening_repo.get_latest_for_candidate(workflow_id, snap.id)
            if not screening or screening.level not in candidate_levels:
                continue
            meta = snap.metadata_ or {}
            score_detail = screening.score_detail or {}
            followup_passed = bool(meta.get("followup_passed") or score_detail.get("followup_passed"))
            is_followup = screening.level == "followup" and not followup_passed
            rows.append(
                {
                    "candidate_snapshot_id": snap.id,
                    "display_name": _safe_display_name(snap),
                    "identity_key": snapshot_identity_key(snap, display_name=_safe_display_name(snap)),
                    "current_title": snap.current_title,
                    "current_company": snap.current_company,
                    "work_years": _as_float(snap.work_years),
                    "education": snap.education,
                    "city": snap.city,
                    "skills": snap.skills or [],
                    "summary": snap.summary,
                    "experience_summary": snap.experience_summary,
                    "project_summary": snap.project_summary,
                    "total_score": _as_float(screening.total_score),
                    "matched_points": screening.matched_points or [],
                    "gaps": screening.gaps or [],
                    "resume_summary": score_detail.get("resume_summary"),
                    "reason": score_detail.get("reason"),
                    "criteria_analysis": score_detail.get("criteria_analysis"),
                    "summary_for_list": score_detail.get("summary_for_list")
                    or meta.get("summary_for_list"),
                    "followup_passed": followup_passed,
                    "level": screening.level,
                    "pending_followup": is_followup,
                    "followup_summary": score_detail.get("followup_summary")
                    or meta.get("followup_summary"),
                    "captured_at": snap.captured_at.isoformat() if snap.captured_at else "",
                }
            )
        deduped = dedupe_candidate_records(
            rows,
            score_getter=lambda row: row.get("total_score"),
            captured_getter=lambda row: row.get("captured_at"),
        )
        return sorted(deduped, key=lambda row: row.get("total_score") or 0, reverse=True)


def _fallback_report(workflow_id: str, candidates: list[dict[str, Any]], summary: str | None = None) -> dict:
    ranked = []
    for index, c in enumerate(candidates, start=1):
        points = c.get("matched_points") or []
        gaps = c.get("gaps") or []
        recommendation = c.get("reason") or c.get("summary_for_list") or "进入候选列表，可优先联系确认意向。"
        ranked.append(
            {
                "candidate_snapshot_id": c["candidate_snapshot_id"],
                "display_name": c.get("display_name"),
                "rank": index,
                "priority": "high" if index <= 3 else "medium",
                "recommendation": recommendation,
                "risk_points": gaps[:3],
                "talking_points": points[:3],
                "followup_passed": bool(c.get("followup_passed")),
                "score": c.get("total_score"),
            }
        )
    return {
        "workflow_id": workflow_id,
        "generated_at": _utc_now(),
        "ranked_candidates": ranked,
        "summary": _render_report_summary(ranked, empty_summary=summary),
    }


def _priority_label(priority: str | None) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(priority or "", priority or "中")


def _plain_table_cell(value: object, *, limit: int = 90) -> str:
    text = str(value or "").replace("\n", " ").replace("|", "/").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _render_report_summary(
    ranked: list[dict[str, Any]],
    *,
    empty_summary: str | None = None,
) -> str:
    if not ranked:
        return empty_summary or "## 候选人排序总结报告\n\n本次暂无进入候选列表的人选。"

    lines = [
        "## 候选人排序总结报告",
        "",
        "### 整体说明",
        f"本次进入候选列表共 {len(ranked)} 位候选人，以下排序基于 HR 需求、候选人简历信息、追问补充信息、匹配度、风险点和沟通价值综合生成。",
        "",
        "### 最终排名",
        "",
        "| 排名 | 候选人 | 评分 | 优先级 | 推荐理由 |",
        "|:---:|:---|:---:|:---:|:---|",
    ]
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
        name = _plain_table_cell(item.get("display_name") or item.get("candidate_snapshot_id"))
        score = item.get("score")
        score_text = "-" if score is None else _plain_table_cell(score, limit=12)
        priority = _priority_label(item.get("priority"))
        recommendation = _plain_table_cell(item.get("recommendation"), limit=120)
        lines.append(f"| {index} | {name} | {score_text} | {priority} | {recommendation} |")

    lines.extend(["", "### 推进建议"])
    for item in ranked[:5]:
        name = _plain_table_cell(item.get("display_name") or item.get("candidate_snapshot_id"))
        recommendation = _plain_table_cell(item.get("recommendation"), limit=120)
        lines.append(f"- **{name}**：{recommendation or '建议优先确认岗位意向与关键硬性条件。'}")
    if len(ranked) > 5:
        lines.append(f"- 其余 {len(ranked) - 5} 位可作为备选池，按业务紧急度继续沟通。")

    return "\n".join(lines)


def _short_prompt_text(value: Any, *, limit: int = 700) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _candidate_prompt_payload(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for c in candidates:
        payload.append(
            {
                "candidate_snapshot_id": c.get("candidate_snapshot_id"),
                "display_name": c.get("display_name"),
                "total_score": c.get("total_score"),
                "work_years": c.get("work_years"),
                "education": c.get("education"),
                "city": c.get("city"),
                "current_title": c.get("current_title"),
                "current_company": c.get("current_company"),
                "resume_summary": _short_prompt_text(c.get("resume_summary"), limit=700),
                "reason": _short_prompt_text(c.get("reason"), limit=500),
                "criteria_analysis": _short_prompt_text(c.get("criteria_analysis"), limit=700),
                "summary_for_list": _short_prompt_text(c.get("summary_for_list"), limit=500),
                "matched_points": (c.get("matched_points") or [])[:8],
                "gaps": (c.get("gaps") or [])[:8],
                "followup_passed": bool(c.get("followup_passed")),
                "followup_summary": _short_prompt_text(c.get("followup_summary"), limit=400),
            }
        )
    return payload


def _normalize_report(
    workflow_id: str,
    candidates: list[dict[str, Any]],
    output: ReplyJudgmentSummaryOutput,
) -> dict:
    by_id = {c["candidate_snapshot_id"]: c for c in candidates}
    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for item in output.ranked_candidates or []:
        snap_id = item.candidate_snapshot_id
        if not snap_id or snap_id not in by_id or snap_id in seen:
            continue
        src = by_id[snap_id]
        ranked.append(
            {
                "candidate_snapshot_id": snap_id,
                "display_name": item.display_name or src.get("display_name"),
                "rank": len(ranked) + 1,
                "priority": item.priority or "medium",
                "recommendation": item.recommendation or src.get("reason") or "",
                "risk_points": item.risk_points or src.get("gaps") or [],
                "talking_points": item.talking_points or src.get("matched_points") or [],
                "followup_passed": bool(item.followup_passed or src.get("followup_passed")),
                "score": item.score if item.score is not None else src.get("total_score"),
            }
        )
        seen.add(snap_id)

    for src in candidates:
        snap_id = src["candidate_snapshot_id"]
        if snap_id in seen:
            continue
        ranked.append(
            {
                "candidate_snapshot_id": snap_id,
                "display_name": src.get("display_name"),
                "rank": len(ranked) + 1,
                "priority": "medium",
                "recommendation": src.get("reason") or src.get("summary_for_list") or "",
                "risk_points": src.get("gaps") or [],
                "talking_points": src.get("matched_points") or [],
                "followup_passed": bool(src.get("followup_passed")),
                "score": src.get("total_score"),
            }
        )

    return {
        "workflow_id": workflow_id,
        "generated_at": output.generated_at or _utc_now(),
        "ranked_candidates": ranked,
        "summary": _render_report_summary(ranked),
    }


def normalize_summary_report_payload(report: dict | None) -> dict | None:
    if not isinstance(report, dict):
        return None
    ranked = report.get("ranked_candidates")
    if not isinstance(ranked, list):
        return report
    normalized = dict(report)
    normalized["ranked_candidates"] = ranked
    normalized["summary"] = _render_report_summary(ranked)
    return normalized


async def persist_reply_judgment_summary_report(
    workflow_id: str,
    report: dict,
    *,
    config_key: str = "reply_judgment_summary_report",
) -> dict:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        merged = await wf_repo.patch_config(workflow_id, {config_key: report})
        await session.commit()
        return merged.get(config_key) or report


async def get_reply_judgment_summary_report(
    workflow_id: str,
    *,
    config_key: str = "reply_judgment_summary_report",
) -> dict | None:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError(f"Workflow not found: {workflow_id}")
        report = (wf.config or {}).get(config_key)
        return normalize_summary_report_payload(report if isinstance(report, dict) else None)


async def generate_reply_judgment_summary_report(
    workflow_id: str,
    *,
    should_stop: Callable[[], bool] | None = None,
    candidate_levels: frozenset[str] = frozenset({"observe", "followup"}),
    config_key: str = "reply_judgment_summary_report",
    event_category: str = "reply_judgment",
    prompt_candidate_limit: int = 40,
) -> dict | None:
    if should_stop and should_stop():
        return None

    candidates = await list_reply_summary_candidates(
        workflow_id,
        candidate_levels=candidate_levels,
    )
    if not candidates:
        report = _fallback_report(workflow_id, [])
        if should_stop and should_stop():
            return None
        await persist_reply_judgment_summary_report(workflow_id, report, config_key=config_key)
        return report

    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError(f"Workflow not found: {workflow_id}")
        job = (wf.config or {}).get("job") or {}
        criteria = resolve_screening_criteria(job.get("screening_criteria") or "")

    prompt_candidates = candidates[:max(1, prompt_candidate_limit)]
    remainder_note = ""
    if len(candidates) > len(prompt_candidates):
        remainder_note = (
            f"\n本次共有 {len(candidates)} 位候选人。请对以下按初筛分数靠前的 "
            f"{len(prompt_candidates)} 位精排；其余人选会由系统按初筛分数接续排序。"
        )

    prompt = f"""## HR 招聘需求
{criteria[:3000] or "未提供"}

## 进入候选列表的人选
{json.dumps(_candidate_prompt_payload(prompt_candidates), ensure_ascii=False, indent=2)}
{remainder_note}

请按优先级输出最终候选人排序和整体总结报告。每位输出候选人必须填写复核 score（0-100）。"""

    agent = create_reply_summary_agent()
    result = await agent.run(prompt)
    report = _normalize_report(workflow_id, candidates, result.output)
    if should_stop and should_stop():
        return None
    await persist_reply_judgment_summary_report(workflow_id, report, config_key=config_key)
    emit(
        "success",
        f"候选总结排名 Agent 完成：{len(report.get('ranked_candidates') or [])} 人",
        category=event_category,
        workflow_id=workflow_id,
        meta={"report_ready": True},
    )
    return report
