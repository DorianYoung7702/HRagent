
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import OutreachConversation
from packages.db.repositories import (
    CandidateRepository,
    ConversationRepository,
    ProfileRepository,
    ScreeningRepository,
    WorkflowRepository,
)
from services.agent_service.reply_parser_agent import parse_reply
from services.agent_service.rescreening_agent import rescreen_candidate


async def process_reply_inline(
    db: AsyncSession, conv: OutreachConversation, message_text: str
) -> dict:
    conv_repo = ConversationRepository(db)
    screening_repo = ScreeningRepository(db)
    candidate_repo = CandidateRepository(db)
    profile_repo = ProfileRepository(db)
    wf_repo = WorkflowRepository(db)

    screening = await screening_repo.get_latest_for_candidate(conv.workflow_id, conv.candidate_snapshot_id)
    messages = await conv_repo.list_messages(conv.id)
    history = [m.message_text for m in messages if m.direction == "outbound"]

    parsed = await parse_reply(
        candidate_snapshot_id=conv.candidate_snapshot_id,
        raw_message=message_text,
        missing_info=conv.missing_info or [],
        conversation_history=history,
    )

    await conv_repo.update_status(conv.id, "REPLY_PARSED")
    await profile_repo.save_supplemental(
        workflow_id=conv.workflow_id,
        candidate_snapshot_id=conv.candidate_snapshot_id,
        raw_message=message_text,
        extracted_fields=parsed.extracted_fields,
        confidence=parsed.confidence,
    )

    snap = await candidate_repo.get(conv.candidate_snapshot_id)
    original_profile = {
        "display_name": snap.display_name,
        "current_title": snap.current_title,
        "skills": snap.skills,
        "experience_summary": snap.experience_summary,
        "project_summary": snap.project_summary,
    }
    merged = {**original_profile, **parsed.extracted_fields}
    await profile_repo.upsert_merged_profile(conv.workflow_id, conv.candidate_snapshot_id, merged)
    await conv_repo.update_status(conv.id, "PROFILE_UPDATED")

    wf = await wf_repo.get(conv.workflow_id)
    job_desc = wf.config.get("job", {}).get("description", "") if wf else ""
    old_score = float(screening.total_score) if screening and screening.total_score else 0

    rescreen = await rescreen_candidate(
        candidate_snapshot_id=conv.candidate_snapshot_id,
        job_description=job_desc,
        original_profile=original_profile,
        supplemental_fields=parsed.extracted_fields,
        old_score=old_score,
        missing_info=conv.missing_info or [],
    )

    from packages.schemas.screening import ScreeningOutput

    screening_output = ScreeningOutput(
        candidate_snapshot_id=conv.candidate_snapshot_id,
        total_score=rescreen.new_score,
        level=rescreen.level,
        matched_points=[],
        gaps=[],
        missing_info=rescreen.remaining_missing_info,
        suggested_action=rescreen.decision,
    )
    await screening_repo.save_result(
        conv.workflow_id,
        wf.job_id if wf else None,
        screening_output,
        round_num=2,
    )

    if rescreen.decision == "recommend_to_hr":
        await conv_repo.update_status(conv.id, "READY_FOR_HR")
    elif rescreen.decision == "reject":
        await conv_repo.update_status(conv.id, "REJECTED")
    elif rescreen.decision == "ask_followup":
        await conv_repo.update_status(
            conv.id,
            "FOLLOW_UP_REQUIRED",
            missing_info=[m.model_dump() for m in rescreen.remaining_missing_info],
        )
    else:
        await conv_repo.update_status(conv.id, "RESCREENED")

    return {
        "parsed": parsed.model_dump(),
        "rescreening": rescreen.model_dump(),
        "conversation_status": conv.status,
    }
