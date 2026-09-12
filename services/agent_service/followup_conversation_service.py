"""IM 中心追问编排：草稿、发送、未读扫描、候选表回写。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import RecruitingWorkflow
from packages.db.repositories import (
    CandidateRepository,
    ConversationRepository,
    ProfileRepository,
    ScreeningRepository,
    WorkflowRepository,
)
from packages.db.session import async_session_factory
from packages.screening_defaults import resolve_screening_criteria
from packages.workflow_events import emit
from packages.outreach_policy import workflow_im_review_required
from services.agent_service.followup_conversation_agent import generate_followup_message
from services.agent_service.followup_reply_enrichment_agent import enrich_followup_reply
from services.agent_service.outreach_draft_utils import (
    draft_result_from_message,
    get_pending_outbound_draft,
)
from services.agent_service.resume_request_agent import generate_resume_request_message
from services.fetch_worker.im_chat_adapter import build_im_contact_key
from services.fetch_worker.im_chat_runner import (
    IMSendTarget,
    run_im_send_batch,
    run_im_sync_replies_from_db,
    run_im_sync_replies_serial,
)
from services.fetch_worker.im_contact_match import (
    IMContactMatchFields,
    candidate_display_name,
    format_candidate_subtitle,
)

PARALLEL_LLM_LIMIT = 4


def _im_target_from_snap(
    snap,
    snap_id: str,
    message_text: str,
    *,
    conversation_id: str | None = None,
) -> IMSendTarget:
    fields = IMContactMatchFields.from_snapshot(snap)
    meta = (getattr(snap, "metadata_", None) or getattr(snap, "metadata", None) or {}) or {}
    return IMSendTarget(
        candidate_snapshot_id=snap_id,
        display_name=fields.display_name,
        message_text=message_text,
        conversation_id=conversation_id,
        age=fields.age,
        school=fields.school,
        education=fields.education,
        current_title=getattr(snap, "current_title", None) if snap else None,
        chat_initiated_at=meta.get("chat_initiated_at") or fields.chat_initiated_at,
    )


def _screening_criteria_from_wf(wf: RecruitingWorkflow) -> str:
    job = wf.config.get("job") or {}
    return resolve_screening_criteria(job.get("screening_criteria") or "")


async def _followup_candidates(session: AsyncSession, wf: RecruitingWorkflow) -> list[dict]:
    screening_repo = ScreeningRepository(session)
    candidate_repo = CandidateRepository(session)
    results = await screening_repo.list_latest_by_workflow(wf.id)
    rows = [r for r in results if r.level == "followup"]

    out = []
    for row in rows:
        snap_id = row.candidate_snapshot_id
        screening = await screening_repo.get_latest_for_candidate(wf.id, snap_id)
        snap = await candidate_repo.get(snap_id)
        if not snap:
            continue
        fields = IMContactMatchFields.from_snapshot(snap)
        person_name = candidate_display_name(snap)
        out.append({
            "candidate_snapshot_id": snap_id,
            "display_name": person_name,
            "current_title": snap.current_title,
            "age": fields.age,
            "school": fields.school,
            "education": fields.education,
            "missing_info": (screening.missing_info if screening else []) or [],
            "level": (screening.level if screening else "followup"),
            "screening": screening,
        })
    return out


async def _observe_candidates(session: AsyncSession, wf: RecruitingWorkflow) -> list[dict]:
    screening_repo = ScreeningRepository(session)
    candidate_repo = CandidateRepository(session)
    if not wf.shortlist_id:
        results = await screening_repo.list_by_workflow(wf.id)
        rows = [r for r in results if r.level == "observe"]
    else:
        _, sl = await screening_repo.get_shortlist(wf.shortlist_id)
        rows = [sc for sc in sl if sc.level == "observe"]

    out = []
    for row in rows:
        snap_id = row.candidate_snapshot_id
        snap = await candidate_repo.get(snap_id)
        if snap:
            fields = IMContactMatchFields.from_snapshot(snap)
            out.append({
                "candidate_snapshot_id": snap_id,
                "display_name": candidate_display_name(snap),
                "current_title": snap.current_title,
                "age": fields.age,
                "school": fields.school,
                "education": fields.education,
            })
    return out


async def count_followup_candidates(workflow_id: str) -> int:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            return 0
        return len(await _followup_candidates(session, wf))


def _inbound_already_stored(messages, text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return True
    for m in reversed(messages or []):
        if m.direction != "inbound":
            continue
        if (m.message_text or "").strip() == normalized:
            return True
    return False


async def apply_reply_enrichment(
    *,
    workflow_id: str,
    snap_id: str,
    raw_reply: str,
    wf: RecruitingWorkflow,
    criteria: str,
    session,
) -> dict:
    """将 enrichment 结果回写会话、初筛 round2 与画像。"""
    conv_repo = ConversationRepository(session)
    screening_repo = ScreeningRepository(session)
    candidate_repo = CandidateRepository(session)
    profile_repo = ProfileRepository(session)

    screening = await screening_repo.get_latest_for_candidate(workflow_id, snap_id)
    snap = await candidate_repo.get(snap_id)
    original_level = screening.level if screening else "followup"
    enrichment = await enrich_followup_reply(
        candidate_snapshot_id=snap_id,
        raw_reply=raw_reply,
        missing_info=(screening.missing_info if screening else []) or [],
        screening_criteria=criteria,
        original_level=original_level,
        display_name=snap.display_name if snap else None,
    )
    updated_level = enrichment.updated_level if enrichment.updated_level in ("observe", "followup", "exclude") else original_level
    followup_passed = original_level == "followup" and updated_level == "observe"
    now_iso = datetime.now(timezone.utc).isoformat()

    conv = await conv_repo.get_by_candidate(workflow_id, snap_id)
    if conv:
        await conv_repo.save_message(
            conversation_id=conv.id,
            candidate_snapshot_id=snap_id,
            direction="inbound",
            message_text=raw_reply,
            status="received",
            extracted_fields=enrichment.extracted_fields,
        )
        await conv_repo.update_status(
            conv.id,
            "REPLY_RECEIVED",
            last_reply_at=datetime.now(timezone.utc),
            last_agent_reason=enrichment.summary_for_list,
            need_resume_request=enrichment.need_resume_request,
        )

    from packages.schemas.screening import MissingInfo, ScreeningOutput

    remaining = []
    for m in enrichment.remaining_missing_info or []:
        if isinstance(m, dict):
            remaining.append(MissingInfo(**m))
        else:
            remaining.append(m)

    new_screening = ScreeningOutput(
        candidate_snapshot_id=snap_id,
        total_score=float(screening.total_score) if screening and screening.total_score else 65.0,
        level=updated_level,
        matched_points=screening.matched_points if screening else [],
        gaps=screening.gaps if screening else [],
        missing_info=remaining,
        suggested_action=(
            "ask_for_more_info"
            if updated_level == "followup"
            else "reject"
            if updated_level == "exclude"
            else "contact_now"
        ),
        score_detail={
            **(screening.score_detail if screening else {}),
            "summary_for_list": enrichment.summary_for_list,
            "im_reply": raw_reply[:500],
            "final_judgment_source": "reply_judgment_agent",
            "final_judgment_level": updated_level,
            **(
                {
                    "followup_passed": True,
                    "followup_origin_level": original_level,
                    "followup_passed_at": now_iso,
                    "followup_summary": enrichment.summary_for_list,
                }
                if followup_passed
                else {}
            ),
        },
    )
    await screening_repo.save_result(workflow_id, wf.job_id, new_screening, round_num=2)
    if wf.shortlist_id:
        from services.agent_service.screening_service import refresh_shortlist_ranks

        await refresh_shortlist_ranks(workflow_id, session=session)

    if enrichment.extracted_fields:
        await profile_repo.upsert_merged_profile(workflow_id, snap_id, enrichment.extracted_fields)
    metadata_patch = {
        "summary_for_list": enrichment.summary_for_list,
        "need_resume_request": enrichment.need_resume_request,
        "final_judgment_source": "reply_judgment_agent",
        "final_judgment_level": updated_level,
    }
    if followup_passed:
        metadata_patch.update(
            {
                "followup_passed": True,
                "followup_origin_level": original_level,
                "followup_passed_at": now_iso,
                "followup_summary": enrichment.summary_for_list,
            }
        )
    await candidate_repo.patch_metadata(snap_id, metadata_patch)

    return {
        "candidate_snapshot_id": snap_id,
        "display_name": snap.display_name if snap else None,
        "ok": True,
        "updated_level": updated_level,
        "followup_passed": followup_passed,
        "need_resume_request": enrichment.need_resume_request,
        "summary_for_list": enrichment.summary_for_list,
        "reply_preview": raw_reply[:200],
    }


async def list_reply_judgment_targets(workflow_id: str) -> list[dict]:
    """待拉取回复并终判的会话：已发出追问/要简历且仍待同步回复。"""
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        candidate_repo = CandidateRepository(session)
        convs = await conv_repo.list_by_workflow(workflow_id)
        out = []
        for conv in convs:
            if conv.status not in ("WAITING_REPLY", "MESSAGE_SENT", "REPLY_RECEIVED"):
                continue
            msgs = await conv_repo.list_messages(conv.id)
            if not any(m.direction == "outbound" and m.status == "sent" for m in msgs):
                continue
            snap = await candidate_repo.get(conv.candidate_snapshot_id)
            if not snap:
                continue
            person_name = candidate_display_name(snap)
            out.append({
                "conversation_id": conv.id,
                "candidate_snapshot_id": conv.candidate_snapshot_id,
                "display_name": person_name,
                "status": conv.status,
                "conversation_type": conv.conversation_type,
            })
        return out


async def run_serial_reply_judgment(
    workflow_id: str,
    *,
    should_stop: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[dict]:
    """串行：逐人同步 IM 回复 → enrichment → 终判回写（不自动发下一轮）。"""
    targets_meta = await list_reply_judgment_targets(workflow_id)
    if not targets_meta:
        emit(
            "info",
            "回复判定：暂无待处理会话（需已发出追问/要简历）",
            category="reply_judgment",
            workflow_id=workflow_id,
        )
        return []

    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        candidate_repo = CandidateRepository(session)
        conv_repo = ConversationRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError("Workflow not found")
        criteria = _screening_criteria_from_wf(wf)
        sync_targets: list[IMSendTarget] = []
        for item in targets_meta:
            snap = await candidate_repo.get(item["candidate_snapshot_id"])
            if not snap:
                continue
            sync_targets.append(
                _im_target_from_snap(
                    snap,
                    item["candidate_snapshot_id"],
                    "",
                    conversation_id=item["conversation_id"],
                )
            )
        await session.commit()

    browser_profile = (wf.config.get("fetch") or {}).get("browser_profile", "hr_default")
    outcomes = await run_im_sync_replies_serial(
        sync_targets,
        workflow_id=workflow_id,
        browser_profile=browser_profile,
        stop_check=should_stop,
    )

    results: list[dict] = []
    total = len(outcomes)
    for index, outcome in enumerate(outcomes):
        from packages.workflow_control import wait_if_paused

        await wait_if_paused(workflow_id)
        if should_stop and should_stop():
            break

        snap_id = outcome.target.candidate_snapshot_id
        name = outcome.target.display_name or snap_id[:8]
        if on_progress:
            on_progress(index + 1, total, name)

        if outcome.error:
            results.append({
                "candidate_snapshot_id": snap_id,
                "display_name": outcome.target.display_name,
                "ok": False,
                "skipped": outcome.error == "暂无新回复",
                "error": outcome.error,
            })
            emit(
                "info" if outcome.error == "暂无新回复" else "warn",
                f"回复判定 [{index + 1}/{total}] {name}: {outcome.error}",
                category="reply_judgment",
                workflow_id=workflow_id,
            )
            continue

        inbound = outcome.inbound
        if not inbound or not inbound.message_text:
            continue

        async with async_session_factory() as session:
            conv_repo = ConversationRepository(session)
            wf_repo = WorkflowRepository(session)
            wf = await wf_repo.get(workflow_id)
            conv = await conv_repo.get_by_candidate(workflow_id, snap_id)
            msgs = await conv_repo.list_messages(conv.id) if conv else []
            if _inbound_already_stored(msgs, inbound.message_text):
                results.append({
                    "candidate_snapshot_id": snap_id,
                    "display_name": outcome.target.display_name,
                    "ok": True,
                    "skipped": True,
                    "error": "回复已处理，跳过重复",
                })
                emit(
                    "info",
                    f"回复判定 [{index + 1}/{total}] {name}: 回复已处理",
                    category="reply_judgment",
                    workflow_id=workflow_id,
                )
                await session.commit()
                continue

            try:
                applied = await apply_reply_enrichment(
                    workflow_id=workflow_id,
                    snap_id=snap_id,
                    raw_reply=inbound.message_text,
                    wf=wf,
                    criteria=criteria,
                    session=session,
                )
                await session.commit()
                results.append(applied)
                emit(
                    "success",
                    f"回复判定 [{index + 1}/{total}] {name}: 【{applied.get('updated_level')}】"
                    f" {applied.get('summary_for_list', '')[:60]}",
                    category="reply_judgment",
                    workflow_id=workflow_id,
                    meta=applied,
                )
            except Exception as e:
                await session.rollback()
                results.append({
                    "candidate_snapshot_id": snap_id,
                    "display_name": outcome.target.display_name,
                    "ok": False,
                    "error": str(e),
                })
                emit(
                    "warn",
                    f"回复判定 [{index + 1}/{total}] {name} 失败: {e}",
                    category="reply_judgment",
                    workflow_id=workflow_id,
                )

    enriched = sum(1 for r in results if r.get("ok") and not r.get("skipped"))
    emit(
        "success",
        f"回复判定完成：终判 {enriched}/{len(results)} 人",
        category="reply_judgment",
        workflow_id=workflow_id,
    )
    return results


async def prepare_followup_for_candidate(workflow_id: str, snap_id: str) -> dict | None:
    """为单个追问候选人生成草稿（可并行调用；已有未发送草稿则直接返回）。"""
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        conv_repo = ConversationRepository(session)
        screening_repo = ScreeningRepository(session)
        candidate_repo = CandidateRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            return None

        snap = await candidate_repo.get(snap_id)
        if not snap:
            return None
        if not (snap.metadata_ or {}).get("chat_initiated"):
            return None
        screening = await screening_repo.get_latest_for_candidate(workflow_id, snap_id)
        if not screening or screening.level != "followup":
            return None

        existing = await conv_repo.get_by_candidate(workflow_id, snap_id)
        if existing:
            msgs = await conv_repo.list_messages(existing.id)
            pending = get_pending_outbound_draft(msgs)
            if pending:
                return draft_result_from_message(
                    pending,
                    conversation_id=existing.id,
                    candidate_snapshot_id=snap_id,
                    display_name=snap.display_name,
                    reason=existing.last_agent_reason or "",
                    action="追问",
                    auto_send_allowed=True,
                    reused_existing=True,
                )

        criteria = _screening_criteria_from_wf(wf)
        missing = screening.missing_info or []
        score_detail = screening.score_detail or {}
        followup_q = score_detail.get("followup_question")
        if not followup_q and missing:
            first = missing[0]
            followup_q = first.get("question") if isinstance(first, dict) else getattr(first, "question", None)

        im_fields = IMContactMatchFields.from_snapshot(snap)
        if not existing:
            existing = await conv_repo.create(
                workflow_id,
                snap_id,
                missing,
                conversation_type="followup",
                im_contact_key=build_im_contact_key(
                    snap.display_name,
                    age=im_fields.age,
                    school=im_fields.school,
                    education=im_fields.education,
                    current_title=snap.current_title,
                ),
            )

        msgs = await conv_repo.list_messages(existing.id)
        history = [m.message_text for m in msgs if m.direction == "outbound"]
        round_num = (existing.current_round or 0) + 1

        job_cfg = wf.config.get("job") or {}
        out = await generate_followup_message(
            candidate_snapshot_id=snap_id,
            display_name=candidate_display_name(snap),
            current_title=snap.current_title,
            missing_info=missing,
            screening_criteria=criteria,
            followup_question=followup_q,
            conversation_history=history,
            round_num=round_num,
            job_title=job_cfg.get("title"),
            job_description=job_cfg.get("description"),
        )

        msg = await conv_repo.save_message(
            conversation_id=existing.id,
            candidate_snapshot_id=snap_id,
            direction="outbound",
            message_text=out.message_text,
            status="drafted",
            round_num=round_num,
        )
        await conv_repo.update_status(
            existing.id,
            "MESSAGE_DRAFTED",
            current_round=round_num,
            last_agent_reason=out.reason,
        )
        await session.commit()

        return {
            "conversation_id": existing.id,
            "message_id": msg.id,
            "candidate_snapshot_id": snap_id,
            "display_name": snap.display_name,
            "message_text": out.message_text,
            "reason": out.reason,
            "round": round_num,
            "auto_send_allowed": out.auto_send_allowed,
            "reused_existing": False,
        }


async def schedule_prepare_followup_draft(workflow_id: str, snap_id: str) -> None:
    """兼容旧调用：委托 im_autopilot 自动判定并发送。"""
    from services.agent_service.im_autopilot import schedule_auto_im_outreach

    await schedule_auto_im_outreach(workflow_id, snap_id, "追问")


async def prepare_followup_messages(workflow_id: str) -> list[dict]:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError("Workflow not found")
        candidates = await _followup_candidates(session, wf)

    if not candidates:
        return []

    sem = asyncio.Semaphore(PARALLEL_LLM_LIMIT)

    async def _one(cand: dict) -> dict | None:
        async with sem:
            return await prepare_followup_for_candidate(
                workflow_id, cand["candidate_snapshot_id"]
            )

    results = await asyncio.gather(
        *[_one(c) for c in candidates],
        return_exceptions=True,
    )
    drafts: list[dict] = []
    new_count = 0
    for r in results:
        if isinstance(r, Exception):
            emit(
                "warn",
                f"并行生成追问草稿失败: {r}",
                category="im_followup",
                workflow_id=workflow_id,
            )
            continue
        if r:
            drafts.append(r)
            if not r.get("reused_existing"):
                new_count += 1

    if new_count:
        emit(
            "success",
            f"已生成 {new_count} 条新追问草稿",
            category="im_followup",
            workflow_id=workflow_id,
        )
    elif drafts:
        emit(
            "info",
            f"已有 {len(drafts)} 条追问草稿待确认，未重复生成",
            category="im_followup",
            workflow_id=workflow_id,
        )
    return drafts


async def confirm_and_send_batch(workflow_id: str, *, confirmed: bool = True) -> list[dict]:
    if not confirmed:
        raise ValueError("首轮发送需要 confirmed=true")

    from services.agent_service.im_autopilot import mark_conversations_started_when_ready

    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        conv_repo = ConversationRepository(session)
        candidate_repo = CandidateRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError("Workflow not found")

        await mark_conversations_started_when_ready(
            wf_repo, workflow_id, current_status=wf.status if wf else None
        )
        convs = await conv_repo.list_by_workflow(workflow_id)
        followup_convs = [c for c in convs if c.conversation_type == "followup"]

        targets: list[IMSendTarget] = []
        for conv in followup_convs:
            msgs = await conv_repo.list_messages(conv.id)
            drafted = [m for m in msgs if m.direction == "outbound" and m.status == "drafted"]
            if not drafted:
                continue
            msg = drafted[-1]
            snap = await candidate_repo.get(conv.candidate_snapshot_id)
            if not snap:
                continue
            if not (snap.metadata_ or {}).get("chat_initiated"):
                continue
            targets.append(
                _im_target_from_snap(
                    snap,
                    conv.candidate_snapshot_id,
                    msg.message_text,
                    conversation_id=conv.id,
                )
            )

        await session.commit()

    browser_profile = (wf.config.get("fetch") or {}).get("browser_profile", "hr_default")
    send_results = await run_im_send_batch(targets, workflow_id=workflow_id, browser_profile=browser_profile)

    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        now = datetime.now(timezone.utc)
        for r in send_results:
            if not r.get("ok"):
                continue
            cid = r.get("conversation_id")
            if not cid:
                continue
            msgs = await conv_repo.list_messages(cid)
            for m in reversed(msgs):
                if m.direction == "outbound" and m.status == "drafted":
                    await conv_repo.update_message_status(m.id, "sent")
                    break
            await conv_repo.update_status(
                cid,
                "WAITING_REPLY",
                last_message_at=now,
                im_contact_key=r.get("im_contact_key"),
            )
        await session.commit()

    emit(
        "success",
        f"IM 追问发送完成: {sum(1 for r in send_results if r.get('ok'))}/{len(send_results)}",
        category="im_followup",
        workflow_id=workflow_id,
    )
    return send_results


async def continue_followup(workflow_id: str) -> list[dict]:
    """一键继续：为需追问会话生成新草稿；非审核模式下 round>=2 自动发送。"""
    drafts = await prepare_followup_messages(workflow_id)

    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.get(workflow_id)
        if wf and workflow_im_review_required(wf.config):
            new_drafts = [d for d in drafts if not d.get("reused_existing")]
            if new_drafts:
                emit(
                    "info",
                    f"IM 审核模式：新生成 {len(new_drafts)} 条追问草稿，等待人工确认后发送",
                    category="im_followup",
                    workflow_id=workflow_id,
                    meta={"draft_count": len(new_drafts), "review_pending": True},
                )
            elif drafts:
                emit(
                    "info",
                    "IM 审核模式：追问草稿已存在，请在面板编辑或发送",
                    category="im_followup",
                    workflow_id=workflow_id,
                    meta={"draft_count": len(drafts), "review_pending": True, "reused_existing": True},
                )
            return drafts

    auto_targets = [d for d in drafts if d.get("auto_send_allowed") or (d.get("round") or 0) >= 2]
    if not auto_targets:
        return drafts

    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        candidate_repo = CandidateRepository(session)
        wf = await wf_repo.get(workflow_id)
        targets = []
        for d in auto_targets:
            snap = await candidate_repo.get(d["candidate_snapshot_id"])
            if not snap:
                continue
            if not (snap.metadata_ or {}).get("chat_initiated"):
                continue
            targets.append(
                _im_target_from_snap(
                    snap,
                    d["candidate_snapshot_id"],
                    d["message_text"],
                    conversation_id=d.get("conversation_id"),
                )
            )
        await session.commit()

    browser_profile = (wf.config.get("fetch") or {}).get("browser_profile", "hr_default")
    send_results = await run_im_send_batch(
        targets, workflow_id=workflow_id, browser_profile=browser_profile
    )
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        now = datetime.now(timezone.utc)
        for r in send_results:
            if not r.get("ok") or not r.get("conversation_id"):
                continue
            cid = r["conversation_id"]
            msgs = await conv_repo.list_messages(cid)
            for m in reversed(msgs):
                if m.direction == "outbound" and m.status == "drafted":
                    await conv_repo.update_message_status(m.id, "sent")
                    break
            await conv_repo.update_status(cid, "WAITING_REPLY", last_message_at=now)
        await session.commit()
    return send_results


async def run_im_unread_scan_and_enrich(workflow_id: str) -> list[dict]:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        conv_repo = ConversationRepository(session)
        candidate_repo = CandidateRepository(session)
        screening_repo = ScreeningRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError("Workflow not found")

        criteria = _screening_criteria_from_wf(wf)
        convs = await conv_repo.list_by_workflow(workflow_id)
        sync_targets: list[IMSendTarget] = []
        for conv in convs:
            if conv.status not in ("WAITING_REPLY", "REPLY_RECEIVED", "MESSAGE_SENT"):
                continue
            snap = await candidate_repo.get(conv.candidate_snapshot_id)
            if not snap:
                continue
            sync_targets.append(
                _im_target_from_snap(snap, conv.candidate_snapshot_id, "", conversation_id=conv.id)
            )
        await session.commit()

    if not sync_targets:
        emit(
            "info",
            "跳过 IM 回复同步：尚无已发出的追问/要简历（待查的是追问回复，不是开聊回复）",
            category="im_followup",
            workflow_id=workflow_id,
        )
        return []

    browser_profile = (wf.config.get("fetch") or {}).get("browser_profile", "hr_default")
    inbound = await run_im_sync_replies_from_db(
        sync_targets, workflow_id=workflow_id, browser_profile=browser_profile
    )

    enriched_results = []
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        screening_repo = ScreeningRepository(session)
        candidate_repo = CandidateRepository(session)
        profile_repo = ProfileRepository(session)
        wf = await wf_repo.get(workflow_id)

        sem = asyncio.Semaphore(PARALLEL_LLM_LIMIT)

        async def _enrich_item(item):
            snap_id = item.candidate_snapshot_id or item.matched_snapshot_id
            if not snap_id:
                return item, None, None, None, None
            async with sem:
                async with async_session_factory() as s2:
                    sr = ScreeningRepository(s2)
                    cr = CandidateRepository(s2)
                    screening = await sr.get_latest_for_candidate(workflow_id, snap_id)
                    snap = await cr.get(snap_id)
                    enrichment = await enrich_followup_reply(
                        candidate_snapshot_id=snap_id,
                        raw_reply=item.message_text,
                        missing_info=(screening.missing_info if screening else []) or [],
                        screening_criteria=criteria,
                        original_level=screening.level if screening else "followup",
                        display_name=snap.display_name if snap else None,
                    )
                    return item, snap_id, screening, snap, enrichment

        enrich_pairs = await asyncio.gather(
            *[_enrich_item(item) for item in inbound],
            return_exceptions=True,
        )

        for pair in enrich_pairs:
            if isinstance(pair, Exception):
                enriched_results.append({"ok": False, "error": str(pair)})
                continue
            item, snap_id, screening, snap, enrichment = pair
            snap_id = snap_id or item.candidate_snapshot_id or item.matched_snapshot_id
            if not snap_id or enrichment is None:
                enriched_results.append({
                    "contact_text": item.contact_text,
                    "ok": False,
                    "error": "未能读取或解析回复",
                })
                continue

            conv = await conv_repo.get_by_candidate(workflow_id, snap_id)
            if conv:
                await conv_repo.save_message(
                    conversation_id=conv.id,
                    candidate_snapshot_id=snap_id,
                    direction="inbound",
                    message_text=item.message_text,
                    status="received",
                    extracted_fields=enrichment.extracted_fields,
                )
                await conv_repo.update_status(
                    conv.id,
                    "REPLY_RECEIVED",
                    last_reply_at=datetime.now(timezone.utc),
                    last_agent_reason=enrichment.summary_for_list,
                    need_resume_request=enrichment.need_resume_request,
                )

            from packages.schemas.screening import MissingInfo, ScreeningOutput

            remaining = []
            for m in enrichment.remaining_missing_info or []:
                if isinstance(m, dict):
                    remaining.append(MissingInfo(**m))
                else:
                    remaining.append(m)

            new_screening = ScreeningOutput(
                candidate_snapshot_id=snap_id,
                total_score=float(screening.total_score) if screening and screening.total_score else 65.0,
                level=enrichment.updated_level,
                matched_points=screening.matched_points if screening else [],
                gaps=screening.gaps if screening else [],
                missing_info=remaining,
                suggested_action="ask_for_more_info" if enrichment.updated_level == "followup" else "contact_now",
                score_detail={
                    **(screening.score_detail if screening else {}),
                    "summary_for_list": enrichment.summary_for_list,
                    "im_reply": item.message_text[:500],
                },
            )
            await screening_repo.save_result(workflow_id, wf.job_id, new_screening, round_num=2)

            if enrichment.extracted_fields:
                await profile_repo.upsert_merged_profile(
                    workflow_id, snap_id, enrichment.extracted_fields
                )
            await candidate_repo.patch_metadata(
                snap_id,
                {
                    "summary_for_list": enrichment.summary_for_list,
                    "need_resume_request": enrichment.need_resume_request,
                },
            )

            enriched_results.append({
                "candidate_snapshot_id": snap_id,
                "display_name": snap.display_name if snap else None,
                "ok": True,
                "updated_level": enrichment.updated_level,
                "need_resume_request": enrichment.need_resume_request,
                "summary_for_list": enrichment.summary_for_list,
                "reply_preview": item.message_text[:200],
            })

        await session.commit()

    emit(
        "success",
        f"DB 对话同步完成，处理 {len(enriched_results)} 条",
        category="im_reply",
        workflow_id=workflow_id,
    )
    return enriched_results


async def prepare_observe_resume_requests(workflow_id: str) -> list[dict]:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        conv_repo = ConversationRepository(session)
        candidate_repo = CandidateRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError("Workflow not found")

        job_title = (wf.config.get("job") or {}).get("title")
        observes = await _observe_candidates(session, wf)
        drafts = []

        for cand in observes:
            snap_id = cand["candidate_snapshot_id"]
            snap = await candidate_repo.get(snap_id)
            if not snap or not (snap.metadata_ or {}).get("chat_initiated"):
                continue
            existing = await conv_repo.get_by_candidate(workflow_id, snap_id)
            im_fields = IMContactMatchFields.from_snapshot(snap) if snap else IMContactMatchFields(
                display_name=cand.get("display_name"),
                age=cand.get("age"),
                school=cand.get("school"),
                education=cand.get("education"),
            )
            if not existing:
                existing = await conv_repo.create(
                    workflow_id,
                    snap_id,
                    [],
                    conversation_type="resume_request",
                    im_contact_key=build_im_contact_key(
                        cand["display_name"],
                        age=im_fields.age,
                        school=im_fields.school,
                        education=im_fields.education,
                        current_title=cand.get("current_title"),
                    ),
                )
            msgs = await conv_repo.list_messages(existing.id)
            pending = get_pending_outbound_draft(msgs)
            if pending:
                drafts.append(
                    draft_result_from_message(
                        pending,
                        conversation_id=existing.id,
                        candidate_snapshot_id=snap_id,
                        display_name=cand["display_name"],
                        reason=existing.last_agent_reason or "",
                        action="要简历",
                        reused_existing=True,
                    )
                )
                continue
            out = await generate_resume_request_message(
                candidate_snapshot_id=snap_id,
                display_name=cand["display_name"],
                current_title=cand["current_title"],
                job_title=job_title,
            )
            msg = await conv_repo.save_message(
                conversation_id=existing.id,
                candidate_snapshot_id=snap_id,
                direction="outbound",
                message_text=out.message_text,
                status="drafted",
                round_num=1,
            )
            await conv_repo.update_status(existing.id, "MESSAGE_DRAFTED", current_round=1)
            drafts.append({
                "conversation_id": existing.id,
                "message_id": msg.id,
                "candidate_snapshot_id": snap_id,
                "display_name": cand["display_name"],
                "message_text": out.message_text,
                "reason": out.reason,
                "reused_existing": False,
            })
        await session.commit()
        return drafts


async def send_observe_resume_batch(workflow_id: str, *, confirmed: bool = True) -> list[dict]:
    if not confirmed:
        raise ValueError("需要 confirmed=true")
    drafts = await prepare_observe_resume_requests(workflow_id)

    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        candidate_repo = CandidateRepository(session)
        wf = await wf_repo.get(workflow_id)
        targets = []
        for d in drafts:
            snap = await candidate_repo.get(d["candidate_snapshot_id"])
            if not snap:
                continue
            targets.append(
                _im_target_from_snap(
                    snap,
                    d["candidate_snapshot_id"],
                    d["message_text"],
                    conversation_id=d.get("conversation_id"),
                )
            )
        await session.commit()

    browser_profile = (wf.config.get("fetch") or {}).get("browser_profile", "hr_default")
    send_results = await run_im_send_batch(
        targets, workflow_id=workflow_id, browser_profile=browser_profile
    )
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        now = datetime.now(timezone.utc)
        for r in send_results:
            if not r.get("ok") or not r.get("conversation_id"):
                continue
            cid = r["conversation_id"]
            msgs = await conv_repo.list_messages(cid)
            for m in reversed(msgs):
                if m.direction == "outbound" and m.status == "drafted":
                    await conv_repo.update_message_status(m.id, "sent")
                    break
            await conv_repo.update_status(cid, "WAITING_REPLY", last_message_at=now)
        await session.commit()
    return send_results


async def list_workflow_conversations(workflow_id: str) -> list[dict]:
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        candidate_repo = CandidateRepository(session)
        convs = await conv_repo.list_by_workflow(workflow_id)
        out = []
        for conv in convs:
            snap = await candidate_repo.get(conv.candidate_snapshot_id)
            msgs = await conv_repo.list_messages(conv.id)
            fields = IMContactMatchFields.from_snapshot(snap) if snap else IMContactMatchFields()
            person_name = candidate_display_name(snap) if snap else "未知"
            out.append({
                "id": conv.id,
                "candidate_snapshot_id": conv.candidate_snapshot_id,
                "display_name": None if person_name == "未知" else person_name,
                "subtitle": format_candidate_subtitle(
                    person_name,
                    age=fields.age,
                    school=fields.school,
                    education=fields.education,
                ),
                "conversation_type": conv.conversation_type,
                "status": conv.status,
                "current_round": conv.current_round,
                "need_resume_request": bool(conv.need_resume_request),
                "last_agent_reason": conv.last_agent_reason,
                "message_count": len(msgs),
                "latest_outbound": next(
                    (m.message_text for m in reversed(msgs) if m.direction == "outbound"),
                    None,
                ),
                "latest_inbound": next(
                    (m.message_text for m in reversed(msgs) if m.direction == "inbound"),
                    None,
                ),
                "messages": [
                    {
                        "id": m.id,
                        "direction": m.direction,
                        "message_text": m.message_text,
                        "status": m.status,
                        "round": m.round,
                        "extracted_fields": m.extracted_fields or {},
                    }
                    for m in msgs
                ],
            })
        return out
