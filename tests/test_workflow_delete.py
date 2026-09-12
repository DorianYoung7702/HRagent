"""Tests for permanent workflow deletion from recruiting.db."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import (
    Base,
    CandidateProfileCurrent,
    CandidateScreeningResult,
    CandidateSnapshot,
    OutreachConversation,
    OutreachMessage,
    RecruitingWorkflow,
    Shortlist,
    ShortlistCandidate,
)
from packages.db.repositories import (
    CandidateRepository,
    ConversationRepository,
    ProfileRepository,
    ScreeningRepository,
    WorkflowRepository,
)
from packages.schemas.candidate import CandidateSnapshotData
from packages.schemas.screening import ScreeningOutput
from packages.schemas.screening import ShortlistCandidate as ShortlistCandidateSchema


@pytest.fixture
def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'delete_test.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


@pytest.mark.asyncio
async def test_delete_workflow_data_removes_all_related_rows(session_factory):
    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        screening_repo = ScreeningRepository(session)
        conv_repo = ConversationRepository(session)

        wf = await wf_repo.create(
            name="测试任务",
            platform="liepin",
            start_url="https://example.com",
            job_id=None,
            config={"fetch": {"target_count": 5}},
        )
        snap = CandidateSnapshot(
            workflow_id=wf.id,
            platform="liepin",
            raw_text="简历",
        )
        session.add(snap)
        await session.flush()

        await screening_repo.save_result(
            wf.id,
            None,
            ScreeningOutput(
                candidate_snapshot_id=snap.id,
                total_score=80.0,
                level="A",
                score_detail={},
                matched_points=[],
                gaps=[],
                missing_info=[],
                suggested_action="contact",
            ),
        )
        shortlist = await screening_repo.create_shortlist(
            wf.id,
            None,
            [],
            min_score=70.0,
            total_candidates=1,
        )
        profile = CandidateProfileCurrent(
            workflow_id=wf.id,
            candidate_snapshot_id=snap.id,
            merged_profile={"name": "张三"},
        )
        session.add(profile)

        conv = await conv_repo.create(wf.id, snap.id, [])
        await conv_repo.save_message(
            conv.id,
            snap.id,
            "outbound",
            "你好",
            status="sent",
        )
        await session.commit()

        wf_id = wf.id
        shortlist_id = shortlist.id
        conv_id = conv.id

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        assert await wf_repo.delete_workflow_data(wf_id)
        await session.commit()

    async with factory() as session:
        assert (
            await session.execute(
                select(RecruitingWorkflow).where(RecruitingWorkflow.id == wf_id)
            )
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(CandidateSnapshot).where(CandidateSnapshot.workflow_id == wf_id)
            )
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(CandidateScreeningResult).where(
                    CandidateScreeningResult.workflow_id == wf_id
                )
            )
        ).scalar_one_or_none() is None
        assert (
            await session.execute(select(Shortlist).where(Shortlist.id == shortlist_id))
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(ShortlistCandidate).where(ShortlistCandidate.shortlist_id == shortlist_id)
            )
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(OutreachConversation).where(OutreachConversation.id == conv_id)
            )
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(OutreachMessage).where(OutreachMessage.conversation_id == conv_id)
            )
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(CandidateProfileCurrent).where(CandidateProfileCurrent.workflow_id == wf_id)
            )
        ).scalar_one_or_none() is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_workflow_data_missing_returns_false(session_factory):
    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        assert not await wf_repo.delete_workflow_data("missing-id")

    await engine.dispose()


@pytest.mark.asyncio
async def test_candidate_snapshot_platform_must_match_workflow(session_factory):
    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        candidate_repo = CandidateRepository(session)
        wf = await wf_repo.create(
            name="猎聘任务",
            platform="liepin",
            start_url="https://lpt.liepin.com/search",
            job_id=None,
            config={"platform": "liepin"},
        )

        with pytest.raises(ValueError, match="platform"):
            await candidate_repo.save_snapshot(
                CandidateSnapshotData(
                    workflow_id=wf.id,
                    platform="boss",
                    display_name="跨平台候选人",
                    raw_text="简历",
                )
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_candidate_owned_by_one_platform_workflow_cannot_be_reused_by_another(session_factory):
    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        candidate_repo = CandidateRepository(session)
        screening_repo = ScreeningRepository(session)
        conv_repo = ConversationRepository(session)
        profile_repo = ProfileRepository(session)

        liepin = await wf_repo.create(
            name="猎聘任务",
            platform="liepin",
            start_url="https://lpt.liepin.com/search",
            job_id="same_job",
            config={"platform": "liepin"},
        )
        boss = await wf_repo.create(
            name="BOSS任务",
            platform="boss",
            start_url="https://www.zhipin.com/web/geek/job",
            job_id="same_job",
            config={"platform": "boss"},
        )
        snap = await candidate_repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=liepin.id,
                platform="liepin",
                display_name="猎聘候选人",
                raw_text="简历",
            )
        )

        output = ScreeningOutput(
            candidate_snapshot_id=snap.id,
            total_score=80.0,
            level="A",
            score_detail={},
            matched_points=[],
            gaps=[],
            missing_info=[],
            suggested_action="contact",
        )

        with pytest.raises(ValueError, match="workflow"):
            await screening_repo.save_result(boss.id, boss.job_id, output)

        with pytest.raises(ValueError, match="workflow"):
            await screening_repo.create_shortlist(
                boss.id,
                boss.job_id,
                [
                    ShortlistCandidateSchema(
                        candidate_snapshot_id=snap.id,
                        score=80.0,
                        level="A",
                        rank=1,
                    )
                ],
                min_score=60.0,
                total_candidates=1,
            )

        with pytest.raises(ValueError, match="workflow"):
            await conv_repo.create(boss.id, snap.id, [])

        with pytest.raises(ValueError, match="workflow"):
            await profile_repo.upsert_merged_profile(boss.id, snap.id, {"name": "猎聘候选人"})

        with pytest.raises(ValueError, match="workflow"):
            await profile_repo.save_supplemental(
                boss.id,
                snap.id,
                raw_message="你好",
                extracted_fields={},
                confidence=0.8,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_liepin_workflow_preserves_boss_workflow_in_same_platform_group(session_factory):
    setup, engine = session_factory
    factory = await setup()

    group_id = "group_shared"
    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        candidate_repo = CandidateRepository(session)

        liepin = await wf_repo.create(
            name="同设定 - 猎聘",
            platform="liepin",
            start_url="https://lpt.liepin.com/search",
            job_id="same_job",
            config={"platform_group": {"id": group_id, "platforms": ["liepin", "boss"]}},
        )
        boss = await wf_repo.create(
            name="同设定 - BOSS",
            platform="boss",
            start_url="https://www.zhipin.com/web/geek/job",
            job_id="same_job",
            config={"platform_group": {"id": group_id, "platforms": ["liepin", "boss"]}},
        )
        boss_snap = await candidate_repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=boss.id,
                platform="boss",
                display_name="BOSS候选人",
                raw_text="BOSS简历",
            )
        )
        liepin_snap = await candidate_repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=liepin.id,
                platform="liepin",
                display_name="猎聘候选人",
                raw_text="猎聘简历",
            )
        )
        await session.commit()

        liepin_id = liepin.id
        boss_id = boss.id
        boss_snap_id = boss_snap.id
        liepin_snap_id = liepin_snap.id

    async with factory() as session:
        wf_repo = WorkflowRepository(session)
        assert await wf_repo.delete_workflow_data(liepin_id)
        await session.commit()

    async with factory() as session:
        assert (
            await session.execute(select(RecruitingWorkflow).where(RecruitingWorkflow.id == boss_id))
        ).scalar_one_or_none() is not None
        assert (
            await session.execute(select(CandidateSnapshot).where(CandidateSnapshot.id == boss_snap_id))
        ).scalar_one_or_none() is not None
        assert (
            await session.execute(select(CandidateSnapshot).where(CandidateSnapshot.id == liepin_snap_id))
        ).scalar_one_or_none() is None

    await engine.dispose()
