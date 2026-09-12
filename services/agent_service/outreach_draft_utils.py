"""Shared helpers for outbound IM drafts (reuse vs create)."""

from __future__ import annotations

from typing import Any

from packages.db.models import OutreachMessage

PENDING_OUTBOUND_STATUSES = frozenset({"drafted", "failed"})


def get_pending_outbound_draft(
    messages: list[OutreachMessage],
    *,
    agent_type: str | None = None,
    reply_to_message_id: str | None = None,
) -> OutreachMessage | None:
    """Return the latest outbound draft waiting for HR send/edit."""
    for message in reversed(messages):
        if message.direction != "outbound":
            continue
        if message.status not in PENDING_OUTBOUND_STATUSES:
            continue
        fields = message.extracted_fields or {}
        if agent_type is not None and fields.get("agent_type") != agent_type:
            continue
        if reply_to_message_id is not None and fields.get("reply_to_message_id") != reply_to_message_id:
            continue
        if not (message.message_text or "").strip():
            continue
        return message
    return None


def has_pending_outbound_draft(
    messages: list[OutreachMessage],
    *,
    agent_type: str | None = None,
    reply_to_message_id: str | None = None,
) -> bool:
    return get_pending_outbound_draft(
        messages,
        agent_type=agent_type,
        reply_to_message_id=reply_to_message_id,
    ) is not None


def draft_result_from_message(
    message: OutreachMessage,
    *,
    conversation_id: str,
    candidate_snapshot_id: str,
    display_name: str | None = None,
    reason: str = "",
    action: str = "",
    round_num: int | None = None,
    auto_send_allowed: bool = True,
    reused_existing: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "message_id": message.id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "display_name": display_name,
        "message_text": message.message_text,
        "reason": reason,
        "round": round_num if round_num is not None else message.round,
        "action": action,
        "auto_send_allowed": auto_send_allowed,
        "reused_existing": reused_existing,
        **extra,
    }
