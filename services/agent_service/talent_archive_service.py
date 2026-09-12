"""Backfill the opt-in cross-workflow talent archive from existing results."""

from __future__ import annotations

from sqlalchemy import select

from packages.db.models import CandidateScreeningResult, CandidateSnapshot
from packages.db.repositories import TalentArchiveRepository
from packages.db.session import async_session_factory
from packages.talent_archive_policy import talent_archive_enabled

ARCHIVABLE_LEVELS = {"observe", "followup", "recommend", "backup"}


async def backfill_talent_archive() -> int:
    """Idempotently archive the latest non-excluded result for each prior snapshot."""

    if not talent_archive_enabled():
        return 0
    async with async_session_factory() as session:
        rows = await session.execute(
            select(CandidateScreeningResult).order_by(
                CandidateScreeningResult.candidate_snapshot_id,
                CandidateScreeningResult.screening_round.desc(),
                CandidateScreeningResult.created_at.desc(),
            )
        )
        latest: dict[str, CandidateScreeningResult] = {}
        for result in rows.scalars():
            latest.setdefault(result.candidate_snapshot_id, result)

        archive = TalentArchiveRepository(session)
        archived_count = 0
        for result in latest.values():
            if (result.level or "").lower() not in ARCHIVABLE_LEVELS:
                continue
            snapshot = await session.get(CandidateSnapshot, result.candidate_snapshot_id)
            if snapshot and await archive.upsert_from_screening(snapshot, result):
                archived_count += 1
        await session.commit()
        return archived_count
