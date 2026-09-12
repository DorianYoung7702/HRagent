import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.temporal_client import signal_candidate_reply
from packages.db.repositories import ConversationRepository, WorkflowRepository
from packages.schemas.outreach import ReplyIngestionPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/{conversation_id}/draft")
async def generate_outreach_draft(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    from services.agent_service.outreach_service import generate_outreach_draft_for_conversation

    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    result = await generate_outreach_draft_for_conversation(db, conv)
    return result


@router.post("/{conversation_id}/reply")
async def ingest_candidate_reply(
    conversation_id: str,
    body: ReplyIngestionPayload,
    db: AsyncSession = Depends(get_db),
):
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    msg = await conv_repo.save_message(
        conversation_id=conversation_id,
        candidate_snapshot_id=body.candidate_snapshot_id,
        direction="inbound",
        message_text=body.message_text,
        status="received",
        platform_message_id=body.platform_message_id,
    )
    await conv_repo.update_status(conversation_id, "REPLY_RECEIVED", last_reply_at=msg.created_at)

    if conv.temporal_workflow_id:
        try:
            await signal_candidate_reply(
                conv.temporal_workflow_id,
                {
                    "message_id": msg.id,
                    "message_text": body.message_text,
                    "candidate_snapshot_id": body.candidate_snapshot_id,
                    "platform_message_id": body.platform_message_id,
                },
            )
        except Exception as e:
            logger.warning("Failed to signal Temporal workflow: %s", e)
            from services.agent_service.reply_service import process_reply_inline

            await process_reply_inline(db, conv, body.message_text)
    else:
        from services.agent_service.reply_service import process_reply_inline

        await process_reply_inline(db, conv, body.message_text)

    return {"status": "REPLY_RECEIVED", "message_id": msg.id}


@router.post("/{conversation_id}/dialogue/draft")
async def generate_dialogue_draft(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    from services.agent_service.candidate_dialogue_service import draft_dialogue_reply_for_conversation

    try:
        return await draft_dialogue_reply_for_conversation(db, conversation_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{conversation_id}/dialogue/send")
async def send_dialogue_draft(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    from services.agent_service.candidate_dialogue_service import send_dialogue_draft_for_conversation

    try:
        return await send_dialogue_draft_for_conversation(db, conversation_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    messages = await conv_repo.list_messages(conversation_id)
    return {
        "id": conv.id,
        "workflow_id": conv.workflow_id,
        "candidate_snapshot_id": conv.candidate_snapshot_id,
        "status": conv.status,
        "current_round": conv.current_round,
        "missing_info": conv.missing_info,
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "message_text": m.message_text,
                "status": m.status,
                "round": m.round,
                "extracted_fields": m.extracted_fields or {},
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.post("/start-for-shortlist/{workflow_id}")
async def start_conversations_for_shortlist(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """为 shortlist 候选人创建会话并生成首轮私信草稿。"""
    from services.agent_service.outreach_service import start_conversations_for_workflow

    wf_repo = WorkflowRepository(db)
    wf = await wf_repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if not wf.shortlist_id:
        raise HTTPException(400, "No shortlist available")

    results = await start_conversations_for_workflow(db, wf)
    return {"conversations_started": len(results), "conversations": results}
