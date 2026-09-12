"""Persistent candidate dialogue orchestration for IM conversations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import CandidateSnapshot, OutreachConversation, OutreachMessage
from packages.db.repositories import CandidateRepository, ConversationRepository, WorkflowRepository
from packages.db.session import async_session_factory
from packages.outreach_policy import workflow_im_review_required
from packages.schemas.outreach import CandidateDialogueOutput
from services.agent_service.candidate_dialogue_agent import generate_candidate_dialogue_reply
from services.agent_service.outreach_draft_utils import get_pending_outbound_draft
from services.fetch_worker.im_chat_runner import IMSendTarget, run_im_send_batch


def _message_payload(message: OutreachMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "direction": message.direction,
        "message_text": message.message_text,
        "status": message.status,
        "round": message.round,
        "platform_message_id": message.platform_message_id,
        "extracted_fields": message.extracted_fields or {},
    }


def _latest_inbound(messages: list[OutreachMessage]) -> OutreachMessage | None:
    for message in reversed(messages):
        if message.direction == "inbound" and message.message_text.strip():
            return message
    return None


def _reply_key(message: OutreachMessage) -> str:
    return message.platform_message_id or message.id


def _already_answered(messages: list[OutreachMessage], inbound: OutreachMessage) -> bool:
    key = _reply_key(inbound)
    for message in messages:
        if message.direction != "outbound":
            continue
        fields = message.extracted_fields or {}
        if fields.get("agent_type") != "candidate_dialogue_agent":
            continue
        if fields.get("reply_to_message_id") == key:
            return True
    return False


def _candidate_profile(snap: CandidateSnapshot | None) -> dict[str, Any]:
    if not snap:
        return {}
    return {
        "display_name": snap.display_name,
        "current_title": snap.current_title,
        "current_company": snap.current_company,
        "work_years": float(snap.work_years) if snap.work_years else None,
        "education": snap.education,
        "city": snap.city,
        "skills": snap.skills or [],
        "metadata": snap.metadata_ or {},
    }


def _target_from_snapshot(snap: CandidateSnapshot, message_text: str, conversation_id: str) -> IMSendTarget:
    meta = snap.metadata_ or {}
    return IMSendTarget(
        candidate_snapshot_id=snap.id,
        display_name=snap.display_name,
        message_text=message_text,
        conversation_id=conversation_id,
        age=str(meta.get("age") or "") or None,
        school=str(meta.get("school") or "") or None,
        education=snap.education,
        current_title=snap.current_title,
        chat_initiated_at=str(meta.get("chat_initiated_at") or "") or None,
    )


def _dialogue_fields(output: CandidateDialogueOutput, inbound: OutreachMessage) -> dict[str, Any]:
    return {
        "agent_type": "candidate_dialogue_agent",
        "reply_to_message_id": _reply_key(inbound),
        "question_type": output.question_type,
        "answer_source": output.answer_source,
        "auto_send_allowed": output.auto_send_allowed,
        "confidence": output.confidence,
        "action": output.action,
        "reason": output.reason,
        "history_used": output.history_used,
    }


async def _draft_for_inbound(
    *,
    session: AsyncSession,
    conv: OutreachConversation,
    messages: list[OutreachMessage],
    inbound: OutreachMessage,
) -> tuple[CandidateDialogueOutput, OutreachMessage | None]:
    wf_repo = WorkflowRepository(session)
    candidate_repo = CandidateRepository(session)
    conv_repo = ConversationRepository(session)
    wf = await wf_repo.get(conv.workflow_id)
    snap = await candidate_repo.get(conv.candidate_snapshot_id)
    wf_config = wf.config if wf else {}
    reply_key = _reply_key(inbound)
    pending = get_pending_outbound_draft(
        messages,
        agent_type="candidate_dialogue_agent",
        reply_to_message_id=reply_key,
    )
    if pending:
        fields = pending.extracted_fields or {}
        output = CandidateDialogueOutput(
            action=str(fields.get("action") or "draft_only"),
            message_text=pending.message_text,
            question_type=str(fields.get("question_type") or "unknown"),
            answer_source=str(fields.get("answer_source") or ""),
            auto_send_allowed=bool(fields.get("auto_send_allowed")),
            confidence=float(fields.get("confidence") or 0.0),
            reason=str(fields.get("reason") or "已有草稿待确认"),
            history_used=bool(fields.get("history_used")),
        )
        return output, pending

    output = generate_candidate_dialogue_reply(
        candidate_snapshot_id=conv.candidate_snapshot_id,
        latest_message=inbound.message_text,
        conversation_history=[_message_payload(m) for m in messages],
        candidate_profile=_candidate_profile(snap),
        workflow_config=wf_config,
        job_qa_profile=(wf_config or {}).get("job_qa_profile") if isinstance(wf_config, dict) else {},
        hr_preference_memory=(wf_config or {}).get("hr_preference_memory") if isinstance(wf_config, dict) else {},
    )
    if output.action == "no_action" or not output.message_text.strip():
        await conv_repo.update_status(conv.id, "REPLY_RECEIVED", last_agent_reason=output.reason)
        return output, None

    draft = await conv_repo.save_message(
        conversation_id=conv.id,
        candidate_snapshot_id=conv.candidate_snapshot_id,
        direction="outbound",
        message_text=output.message_text,
        status="drafted",
        round_num=(conv.current_round or 0) + 1,
        extracted_fields=_dialogue_fields(output, inbound),
    )
    status = "DRAFT_READY" if output.action == "draft_only" else "NEEDS_HR"
    if output.action == "auto_reply" and output.auto_send_allowed:
        status = "DRAFT_READY"
    await conv_repo.update_status(
        conv.id,
        status,
        current_round=draft.round or conv.current_round,
        last_agent_reason=output.reason,
    )
    return output, draft


async def process_pending_dialogue_replies(workflow_id: str) -> dict[str, int]:
    counts = {
        "processed": 0,
        "auto_reply_sent": 0,
        "drafted": 0,
        "needs_hr": 0,
        "no_action": 0,
        "skipped_duplicate": 0,
        "failed": 0,
    }
    pending_sends: list[tuple[str, str, IMSendTarget]] = []
    browser_profile = "hr_default"
    im_review = False

    async with async_session_factory() as session:
        wf_repo = WorkflowRepository(session)
        conv_repo = ConversationRepository(session)
        candidate_repo = CandidateRepository(session)
        wf = await wf_repo.get(workflow_id)
        if not wf:
            raise ValueError(f"Workflow not found: {workflow_id}")
        im_review = workflow_im_review_required(wf.config)
        browser_profile = ((wf.config or {}).get("fetch") or {}).get("browser_profile", "hr_default")
        convs = await conv_repo.list_by_workflow(workflow_id)
        for conv in convs:
            messages = await conv_repo.list_messages(conv.id)
            inbound = _latest_inbound(messages)
            if not inbound:
                continue
            if _already_answered(messages, inbound):
                counts["skipped_duplicate"] += 1
                continue
            if get_pending_outbound_draft(
                messages,
                agent_type="candidate_dialogue_agent",
                reply_to_message_id=_reply_key(inbound),
            ):
                counts["skipped_duplicate"] += 1
                continue

            output, draft = await _draft_for_inbound(
                session=session,
                conv=conv,
                messages=messages,
                inbound=inbound,
            )
            counts["processed"] += 1
            if (
                not im_review
                and output.action == "auto_reply"
                and output.auto_send_allowed
                and draft
            ):
                snap = await candidate_repo.get(conv.candidate_snapshot_id)
                if snap:
                    pending_sends.append(
                        (conv.id, draft.id, _target_from_snapshot(snap, draft.message_text, conv.id))
                    )
                    counts["drafted"] += 1
                else:
                    counts["failed"] += 1
            elif output.action == "auto_reply" and output.auto_send_allowed and draft and im_review:
                counts["drafted"] += 1
            elif output.action == "escalate_to_hr":
                counts["needs_hr"] += 1
            elif output.action == "draft_only":
                counts["drafted"] += 1
            else:
                counts["no_action"] += 1
        await session.commit()

    if pending_sends:
        send_results = await run_im_send_batch(
            [target for _, _, target in pending_sends],
            workflow_id=workflow_id,
            browser_profile=browser_profile,
        )
        result_by_conv = {r.get("conversation_id"): r for r in send_results}
        async with async_session_factory() as session:
            conv_repo = ConversationRepository(session)
            now = datetime.now(timezone.utc)
            for conv_id, message_id, _target in pending_sends:
                result = result_by_conv.get(conv_id) or {}
                if result.get("ok"):
                    await conv_repo.update_message_status(message_id, "sent")
                    await conv_repo.update_status(conv_id, "WAITING_REPLY", last_message_at=now)
                    counts["auto_reply_sent"] += 1
                else:
                    err = str(result.get("error") or "IM send failed")
                    await conv_repo.update_message_status(message_id, "failed", error_message=err)
                    await conv_repo.update_status(conv_id, "DRAFT_READY", last_agent_reason=err)
                    counts["failed"] += 1
            await session.commit()

    return counts


async def draft_dialogue_reply_for_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> dict[str, Any]:
    conv_repo = ConversationRepository(session)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        raise ValueError(f"Conversation not found: {conversation_id}")
    messages = await conv_repo.list_messages(conversation_id)
    inbound = _latest_inbound(messages)
    if not inbound:
        raise ValueError("No inbound message available for dialogue draft")
    if _already_answered(messages, inbound):
        raise ValueError("Latest inbound message has already been answered")
    output, draft = await _draft_for_inbound(
        session=session,
        conv=conv,
        messages=messages,
        inbound=inbound,
    )
    await session.commit()
    return {
        "conversation_id": conversation_id,
        "message_id": draft.id if draft else None,
        "output": output.model_dump(),
    }


async def send_dialogue_draft_for_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> dict[str, Any]:
    conv_repo = ConversationRepository(session)
    candidate_repo = CandidateRepository(session)
    wf_repo = WorkflowRepository(session)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        raise ValueError(f"Conversation not found: {conversation_id}")
    wf = await wf_repo.get(conv.workflow_id)
    snap = await candidate_repo.get(conv.candidate_snapshot_id)
    if not wf or not snap:
        raise ValueError("Conversation workflow or candidate not found")
    messages = await conv_repo.list_messages(conversation_id)
    draft = next(
        (
            m
            for m in reversed(messages)
            if m.direction == "outbound"
            and m.status in ("drafted", "failed")
            and (m.extracted_fields or {}).get("agent_type") == "candidate_dialogue_agent"
        ),
        None,
    )
    if not draft:
        raise ValueError("No dialogue draft available to send")
    browser_profile = ((wf.config or {}).get("fetch") or {}).get("browser_profile", "hr_default")
    target = _target_from_snapshot(snap, draft.message_text, conv.id)
    await session.commit()

    result = (await run_im_send_batch([target], workflow_id=conv.workflow_id, browser_profile=browser_profile))[0]
    if result.get("ok"):
        await conv_repo.update_message_status(draft.id, "sent")
        await conv_repo.update_status(
            conv.id,
            "WAITING_REPLY",
            last_message_at=datetime.now(timezone.utc),
        )
    else:
        await conv_repo.update_message_status(draft.id, "failed", error_message=str(result.get("error") or "send failed"))
    await session.commit()
    return {"conversation_id": conv.id, "message_id": draft.id, "send": result}
