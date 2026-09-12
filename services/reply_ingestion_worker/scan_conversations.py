import logging

import httpx

from packages.db.repositories import ConversationRepository
from packages.db.session import async_session_factory
from packages.settings import get_settings
from services.reply_ingestion_worker.platform_chat_reader import read_latest_reply

logger = logging.getLogger(__name__)


async def scan_active_conversations() -> list[dict]:
    settings = get_settings()
    results = []

    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        waiting = await conv_repo.list_waiting_reply()

        for conv in waiting:
            try:
                reply = await read_latest_reply(conv.candidate_snapshot_id)
                if not reply:
                    continue

                existing_messages = await conv_repo.list_messages(conv.id)
                inbound_texts = {
                    m.message_text for m in existing_messages if m.direction == "inbound"
                }
                if reply["message_text"] in inbound_texts:
                    continue

                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{settings.api_base_url}/conversations/{conv.id}/reply",
                        json={
                            "candidate_snapshot_id": conv.candidate_snapshot_id,
                            "message_text": reply["message_text"],
                            "platform_message_id": reply.get("platform_message_id"),
                        },
                        timeout=30,
                    )
                    resp.raise_for_status()
                    results.append({
                        "conversation_id": conv.id,
                        "status": "ingested",
                    })
                    logger.info("Ingested reply for conversation %s", conv.id)
            except Exception as e:
                logger.exception("Failed to scan conversation %s: %s", conv.id, e)
                results.append({
                    "conversation_id": conv.id,
                    "status": "error",
                    "error": str(e),
                })

    return results
