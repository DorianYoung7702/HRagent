from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base
from packages.db.repositories import CandidateRepository, ScreeningRepository, WorkflowRepository
from packages.schemas.candidate import CandidateSnapshotData
from packages.schemas.screening import ScreeningOutput


@pytest.fixture
def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'screening_identity.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


@pytest.mark.asyncio
async def test_rebuild_shortlist_uses_unique_candidate_identity(session_factory):
    from services.agent_service.screening_service import rebuild_shortlist_from_latest

    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf = await WorkflowRepository(session).create(
            name="dedupe",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={"job": {"job_id": "job-1", "description": ""}},
        )
        candidate_repo = CandidateRepository(session)
        screening_repo = ScreeningRepository(session)
        first = await candidate_repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=wf.id,
                platform="liepin",
                display_name="Zhao",
                raw_text="resume stable text Zhao Spanish sales Mexico",
                education="Tianjin Foreign Studies University",
                city="Shenzhen",
                work_years=4,
            )
        )
        duplicate = await candidate_repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=wf.id,
                platform="liepin",
                display_name="Zhao",
                raw_text="resume stable text Zhao Spanish sales Mexico",
                education="Tianjin Foreign Studies University",
                city="Shenzhen",
                work_years=4,
            )
        )
        await screening_repo.save_result(
            wf.id,
            "job-1",
            ScreeningOutput(
                candidate_snapshot_id=first.id,
                total_score=88,
                level="observe",
                matched_points=["Spanish"],
                suggested_action="observe",
            ),
        )
        await screening_repo.save_result(
            wf.id,
            "job-1",
            ScreeningOutput(
                candidate_snapshot_id=duplicate.id,
                total_score=92,
                level="observe",
                matched_points=["Spanish", "Latam"],
                suggested_action="observe",
            ),
        )

        result = await rebuild_shortlist_from_latest(
            wf.id,
            job_id="job-1",
            top_k=10,
            min_score=60,
            session=session,
        )

    await engine.dispose()

    assert result.screened_count == 1
    assert len(result.shortlist) == 1
    assert result.shortlist[0].candidate_snapshot_id == duplicate.id


@pytest.mark.asyncio
async def test_rebuild_shortlist_ranks_observe_and_followup_together(session_factory):
    from services.agent_service.screening_service import rebuild_shortlist_from_latest

    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf = await WorkflowRepository(session).create(
            name="ranking",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={"job": {"job_id": "job-1", "description": ""}},
        )
        candidate_repo = CandidateRepository(session)
        screening_repo = ScreeningRepository(session)
        observe_snap = await candidate_repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=wf.id,
                platform="liepin",
                display_name="Observe",
                raw_text="observe candidate",
            )
        )
        followup_snap = await candidate_repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=wf.id,
                platform="liepin",
                display_name="Followup",
                raw_text="followup candidate",
            )
        )
        await screening_repo.save_result(
            wf.id,
            "job-1",
            ScreeningOutput(
                candidate_snapshot_id=observe_snap.id,
                total_score=88,
                level="observe",
                suggested_action="contact_now",
            ),
        )
        await screening_repo.save_result(
            wf.id,
            "job-1",
            ScreeningOutput(
                candidate_snapshot_id=followup_snap.id,
                total_score=65,
                level="followup",
                suggested_action="ask_for_more_info",
            ),
        )

        result = await rebuild_shortlist_from_latest(
            wf.id,
            job_id="job-1",
            top_k=10,
            min_score=60,
            session=session,
        )

    await engine.dispose()

    assert len(result.shortlist) == 2
    assert result.shortlist[0].level == "observe"
    assert result.shortlist[0].rank == 1
    assert result.shortlist[1].level == "followup"
    assert result.shortlist[1].rank == 2
