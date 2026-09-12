from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from packages.db.repositories import CandidateRepository, ConversationRepository, ScreeningRepository

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/{snapshot_id}")
async def get_candidate_detail(snapshot_id: str, db: AsyncSession = Depends(get_db)):
    candidate_repo = CandidateRepository(db)
    snap = await candidate_repo.get(snapshot_id)
    if not snap:
        raise HTTPException(404, "Candidate snapshot not found")

    screening_repo = ScreeningRepository(db)
    screening = await screening_repo.get_latest_for_candidate(snap.workflow_id, snapshot_id)

    conv_repo = ConversationRepository(db)
    conversation = await conv_repo.get_by_candidate(snap.workflow_id, snapshot_id)
    messages = []
    if conversation:
        messages = await conv_repo.list_messages(conversation.id)

    return {
        "snapshot": {
            "id": snap.id,
            "workflow_id": snap.workflow_id,
            "platform": snap.platform,
            "source_candidate_id": snap.source_candidate_id,
            "source_url": snap.source_url,
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
            "raw_text": snap.raw_text,
            "extraction_confidence": float(snap.extraction_confidence) if snap.extraction_confidence else None,
            "metadata": snap.metadata_ or {},
            "captured_at": snap.captured_at.isoformat(),
        },
        "screening": {
            "total_score": float(screening.total_score) if screening and screening.total_score else None,
            "level": screening.level if screening else None,
            "matched_points": screening.matched_points if screening else [],
            "gaps": screening.gaps if screening else [],
            "missing_info": screening.missing_info if screening else [],
            "suggested_action": screening.suggested_action if screening else None,
        } if screening else None,
        "conversation": {
            "id": conversation.id,
            "status": conversation.status,
            "current_round": conversation.current_round,
            "messages": [
                {
                    "id": m.id,
                    "direction": m.direction,
                    "message_text": m.message_text,
                    "status": m.status,
                    "round": m.round,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        } if conversation else None,
    }
