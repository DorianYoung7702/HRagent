from __future__ import annotations

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base, TalentArchiveProfile
from packages.db.repositories import (
    CandidateRepository,
    ScreeningRepository,
    TalentArchiveRepository,
    WorkflowRepository,
)
from packages.schemas.candidate import CandidateSnapshotData
from packages.schemas.screening import ScreeningOutput


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("HRAGENT_TALENT_ARCHIVE_ENABLED", "1")
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'archive.db').as_posix()}")

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


async def _create_workflow(session: AsyncSession, name: str):
    return await WorkflowRepository(session).create(
        name=name,
        platform="liepin",
        start_url="https://example.com",
        job_id="job-1",
        config={"job": {"job_id": "job-1", "description": ""}},
    )


def _screening(snapshot_id: str, *, score: float, level: str) -> ScreeningOutput:
    return ScreeningOutput(
        candidate_snapshot_id=snapshot_id,
        total_score=score,
        level=level,
        matched_points=["拉美销售经验"],
        gaps=["需确认到岗时间"],
        score_detail={"summary_for_list": "结构化筛选结果"},
    )


@pytest.mark.asyncio
async def test_non_excluded_candidates_are_deduplicated_in_global_talent_archive(session_factory):
    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        first_workflow = await _create_workflow(session, "岗位 A")
        second_workflow = await _create_workflow(session, "岗位 B")
        candidates = CandidateRepository(session)
        screenings = ScreeningRepository(session)

        first = await candidates.save_snapshot(
            CandidateSnapshotData(
                workflow_id=first_workflow.id,
                platform="liepin",
                display_name="赵先生",
                current_title="墨西哥国家经理",
                current_company="示例科技",
                city="深圳",
                skills=["西班牙语", "渠道销售"],
                summary="拉美市场销售负责人",
                raw_text="赵先生 墨西哥国家经理 拉美销售 经销商体系",
            )
        )
        await screenings.save_result(first_workflow.id, "job-1", _screening(first.id, score=86, level="observe"))

        duplicate = await candidates.save_snapshot(
            CandidateSnapshotData(
                workflow_id=second_workflow.id,
                platform="liepin",
                display_name="赵先生",
                current_title="墨西哥国家经理",
                current_company="示例科技",
                city="深圳",
                skills=["西班牙语", "大客户销售"],
                summary="拉美市场销售负责人",
                raw_text="赵先生 墨西哥国家经理 拉美销售 经销商体系",
            )
        )
        await screenings.save_result(second_workflow.id, "job-1", _screening(duplicate.id, score=92, level="followup"))
        await session.commit()

        archive_rows = await TalentArchiveRepository(session).search("深圳 西班牙语")
        assert len(archive_rows) == 1
        profile = archive_rows[0]
        assert float(profile.best_score) == 92
        assert profile.last_level == "followup"
        assert set(profile.source_workflow_ids) == {first_workflow.id, second_workflow.id}
        assert "raw_text" not in profile.profile_data
        assert profile.resume_raw_text == "赵先生 墨西哥国家经理 拉美销售 经销商体系"
        assert set(profile.skills) == {"西班牙语", "渠道销售", "大客户销售"}

        raw_text_matches = await TalentArchiveRepository(session).search("经销商体系")
        assert [row.id for row in raw_text_matches] == [profile.id]

        excluded = await candidates.save_snapshot(
            CandidateSnapshotData(
                workflow_id=second_workflow.id,
                platform="liepin",
                display_name="李先生",
                city="深圳",
                raw_text="李先生 不相关经历",
            )
        )
        await screenings.save_result(second_workflow.id, "job-1", _screening(excluded.id, score=20, level="exclude"))
        await session.commit()

        rows = await session.execute(select(TalentArchiveProfile))
        assert len(rows.scalars().all()) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_startup_backfill_archives_existing_non_excluded_candidates(session_factory, monkeypatch):
    from services.agent_service import talent_archive_service

    setup, engine = session_factory
    factory = await setup()
    async with factory() as session:
        workflow = await _create_workflow(session, "历史任务")
        snapshot = await CandidateRepository(session).save_snapshot(
            CandidateSnapshotData(
                workflow_id=workflow.id,
                platform="liepin",
                display_name="王女士",
                city="深圳",
                raw_text="王女士 海外销售 拉美市场",
            )
        )
        await ScreeningRepository(session).save_result(
            workflow.id,
            "job-1",
            _screening(snapshot.id, score=84, level="observe"),
        )
        await session.execute(delete(TalentArchiveProfile))
        await session.commit()

    monkeypatch.setattr(talent_archive_service, "async_session_factory", factory)
    assert await talent_archive_service.backfill_talent_archive() == 1

    async with factory() as session:
        rows = await session.execute(select(TalentArchiveProfile))
        assert len(rows.scalars().all()) == 1

    await engine.dispose()
