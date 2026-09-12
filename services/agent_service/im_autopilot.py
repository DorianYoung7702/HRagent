"""IM 全自动触达：Agent 按候选人状态判定追问或要简历，生成即发。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from packages.db.repositories import (
    CandidateRepository,
    ConversationRepository,
    ScreeningRepository,
    WorkflowRepository,
)
from packages.db.session import async_session_factory
from packages.outreach_policy import workflow_im_review_required
from packages.workflow_events import emit
from services.agent_service.followup_conversation_service import (
    _followup_candidates,
    _im_target_from_snap,
    _observe_candidates,
    prepare_followup_for_candidate,
    run_im_unread_scan_and_enrich,
)
from services.agent_service.outreach_draft_utils import (
    draft_result_from_message,
    get_pending_outbound_draft,
)
from services.agent_service.resume_request_agent import generate_resume_request_message
from services.fetch_worker.im_chat_adapter import build_im_contact_key
from services.fetch_worker.im_chat_runner import run_im_send_batch
from services.fetch_worker.im_contact_match import IMContactMatchFields

logger = logging.getLogger(__name__)

IM_MONITOR_INTERVAL_SEC = 180
IM_MONITOR_MAX_CYCLES = 40
# 开聊后猎聘「我发起的」列表同步需要时间；观察/追问均需先开聊才能匹配
CHAT_INITIATED_IM_SYNC_WAIT_SEC = 3

_im_locks: dict[str, asyncio.Lock] = {}
_monitor_running: set[str] = set()
_stop_events: dict[str, asyncio.Event] = {}


def _get_stop_event(workflow_id: str) -> asyncio.Event:
    if workflow_id not in _stop_events:
        _stop_events[workflow_id] = asyncio.Event()
    return _stop_events[workflow_id]


def is_im_autopilot_stopped(workflow_id: str) -> bool:
    return _get_stop_event(workflow_id).is_set()


def stop_im_autopilot(workflow_id: str) -> dict:
    """请求停止 IM Agent 后台跟进。"""
    was_running = workflow_id in _monitor_running
    _get_stop_event(workflow_id).set()
    return {"stopped": True, "was_running": was_running}


def im_autopilot_status(workflow_id: str) -> dict:
    return {
        "running": workflow_id in _monitor_running,
        "stopped": is_im_autopilot_stopped(workflow_id),
    }


def is_im_monitor_running(workflow_id: str) -> bool:
    return workflow_id in _monitor_running


def is_im_autopilot_active(workflow_id: str) -> bool:
    return is_im_monitor_running(workflow_id)


_FETCH_SCREEN_STATUSES = frozenset({"CREATED", "FETCHING", "FETCH_COMPLETED", "SCREENING"})


async def mark_conversations_started_when_ready(
    wf_repo: WorkflowRepository,
    workflow_id: str,
    *,
    current_status: str | None = None,
) -> None:
    """Do not overwrite fetch/screen status while cards are still being processed."""
    status = current_status
    if status is None:
        wf = await wf_repo.get(workflow_id)
        status = (wf.status if wf else "") or ""
    if status in _FETCH_SCREEN_STATUSES:
        return
    await wf_repo.update_status(workflow_id, "CONVERSATIONS_STARTED")


def _workflow_im_lock(workflow_id: str) -> asyncio.Lock:
    if workflow_id not in _im_locks:
        _im_locks[workflow_id] = asyncio.Lock()
    return _im_locks[workflow_id]


async def is_chat_initiated(workflow_id: str, snap_id: str) -> bool:
    """是否已在简历弹窗完成「立即沟通」— 观察/追问均须沟通后才出现在「我发起的」。"""
    async with async_session_factory() as session:
        repo = CandidateRepository(session)
        snap = await repo.get(snap_id)
        if not snap or snap.workflow_id != workflow_id:
            return False
        meta = snap.metadata_ or {}
        return bool(meta.get("chat_initiated"))


async def is_prior_communication(workflow_id: str, snap_id: str) -> bool:
    """猎聘侧此前已沟通过（弹窗为「继续沟通」），不应重复开聊或自动 IM。"""
    async with async_session_factory() as session:
        repo = CandidateRepository(session)
        snap = await repo.get(snap_id)
        if not snap or snap.workflow_id != workflow_id:
            return False
        return bool((snap.metadata_ or {}).get("prior_communication"))


async def wait_after_chat_initiated(workflow_id: str, *, seconds: float | None = None) -> None:
    """开聊后短暂等待，便于猎聘「我发起的」列表出现该联系人。"""
    delay = CHAT_INITIATED_IM_SYNC_WAIT_SEC if seconds is None else seconds
    if delay <= 0:
        return
    emit(
        "info",
        f"开聊完成，等待 {delay:.0f}s 以便「我发起的」同步联系人…",
        category="im_autopilot",
        workflow_id=workflow_id,
    )
    await asyncio.sleep(delay)


async def _workflow_im_review_required(workflow_id: str) -> bool:
    async with async_session_factory() as session:
        wf = await WorkflowRepository(session).get(workflow_id)
        return workflow_im_review_required(wf.config if wf else None)


async def _emit_review_pending_draft(
    workflow_id: str,
    draft: dict,
    *,
    action: str,
) -> dict:
    round_n = draft.get("round") or 1
    name = draft.get("display_name") or draft.get("candidate_snapshot_id", "")[:8]
    if draft.get("reused_existing"):
        emit(
            "info",
            f"IM 草稿待确认（第 {round_n} 轮·{action}）：{name}",
            category="im_autopilot",
            workflow_id=workflow_id,
            meta={
                "snap_id": draft.get("candidate_snapshot_id"),
                "round": round_n,
                "action": action,
                "review_pending": True,
                "reused_existing": True,
            },
        )
    else:
        emit(
            "info",
            f"已生成 IM 草稿（第 {round_n} 轮·{action}）：{name}，等待人工确认",
            category="im_autopilot",
            workflow_id=workflow_id,
            meta={
                "snap_id": draft.get("candidate_snapshot_id"),
                "round": round_n,
                "action": action,
                "review_pending": True,
            },
        )
    return {
        "draft": draft,
        "send": None,
        "action": action,
        "review_pending": True,
        "reused_existing": bool(draft.get("reused_existing")),
    }


async def _mark_outbound_sent(send_results: list[dict]) -> None:
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
            await conv_repo.update_status(
                cid,
                "WAITING_REPLY",
                last_message_at=now,
                im_contact_key=r.get("im_contact_key"),
            )
        await session.commit()


async def prepare_resume_for_candidate(workflow_id: str, snap_id: str) -> dict | None:
    """为单个观察/待要简历候选人生成索要简历草稿。"""
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        conv_repo = ConversationRepository(session)
        candidate_repo = CandidateRepository(session)
        screening_repo = ScreeningRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            return None

        snap = await candidate_repo.get(snap_id)
        if not snap:
            return None
        if not (snap.metadata_ or {}).get("chat_initiated"):
            return None

        screening = await screening_repo.get_latest_for_candidate(workflow_id, snap_id)
        existing = await conv_repo.get_by_candidate(workflow_id, snap_id)
        allow = (
            (screening and screening.level == "observe")
            or (existing and existing.need_resume_request)
            or bool((snap.metadata_ or {}).get("need_resume_request"))
        )
        if not allow:
            return None

        if existing:
            msgs = await conv_repo.list_messages(existing.id)
            if any(
                m.direction == "outbound"
                and m.status == "sent"
                and existing.conversation_type == "resume_request"
                for m in msgs
            ):
                return None
            drafted = get_pending_outbound_draft(msgs)
            if drafted:
                return draft_result_from_message(
                    drafted,
                    conversation_id=existing.id,
                    candidate_snapshot_id=snap_id,
                    display_name=snap.display_name,
                    reason=existing.last_agent_reason or "",
                    action="要简历",
                    round_num=drafted.round or 1,
                    reused_existing=True,
                )

        job_title = (wf.config.get("job") or {}).get("title")
        out = await generate_resume_request_message(
            candidate_snapshot_id=snap_id,
            display_name=snap.display_name,
            current_title=snap.current_title,
            job_title=job_title,
        )

        im_fields = IMContactMatchFields.from_snapshot(snap)
        if not existing:
            existing = await conv_repo.create(
                workflow_id,
                snap_id,
                [],
                conversation_type="resume_request",
                im_contact_key=build_im_contact_key(
                    snap.display_name,
                    age=im_fields.age,
                    school=im_fields.school,
                    education=im_fields.education,
                    current_title=snap.current_title,
                ),
            )

        msg = await conv_repo.save_message(
            conversation_id=existing.id,
            candidate_snapshot_id=snap_id,
            direction="outbound",
            message_text=out.message_text,
            status="drafted",
            round_num=1,
        )
        await conv_repo.update_status(
            existing.id,
            "MESSAGE_DRAFTED",
            current_round=1,
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
            "round": 1,
            "action": "要简历",
            "reused_existing": False,
        }


async def _send_single_draft(workflow_id: str, draft: dict) -> dict | None:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        candidate_repo = CandidateRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            return None
        snap = await candidate_repo.get(draft["candidate_snapshot_id"])
        if not snap:
            return None
        await mark_conversations_started_when_ready(
            wf_repo, workflow_id, current_status=wf.status if wf else None
        )
        target = _im_target_from_snap(
            snap,
            draft["candidate_snapshot_id"],
            draft["message_text"],
            conversation_id=draft.get("conversation_id"),
        )
        await session.commit()

    browser_profile = (wf.config.get("fetch") or {}).get("browser_profile", "hr_default")
    send_results = await run_im_send_batch(
        [target], workflow_id=workflow_id, browser_profile=browser_profile
    )
    await _mark_outbound_sent(send_results)
    return send_results[0] if send_results else None


async def auto_outreach_for_candidate(
    workflow_id: str,
    snap_id: str,
    decision: str,
    *,
    respect_im_stop: bool = True,
) -> dict | None:
    """开聊后立刻发追问/要简历；观察与追问均须先开聊才能在「我发起的」匹配。"""
    if respect_im_stop and is_im_autopilot_stopped(workflow_id):
        return None
    if decision not in ("追问", "观察"):
        return None

    if not await is_chat_initiated(workflow_id, snap_id):
        action = "要简历" if decision == "观察" else "追问"
        emit(
            "warn",
            f"跳过 IM {action}：尚未完成「立即沟通」，无法在「我发起的」匹配（{snap_id[:8]}…）",
            category="im_autopilot",
            workflow_id=workflow_id,
            meta={"snap_id": snap_id, "decision": decision},
        )
        return None

    if await is_prior_communication(workflow_id, snap_id):
        action = "要简历" if decision == "观察" else "追问"
        emit(
            "info",
            f"跳过 IM {action}：此前已在猎聘沟通过，不重复发送（{snap_id[:8]}…）",
            category="im_autopilot",
            workflow_id=workflow_id,
            meta={"snap_id": snap_id, "decision": decision},
        )
        return None

    await wait_after_chat_initiated(workflow_id)

    async with _workflow_im_lock(workflow_id):
        if decision == "追问":
            draft = await prepare_followup_for_candidate(workflow_id, snap_id)
            action = "追问"
        else:
            draft = await prepare_resume_for_candidate(workflow_id, snap_id)
            action = "要简历"

        if not draft:
            return None

        if await _workflow_im_review_required(workflow_id):
            if draft.get("reused_existing"):
                return {
                    "draft": draft,
                    "send": None,
                    "action": action,
                    "review_pending": True,
                    "reused_existing": True,
                }
            return await _emit_review_pending_draft(workflow_id, draft, action=action)

        send_result = await _send_single_draft(workflow_id, draft)
        name = draft.get("display_name") or snap_id
        if send_result and send_result.get("ok"):
            emit(
                "success",
                f"IM 自动{action}已发送: {name}",
                category="im_autopilot",
                workflow_id=workflow_id,
                meta={"snap_id": snap_id, "action": action},
            )
        else:
            err = (send_result or {}).get("error") or "发送失败"
            emit(
                "warn",
                f"IM 自动{action}发送失败 ({name}): {err}",
                category="im_autopilot",
                workflow_id=workflow_id,
            )

        return {"draft": draft, "send": send_result, "action": action}


async def schedule_auto_im_outreach(workflow_id: str, snap_id: str, decision: str) -> dict | None:
    """开聊后立即生成并发送追问/要简历，不等候选人回复开聊消息。"""
    try:
        return await auto_outreach_for_candidate(
            workflow_id,
            snap_id,
            decision,
            respect_im_stop=False,
        )
    except Exception as e:
        logger.exception("auto IM outreach failed for %s", snap_id)
        emit(
            "warn",
            f"IM 自动触达失败: {e}",
            category="im_autopilot",
            workflow_id=workflow_id,
        )
        return None


async def _conv_has_sent_outbound(workflow_id: str, snap_id: str) -> bool:
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        conv = await conv_repo.get_by_candidate(workflow_id, snap_id)
        if not conv:
            return False
        msgs = await conv_repo.list_messages(conv.id)
        return any(m.direction == "outbound" and m.status == "sent" for m in msgs)


async def _process_enrichment_actions(workflow_id: str, enriched: list[dict]) -> int:
    sent = 0
    for r in enriched:
        if not r.get("ok"):
            continue
        snap_id = r.get("candidate_snapshot_id")
        if not snap_id:
            continue
        if r.get("need_resume_request") or r.get("updated_level") == "observe":
            decision = "观察"
        elif r.get("updated_level") == "followup":
            decision = "追问"
        else:
            continue
        result = await auto_outreach_for_candidate(workflow_id, snap_id, decision)
        if result and (result.get("send") or {}).get("ok"):
            sent += 1
    return sent


async def _conv_has_pending_draft(workflow_id: str, snap_id: str) -> bool:
    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        conv = await conv_repo.get_by_candidate(workflow_id, snap_id)
        if not conv:
            return False
        msgs = await conv_repo.list_messages(conv.id)
        return get_pending_outbound_draft(msgs) is not None


async def _catch_up_pending_outreach(workflow_id: str) -> int:
    """补发抓取阶段未成功发送的追问/要简历（单次打开 IM，批量发送）。"""
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            return 0
        followups = await _followup_candidates(session, wf)
        observes = await _observe_candidates(session, wf)
        conv_repo = ConversationRepository(session)
        candidate_repo = CandidateRepository(session)
        pending: list[tuple[str, str]] = []

        async def _eligible(sid: str) -> bool:
            snap = await candidate_repo.get(sid)
            return bool(snap and (snap.metadata_ or {}).get("chat_initiated"))

        for c in followups:
            snap_id = c["candidate_snapshot_id"]
            if not await _eligible(snap_id):
                continue
            if await _conv_has_pending_draft(workflow_id, snap_id):
                continue
            conv = await conv_repo.get_by_candidate(workflow_id, snap_id)
            if conv and conv.conversation_type == "resume_request":
                continue
            if conv and conv.need_resume_request:
                pending.append((snap_id, "观察"))
            elif not await _conv_has_sent_outbound(workflow_id, snap_id):
                pending.append((snap_id, "追问"))

        for c in observes:
            snap_id = c["candidate_snapshot_id"]
            if not await _eligible(snap_id):
                continue
            if await _conv_has_pending_draft(workflow_id, snap_id):
                continue
            if not await _conv_has_sent_outbound(workflow_id, snap_id):
                pending.append((snap_id, "观察"))

        convs = await conv_repo.list_by_workflow(workflow_id)
        for conv in convs:
            if not conv.need_resume_request:
                continue
            snap_id = conv.candidate_snapshot_id
            msgs = await conv_repo.list_messages(conv.id)
            has_resume_sent = any(
                m.direction == "outbound"
                and m.status == "sent"
                and conv.conversation_type == "resume_request"
                for m in msgs
            )
            if not has_resume_sent and await _eligible(snap_id):
                if not await _conv_has_pending_draft(workflow_id, snap_id):
                    pending.append((snap_id, "观察"))

    seen: set[str] = set()
    unique_pending: list[tuple[str, str]] = []
    for snap_id, decision in pending:
        key = f"{snap_id}:{decision}"
        if key in seen:
            continue
        seen.add(key)
        unique_pending.append((snap_id, decision))

    if not unique_pending:
        return 0

    async with _workflow_im_lock(workflow_id):
        drafts: list[dict] = []
        for snap_id, decision in unique_pending:
            if decision == "追问":
                draft = await prepare_followup_for_candidate(workflow_id, snap_id)
            else:
                draft = await prepare_resume_for_candidate(workflow_id, snap_id)
            if draft:
                drafts.append(draft)

        if not drafts:
            emit(
                "warn",
                f"IM 补发：{len(unique_pending)} 人待触达，但追问/要简历草稿生成失败",
                category="im_autopilot",
                workflow_id=workflow_id,
            )
            return 0

        if await _workflow_im_review_required(workflow_id):
            new_drafts = [d for d in drafts if not d.get("reused_existing")]
            if new_drafts:
                emit(
                    "info",
                    f"IM 审核模式：新生成 {len(new_drafts)} 条草稿，等待人工确认后发送",
                    category="im_autopilot",
                    workflow_id=workflow_id,
                    meta={"draft_count": len(new_drafts), "review_pending": True},
                )
            return 0

        async with async_session_factory() as session:
            wf_repo = WorkflowRepository(session)
            candidate_repo = CandidateRepository(session)
            wf = await wf_repo.get(workflow_id)
            if not wf:
                return 0
            await mark_conversations_started_when_ready(
                wf_repo, workflow_id, current_status=wf.status if wf else None
            )
            targets: list = []
            for draft in drafts:
                snap = await candidate_repo.get(draft["candidate_snapshot_id"])
                if not snap:
                    continue
                targets.append(
                    _im_target_from_snap(
                        snap,
                        draft["candidate_snapshot_id"],
                        draft["message_text"],
                        conversation_id=draft.get("conversation_id"),
                    )
                )
            await session.commit()

        if not targets:
            return 0

        browser_profile = (wf.config.get("fetch") or {}).get("browser_profile", "hr_default")
        send_results = await run_im_send_batch(
            targets, workflow_id=workflow_id, browser_profile=browser_profile
        )
        await _mark_outbound_sent(send_results)

        ok = sum(1 for r in send_results if r.get("ok"))
        failed = [r for r in send_results if not r.get("ok")]
        if ok:
            emit(
                "success",
                f"IM 补发完成：{ok}/{len(send_results)} 人已在「我发起的」发送",
                category="im_autopilot",
                workflow_id=workflow_id,
            )
        if failed:
            sample = failed[0].get("error") or "匹配或发送失败"
            emit(
                "warn",
                f"IM 补发失败 {len(failed)} 人：{sample}（列表有联系人但姓名/时间未匹配上）",
                category="im_autopilot",
                workflow_id=workflow_id,
                meta={"failed": len(failed), "sample_error": sample},
            )
        return ok


async def run_im_autopilot_cycle(workflow_id: str) -> dict:
    """一轮：补发首轮消息 → 同步回复 → Agent 判定 → 白名单问答自动回复。"""
    if is_im_autopilot_stopped(workflow_id):
        return {
            "enriched": 0,
            "enrich_sent": 0,
            "catchup_sent": 0,
            "dialogue_auto_sent": 0,
            "stopped": True,
        }
    catchup_sent = await _catch_up_pending_outreach(workflow_id)
    enriched = await run_im_unread_scan_and_enrich(workflow_id)
    enrich_sent = await _process_enrichment_actions(workflow_id, enriched)
    from services.agent_service.candidate_dialogue_service import process_pending_dialogue_replies

    dialogue = await process_pending_dialogue_replies(workflow_id)

    summary = {
        "enriched": len([r for r in enriched if r.get("ok")]),
        "enrich_sent": enrich_sent,
        "catchup_sent": catchup_sent,
        "dialogue_auto_sent": dialogue.get("auto_reply_sent", 0),
        "dialogue_needs_hr": dialogue.get("needs_hr", 0),
    }
    if summary["enriched"] or enrich_sent or catchup_sent or summary["dialogue_auto_sent"]:
        emit(
            "info",
            f"IM 自动轮次完成：同步 {summary['enriched']} 条回复，"
            f"跟进发送 {enrich_sent + catchup_sent} 人，"
            f"基础问答自动回复 {summary['dialogue_auto_sent']} 人",
            category="im_autopilot",
            workflow_id=workflow_id,
            meta=summary,
        )
    return summary


async def _im_workflow_still_active(workflow_id: str) -> bool:
    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        conv_repo = ConversationRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            return False
        if wf.status in ("FAILED", "COMPLETED", "CANCELLED"):
            return False
        convs = await conv_repo.list_by_workflow(workflow_id)
        if not convs:
            return wf.status in ("SCREENING_COMPLETED", "CONVERSATIONS_STARTED", "FETCHING")
        for conv in convs:
            if conv.status in ("WAITING_REPLY", "MESSAGE_DRAFTED", "REPLY_RECEIVED"):
                return True
            if conv.need_resume_request:
                msgs = await conv_repo.list_messages(conv.id)
                if not any(
                    m.direction == "outbound"
                    and m.status == "sent"
                    and conv.conversation_type == "resume_request"
                    for m in msgs
                ):
                    return True
        return False


async def run_im_autopilot_monitor(workflow_id: str) -> None:
    """后台定期同步回复并自动跟进，直至会话趋于静止。"""
    if workflow_id in _monitor_running:
        return
    stop_ev = _get_stop_event(workflow_id)
    _monitor_running.add(workflow_id)
    try:
        emit(
            "info",
            "IM 自动跟进已启动（同步回复 → Agent 判定 → 自动发送）",
            category="im_autopilot",
            workflow_id=workflow_id,
        )
        idle_streak = 0
        for cycle in range(IM_MONITOR_MAX_CYCLES):
            from packages.workflow_control import wait_if_paused

            await wait_if_paused(workflow_id)
            if stop_ev.is_set():
                emit(
                    "warn",
                    "IM Agent 已停止，已切回简历筛选",
                    category="im_autopilot",
                    workflow_id=workflow_id,
                )
                break
            if cycle > 0:
                await asyncio.sleep(IM_MONITOR_INTERVAL_SEC)
                if stop_ev.is_set():
                    emit(
                        "warn",
                        "IM Agent 已停止，已切回简历筛选",
                        category="im_autopilot",
                        workflow_id=workflow_id,
                    )
                    break
            if not await _im_workflow_still_active(workflow_id):
                break
            summary = await run_im_autopilot_cycle(workflow_id)
            if summary.get("stopped"):
                break
            if (
                summary["enriched"] == 0
                and summary["enrich_sent"] == 0
                and summary["catchup_sent"] == 0
                and summary.get("dialogue_auto_sent", 0) == 0
            ):
                idle_streak += 1
                if idle_streak >= 3:
                    break
            else:
                idle_streak = 0

        emit(
            "success",
            "IM 自动跟进已结束，请在工作台查看候选人回复与简历状态",
            category="im_autopilot",
            workflow_id=workflow_id,
        )
    finally:
        _monitor_running.discard(workflow_id)


async def start_im_autopilot(workflow_id: str) -> dict:
    """启动 IM Agent：立即执行一轮触达/同步，并启动后台定期跟进。"""
    _get_stop_event(workflow_id).clear()
    already_running = workflow_id in _monitor_running
    summary = await run_im_autopilot_cycle(workflow_id)
    if already_running:
        emit(
            "info",
            "IM Agent 已在运行，已额外执行一轮同步与触达",
            category="im_autopilot",
            workflow_id=workflow_id,
            meta=summary,
        )
        return {"status": "cycle_only", "already_running": True, **summary}

    from packages.background_tasks import spawn

    spawn(run_im_autopilot_monitor(workflow_id), workflow_id=workflow_id)
    emit(
        "success",
        "IM Agent 已启动：补发遗漏并开始定期跟进",
        category="im_autopilot",
        workflow_id=workflow_id,
        meta=summary,
    )
    return {"status": "started", "already_running": False, **summary}


async def run_post_screening_im_autopilot(workflow_id: str) -> None:
    """初筛完成后自动启动 IM Agent。"""
    await start_im_autopilot(workflow_id)
