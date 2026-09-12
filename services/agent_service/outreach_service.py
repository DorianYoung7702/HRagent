from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import RecruitingWorkflow
from packages.db.repositories import CandidateRepository, ConversationRepository, ScreeningRepository
from packages.settings import get_settings
from services.agent_service.outreach_agent import generate_outreach_message
from services.fetch_worker.message_sender import send_platform_message


async def start_conversations_for_workflow(
    db: AsyncSession, wf: RecruitingWorkflow
) -> list[dict]:
    if not wf.shortlist_id:
        return []

    screening_repo = ScreeningRepository(db)
    conv_repo = ConversationRepository(db)
    candidate_repo = CandidateRepository(db)
    _, shortlist_candidates = await screening_repo.get_shortlist(wf.shortlist_id)

    results = []
    outreach_config = wf.config.get("outreach", {})
    send_mode = outreach_config.get("send_mode", get_settings().send_mode)

    for sc in shortlist_candidates:
        existing = await conv_repo.get_by_candidate(wf.id, sc.candidate_snapshot_id)
        if existing:
            results.append({"conversation_id": existing.id, "status": existing.status})
            continue

        screening = await screening_repo.get_latest_for_candidate(wf.id, sc.candidate_snapshot_id)
        snap = await candidate_repo.get(sc.candidate_snapshot_id)
        missing_info = screening.missing_info if screening else []

        conv = await conv_repo.create(
            workflow_id=wf.id,
            candidate_snapshot_id=sc.candidate_snapshot_id,
            missing_info=missing_info,
        )

        message_output = await generate_outreach_message(
            candidate_snapshot_id=sc.candidate_snapshot_id,
            display_name=snap.display_name if snap else None,
            current_title=snap.current_title if snap else None,
            matched_points=screening.matched_points if screening else [],
            missing_info=missing_info,
            round_num=1,
            job_title=wf.config.get("job", {}).get("title"),
        )

        msg = await conv_repo.save_message(
            conversation_id=conv.id,
            candidate_snapshot_id=sc.candidate_snapshot_id,
            direction="outbound",
            message_text=message_output.message_text,
            status="drafted",
            round_num=1,
        )

        await conv_repo.update_status(conv.id, "MESSAGE_DRAFTED", current_round=1)

        if send_mode == "auto_send":
            try:
                await send_platform_message(sc.candidate_snapshot_id, message_output.message_text, "auto_send")
                await conv_repo.update_message_status(msg.id, "sent")
                await conv_repo.update_status(
                    conv.id, "WAITING_REPLY", last_message_at=datetime.now(timezone.utc)
                )
            except Exception:
                pass

        results.append({
            "conversation_id": conv.id,
            "message_id": msg.id,
            "status": "MESSAGE_DRAFTED",
            "message_text": message_output.message_text,
        })

    return results


async def generate_outreach_draft_for_conversation(db: AsyncSession, conv) -> dict:
    screening_repo = ScreeningRepository(db)
    candidate_repo = CandidateRepository(db)
    conv_repo = ConversationRepository(db)

    screening = await screening_repo.get_latest_for_candidate(conv.workflow_id, conv.candidate_snapshot_id)
    snap = await candidate_repo.get(conv.candidate_snapshot_id)
    next_round = conv.current_round + 1

    message_output = await generate_outreach_message(
        candidate_snapshot_id=conv.candidate_snapshot_id,
        display_name=snap.display_name if snap else None,
        current_title=snap.current_title if snap else None,
        matched_points=screening.matched_points if screening else [],
        missing_info=conv.missing_info or [],
        round_num=next_round,
    )

    msg = await conv_repo.save_message(
        conversation_id=conv.id,
        candidate_snapshot_id=conv.candidate_snapshot_id,
        direction="outbound",
        message_text=message_output.message_text,
        status="drafted",
        round_num=next_round,
    )
    await conv_repo.update_status(conv.id, "MESSAGE_DRAFTED", current_round=next_round)

    return {
        "conversation_id": conv.id,
        "message_id": msg.id,
        "round": next_round,
        "message_text": message_output.message_text,
        "questions_asked": message_output.questions_asked,
    }
