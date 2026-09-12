import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from packages.db.repositories import ConversationRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/outreach_messages", tags=["messages"])


class OutreachMessageUpdateRequest(BaseModel):
    message_text: str = Field(min_length=1)


@router.patch("/{message_id}")
async def update_outreach_message(
    message_id: str,
    body: OutreachMessageUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Edit drafted outbound IM text before HR confirms send."""
    conv_repo = ConversationRepository(db)
    msg = await conv_repo.get_message(message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg.direction != "outbound":
        raise HTTPException(400, "Only outbound messages can be edited")
    if msg.status not in ("drafted", "failed"):
        raise HTTPException(400, f"Cannot edit message in status: {msg.status}")

    await conv_repo.update_message_text(message_id, body.message_text.strip())
    await db.commit()
    return {
        "id": msg.id,
        "message_text": body.message_text.strip(),
        "status": "drafted",
    }


@router.post("/{message_id}/send")
async def confirm_and_send_message(
    message_id: str,
    db: AsyncSession = Depends(get_db),
):
    """人工确认后，通过 Playwright 将私信填入/发送到平台。"""
    from services.fetch_worker.im_chat_runner import run_im_send_batch
    from services.agent_service.followup_conversation_service import _im_target_from_snap
    from packages.db.repositories import CandidateRepository, WorkflowRepository

    conv_repo = ConversationRepository(db)
    msg = await conv_repo.get_message(message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg.status not in ("drafted", "failed"):
        raise HTTPException(400, f"Cannot send message in status: {msg.status}")

    conv = await conv_repo.get(msg.conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    wf_repo = WorkflowRepository(db)
    candidate_repo = CandidateRepository(db)
    wf = await wf_repo.get(conv.workflow_id)
    snap = await candidate_repo.get(msg.candidate_snapshot_id)
    if not wf or not snap:
        raise HTTPException(404, "Workflow or candidate not found")

    browser_profile = ((wf.config or {}).get("fetch") or {}).get("browser_profile", "hr_default")
    target = _im_target_from_snap(
        snap,
        msg.candidate_snapshot_id,
        msg.message_text,
        conversation_id=conv.id,
    )

    try:
        result = (await run_im_send_batch(
            [target],
            workflow_id=conv.workflow_id,
            browser_profile=browser_profile,
        ))[0]
        if not result.get("ok"):
            err = str(result.get("error") or "Send failed")
            await conv_repo.update_message_status(message_id, "failed", error_message=err)
            await db.commit()
            raise HTTPException(500, f"Send failed: {err}")
        await conv_repo.update_message_status(message_id, "sent")
        await conv_repo.update_status(
            conv.id,
            "WAITING_REPLY",
            current_round=msg.round or conv.current_round,
            last_message_at=msg.created_at,
        )
        await db.commit()
        return {"status": "sent", "message_id": message_id, "platform_result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to send message %s", message_id)
        await conv_repo.update_message_status(message_id, "failed", error_message=str(e))
        await db.commit()
        raise HTTPException(500, f"Send failed: {e}") from e


@router.get("/{message_id}")
async def get_message(message_id: str, db: AsyncSession = Depends(get_db)):
    conv_repo = ConversationRepository(db)
    msg = await conv_repo.get_message(message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "candidate_snapshot_id": msg.candidate_snapshot_id,
        "direction": msg.direction,
        "message_text": msg.message_text,
        "status": msg.status,
        "round": msg.round,
        "created_at": msg.created_at.isoformat(),
    }
