from __future__ import annotations

import logging
from hashlib import sha256
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from packages.candidate_identity import snapshot_identity_key
from packages.db.repositories import CandidateRepository, ScreeningRepository, WorkflowRepository
from packages.db.session import async_session_factory
from packages.schemas.screening import (
    MissingInfo,
    ScreeningBatchResult,
    ScreeningOutput,
    ShortlistCandidate,
    VisaScreeningOutput,
)
from packages.schemas.workflow import RecruitingWorkflowConfig
from services.agent_service.screening_agent import screen_candidate
from services.agent_service.visa_screening_agent import screen_visa_only, visa_result_to_screening

if TYPE_CHECKING:
    from packages.schemas.candidate import CandidateSnapshotData

logger = logging.getLogger(__name__)

RANKABLE_LEVELS = frozenset({"observe", "followup"})


def _collect_rankable_screening(
    results: list[ScreeningOutput],
    *,
    min_score: float,
) -> list[ScreeningOutput]:
    """观察 + 追问统一按分数排序（追问始终参与，观察需达到 min_score）。"""
    ranked: list[ScreeningOutput] = []
    for r in results:
        if r.level not in RANKABLE_LEVELS:
            continue
        if r.level == "observe" and float(r.total_score or 0) < min_score:
            continue
        ranked.append(r)
    ranked.sort(key=lambda r: float(r.total_score or 0), reverse=True)
    return ranked


async def _shortlist_candidates_from_results(
    results: list[ScreeningOutput],
    *,
    candidate_repo: CandidateRepository,
    min_score: float,
    top_k: int,
) -> list[ShortlistCandidate]:
    ranked = _collect_rankable_screening(results, min_score=min_score)[:top_k]
    shortlist_candidates: list[ShortlistCandidate] = []
    for rank, r in enumerate(ranked, start=1):
        snap = await candidate_repo.get(r.candidate_snapshot_id)
        shortlist_candidates.append(
            ShortlistCandidate(
                candidate_snapshot_id=r.candidate_snapshot_id,
                rank=rank,
                score=r.total_score,
                level=r.level,
                display_name=snap.display_name if snap else None,
                matched_points=r.matched_points,
                missing_info=r.missing_info,
            )
        )
    return shortlist_candidates


def screening_criteria_hash(screening_criteria: str) -> str:
    return sha256((screening_criteria or "").encode("utf-8")).hexdigest()[:16]


def _criteria_context_from_config(config: dict | None, fallback: str = "") -> tuple[str, int]:
    cfg = dict(config or {})
    initial_criteria = str(cfg.get("initial_screening_criteria") or "").strip()
    if initial_criteria:
        try:
            initial_version = max(1, int(cfg.get("initial_criteria_version") or 1))
        except (TypeError, ValueError):
            initial_version = 1
        return initial_criteria, initial_version

    job = dict(cfg.get("job") or {})
    memory = dict(cfg.get("hr_preference_memory") or {})
    criteria = (
        job.get("screening_criteria")
        or memory.get("screening_criteria")
        or fallback
        or ""
    )
    version = cfg.get("criteria_version") or memory.get("criteria_version") or 1
    try:
        version_int = max(1, int(version))
    except (TypeError, ValueError):
        version_int = 1
    return str(criteria or ""), version_int


async def resolve_workflow_screening_context(
    workflow_id: str,
    fallback: str = "",
    *,
    session: AsyncSession | None = None,
) -> tuple[str, int]:
    if session is not None:
        wf = await WorkflowRepository(session).get(workflow_id)
        return _criteria_context_from_config(wf.config if wf else None, fallback)

    async with async_session_factory() as fresh_session:
        wf = await WorkflowRepository(fresh_session).get(workflow_id)
        return _criteria_context_from_config(wf.config if wf else None, fallback)


def annotate_screening_output(
    output: ScreeningOutput,
    *,
    screening_criteria: str,
    criteria_version: int,
    preference_source: str = "hr_preference_memory",
) -> ScreeningOutput:
    detail = dict(output.score_detail or {})
    detail.update(
        {
            "criteria_version": max(1, int(criteria_version or 1)),
            "screening_criteria_hash": screening_criteria_hash(screening_criteria),
            "preference_source": preference_source,
        }
    )
    output.score_detail = detail
    return output


def _snapshot_fields(snap) -> dict:
    return {
        "display_name": snap.display_name,
        "current_title": snap.current_title,
        "current_company": snap.current_company,
        "work_years": float(snap.work_years) if snap.work_years else None,
        "education": snap.education,
        "city": snap.city,
        "skills": snap.skills or [],
        "summary": snap.summary,
        "experience_summary": snap.experience_summary,
        "project_summary": snap.project_summary,
    }


def _snapshot_resume_text(snap) -> str:
    return snap.raw_text or "\n".join(
        filter(None, [snap.summary, snap.experience_summary, snap.project_summary])
    )


def _apply_rule_adjustments(output: ScreeningOutput, min_years: float | None = None) -> ScreeningOutput:
    if min_years and output.score_detail.get("work_years"):
        years = output.score_detail.get("work_years", 0)
        if years < min_years:
            output.total_score = min(output.total_score, 59)
            output.level = "reject"
            output.gaps.append(f"工作年限不足（需要 {min_years} 年）")
    return output


def _dedupe_screening_outputs_by_identity(
    results: list[ScreeningOutput],
    snapshots_by_id: dict[str, object],
) -> list[ScreeningOutput]:
    by_identity: dict[str, ScreeningOutput] = {}
    order: list[str] = []

    def rank(result: ScreeningOutput) -> tuple[float, str]:
        snap = snapshots_by_id.get(result.candidate_snapshot_id)
        captured = getattr(snap, "captured_at", "") if snap else ""
        return (float(result.total_score or 0), str(captured or ""))

    for result in results:
        snap = snapshots_by_id.get(result.candidate_snapshot_id)
        identity = snapshot_identity_key(snap) if snap else None
        key = identity or f"snapshot:{result.candidate_snapshot_id}"
        if key not in by_identity:
            order.append(key)
            by_identity[key] = result
        elif rank(result) > rank(by_identity[key]):
            by_identity[key] = result

    return [by_identity[key] for key in order]


def _identity_or_id(snapshot: object) -> str:
    return snapshot_identity_key(snapshot) or f"snapshot:{getattr(snapshot, 'id', '')}"


async def screen_and_persist_one(
    snap_data: "CandidateSnapshotData",
    *,
    job_id: str | None,
    job_description: str,
    min_score: float,
) -> tuple[str, ScreeningOutput]:
    """Save one snapshot and run AI screening immediately (per-card flow)."""

    async with async_session_factory() as session:
        candidate_repo = CandidateRepository(session)
        screening_repo = ScreeningRepository(session)
        snap = await candidate_repo.save_snapshot(snap_data)

        fields = {
            "display_name": snap.display_name,
            "current_title": snap.current_title,
            "current_company": snap.current_company,
            "work_years": float(snap.work_years) if snap.work_years else None,
            "education": snap.education,
            "city": snap.city,
            "skills": snap.skills or [],
            "summary": snap.summary,
            "experience_summary": snap.experience_summary,
            "project_summary": snap.project_summary,
        }
        resume_text = snap.raw_text or "\n".join(
            filter(None, [snap.summary, snap.experience_summary, snap.project_summary])
        )

        try:
            output = await screen_candidate(
                job_description=job_description,
                candidate_snapshot_id=snap.id,
                resume_text=resume_text,
                candidate_fields=fields,
            )
            output = _apply_rule_adjustments(output)
        except Exception:
            output = ScreeningOutput(
                candidate_snapshot_id=snap.id,
                total_score=0,
                level="reject",
                gaps=["Agent 筛选失败"],
                suggested_action="reject",
            )

        await screening_repo.save_result(snap_data.workflow_id, job_id, output)
        await session.commit()
        return snap.id, output


async def visa_screen_and_persist_one(
    snap_data: "CandidateSnapshotData",
    *,
    job_id: str | None,
    screening_criteria: str = "",
) -> tuple[str, ScreeningOutput, str, VisaScreeningOutput | None]:
    """Save snapshot, visa-only AI screen, persist. Returns (snap_id, screening, decision)."""
    async with async_session_factory() as session:
        candidate_repo = CandidateRepository(session)
        snap = await candidate_repo.save_snapshot(snap_data)
        snap_id = snap.id
        fields = _snapshot_fields(snap)
        screening_criteria, criteria_version = await resolve_workflow_screening_context(
            snap_data.workflow_id,
            screening_criteria,
            session=session,
        )
        await session.commit()

    resume_text = snap_data.raw_text or "\n".join(
        filter(
            None,
            [snap_data.summary, snap_data.experience_summary, snap_data.project_summary],
        )
    )

    card_index = (snap_data.metadata or {}).get("card_index")
    display_name = snap_data.display_name or fields.get("display_name")

    from packages.workflow_events import emit

    try:
        visa = await screen_visa_only(
            snap_id,
            resume_text,
            fields,
            screening_criteria,
            card_index=card_index,
            display_name=display_name,
        )
    except Exception as e:
        if card_index is not None:
            emit(
                "error",
                f"#{card_index + 1} {display_name or '候选人'} AI 初筛失败: {e}",
                category="screen",
                meta={"card_index": card_index, "phase": "error", "error": str(e)},
            )
        raise
    output = visa_result_to_screening(snap_id, visa)
    output = annotate_screening_output(
        output,
        screening_criteria=screening_criteria,
        criteria_version=criteria_version,
    )
    decision = visa.decision

    from packages.db.sqlite_guard import run_sqlite_write

    async def _persist_screening() -> None:
        async with async_session_factory() as session:
            candidate_repo = CandidateRepository(session)
            screening_repo = ScreeningRepository(session)
            if visa.current_company:
                await candidate_repo.update_current_company(snap_id, visa.current_company)
            await candidate_repo.patch_metadata(
                snap_id,
                {
                    "agent_parse": {
                        "current_company": visa.current_company,
                        "resume_summary": visa.resume_summary,
                        "parse_notes": visa.parse_notes,
                        "highlights": visa.parse_highlights,
                    },
                },
            )
            await screening_repo.save_result(snap_data.workflow_id, job_id, output)
            await session.commit()

    await run_sqlite_write(_persist_screening)
    return snap_id, output, decision, visa


async def finalize_shortlist(workflow_id: str, config: RecruitingWorkflowConfig) -> ScreeningBatchResult:
    """Build shortlist from per-card screening results already stored in DB."""
    async with async_session_factory() as session:
        return await rebuild_shortlist_from_latest(
            workflow_id,
            job_id=config.job.job_id,
            top_k=config.screening.top_k,
            min_score=config.screening.min_score,
            session=session,
            commit=True,
        )


async def refresh_shortlist_ranks(
    workflow_id: str,
    *,
    session: AsyncSession,
    top_k: int | None = None,
) -> bool:
    """按最新初筛结果重排 Shortlist（观察 + 追问统一按分数排名）。"""
    workflow_repo = WorkflowRepository(session)
    wf = await workflow_repo.get(workflow_id)
    if not wf or not wf.shortlist_id:
        return False

    screening_cfg = (wf.config or {}).get("screening") or {}
    limit = top_k if top_k is not None else int(screening_cfg.get("top_k") or 10)
    min_score = float(screening_cfg.get("min_score") or 60)

    candidate_repo = CandidateRepository(session)
    screening_repo = ScreeningRepository(session)
    snapshots = await candidate_repo.list_by_workflow(workflow_id)
    snapshots_by_id = {snap.id: snap for snap in snapshots}
    results_raw = await screening_repo.list_latest_by_workflow(workflow_id)

    results: list[ScreeningOutput] = []
    for row in results_raw:
        missing = []
        for m in row.missing_info or []:
            if isinstance(m, dict):
                missing.append(MissingInfo(**m))
        results.append(
            ScreeningOutput(
                candidate_snapshot_id=row.candidate_snapshot_id,
                total_score=float(row.total_score or 0),
                level=row.level or "reject",
                score_detail=row.score_detail or {},
                matched_points=row.matched_points or [],
                gaps=row.gaps or [],
                missing_info=missing,
                suggested_action=row.suggested_action or "reject",
            )
        )
    results = _dedupe_screening_outputs_by_identity(results, snapshots_by_id)
    shortlist_candidates = await _shortlist_candidates_from_results(
        results,
        candidate_repo=candidate_repo,
        min_score=min_score,
        top_k=limit,
    )
    await screening_repo.replace_shortlist_candidates(wf.shortlist_id, shortlist_candidates)
    return True


# 兼容旧调用名
refresh_shortlist_observe_ranks = refresh_shortlist_ranks


async def rebuild_shortlist_from_latest(
    workflow_id: str,
    *,
    job_id: str | None,
    top_k: int,
    min_score: float,
    session: AsyncSession,
    commit: bool = False,
) -> ScreeningBatchResult:
    candidate_repo = CandidateRepository(session)
    screening_repo = ScreeningRepository(session)
    snapshots = await candidate_repo.list_by_workflow(workflow_id)
    snapshots_by_id = {snap.id: snap for snap in snapshots}
    results_raw = await screening_repo.list_latest_by_workflow(workflow_id)

    results: list[ScreeningOutput] = []
    for row in results_raw:
        missing = []
        for m in row.missing_info or []:
            if isinstance(m, dict):
                missing.append(MissingInfo(**m))
        results.append(
            ScreeningOutput(
                candidate_snapshot_id=row.candidate_snapshot_id,
                total_score=float(row.total_score or 0),
                level=row.level or "reject",
                score_detail=row.score_detail or {},
                matched_points=row.matched_points or [],
                gaps=row.gaps or [],
                missing_info=missing,
                suggested_action=row.suggested_action or "reject",
            )
        )
    results = _dedupe_screening_outputs_by_identity(results, snapshots_by_id)

    shortlist_candidates = await _shortlist_candidates_from_results(
        results,
        candidate_repo=candidate_repo,
        min_score=min_score,
        top_k=top_k,
    )

    shortlist = await screening_repo.create_shortlist(
        workflow_id=workflow_id,
        job_id=job_id,
        candidates=shortlist_candidates,
        min_score=min_score,
        total_candidates=len({_identity_or_id(snap) for snap in snapshots}),
    )
    if commit:
        await session.commit()

    return ScreeningBatchResult(
        workflow_id=workflow_id,
        shortlist_id=shortlist.id,
        screened_count=len(results),
        shortlist=shortlist_candidates,
        results=results,
    )


async def rescreen_existing_with_current_criteria(
    workflow_id: str,
    *,
    session: AsyncSession,
) -> dict:
    workflow_repo = WorkflowRepository(session)
    candidate_repo = CandidateRepository(session)
    screening_repo = ScreeningRepository(session)
    wf = await workflow_repo.get(workflow_id)
    if not wf:
        raise ValueError(f"Workflow not found: {workflow_id}")

    config = dict(wf.config or {})
    job = dict(config.get("job") or {})
    screening_cfg = dict(config.get("screening") or {})
    criteria, criteria_version = _criteria_context_from_config(config, job.get("screening_criteria") or "")
    snapshots = await candidate_repo.list_by_workflow(workflow_id)
    rescreened = 0

    for snap in snapshots:
        fields = _snapshot_fields(snap)
        resume_text = _snapshot_resume_text(snap)
        visa = await screen_visa_only(
            snap.id,
            resume_text,
            fields,
            criteria,
            display_name=snap.display_name,
        )
        output = visa_result_to_screening(snap.id, visa)
        output = annotate_screening_output(
            output,
            screening_criteria=criteria,
            criteria_version=criteria_version,
        )
        round_num = await screening_repo.next_round_for_candidate(workflow_id, snap.id)
        await screening_repo.save_result(workflow_id, wf.job_id, output, round_num=round_num)
        rescreened += 1

    shortlist_result = await rebuild_shortlist_from_latest(
        workflow_id,
        job_id=wf.job_id,
        top_k=int(screening_cfg.get("top_k") or 10),
        min_score=float(screening_cfg.get("min_score") or 60),
        session=session,
    )
    await workflow_repo.update_status(
        workflow_id,
        wf.status or "SCREENING_COMPLETED",
        shortlist_id=shortlist_result.shortlist_id,
    )
    await session.commit()
    return {
        "workflow_id": workflow_id,
        "rescreened_count": rescreened,
        "criteria_version": criteria_version,
        "shortlist_id": shortlist_result.shortlist_id,
    }


async def run_screening_batch(
    workflow_id: str, config: RecruitingWorkflowConfig
) -> ScreeningBatchResult:
    async with async_session_factory() as session:
        candidate_repo = CandidateRepository(session)
        screening_repo = ScreeningRepository(session)
        snapshots = await candidate_repo.list_by_workflow(workflow_id)

        results: list[ScreeningOutput] = []
        for snap in snapshots:
            fields = {
                "display_name": snap.display_name,
                "current_title": snap.current_title,
                "current_company": snap.current_company,
                "work_years": float(snap.work_years) if snap.work_years else None,
                "education": snap.education,
                "city": snap.city,
                "skills": snap.skills or [],
                "summary": snap.summary,
                "experience_summary": snap.experience_summary,
                "project_summary": snap.project_summary,
            }
            resume_text = snap.raw_text or "\n".join(
                filter(None, [snap.summary, snap.experience_summary, snap.project_summary])
            )

            try:
                output = await screen_candidate(
                    job_description=config.job.description,
                    candidate_snapshot_id=snap.id,
                    resume_text=resume_text,
                    candidate_fields=fields,
                )
                output = _apply_rule_adjustments(output)
            except Exception:
                output = ScreeningOutput(
                    candidate_snapshot_id=snap.id,
                    total_score=0,
                    level="reject",
                    gaps=["Agent 筛选失败"],
                    suggested_action="reject",
                )

            await screening_repo.save_result(workflow_id, config.job.job_id, output)
            results.append(output)

        qualified = _collect_rankable_screening(results, min_score=config.screening.min_score)
        top = qualified[: config.screening.top_k]

        shortlist_candidates = []
        for rank, r in enumerate(top, 1):
            snap = await candidate_repo.get(r.candidate_snapshot_id)
            shortlist_candidates.append(
                ShortlistCandidate(
                    candidate_snapshot_id=r.candidate_snapshot_id,
                    rank=rank,
                    score=r.total_score,
                    level=r.level,
                    display_name=snap.display_name if snap else None,
                    matched_points=r.matched_points,
                    missing_info=r.missing_info,
                )
            )

        shortlist = await screening_repo.create_shortlist(
            workflow_id=workflow_id,
            job_id=config.job.job_id,
            candidates=shortlist_candidates,
            min_score=config.screening.min_score,
            total_candidates=len(snapshots),
        )
        await session.commit()

        return ScreeningBatchResult(
            workflow_id=workflow_id,
            shortlist_id=shortlist.id,
            screened_count=len(results),
            shortlist=shortlist_candidates,
            results=results,
        )
