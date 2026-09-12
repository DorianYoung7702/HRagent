from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base
from packages.db.repositories import CandidateRepository, WorkflowRepository
from packages.schemas.candidate import CandidateSnapshotData
from services.fetch_worker.extract_popup import _candidate_fingerprint


def _resume_text(count_a: int, count_b: int, *, company_tail: str = "示例影像") -> str:
    return f"""快速定位：

西班牙语
({count_a})
海外销售
({count_b})
查看大图
赵先生（TA设置了姓名保护）
今天活跃
更新简历时间：2026.05.19
深圳
工作4年
27 岁
在职，急寻新工作
示例外国语大学 · 西班牙语 · 本科 · 统招
示例家电集团 海外销售代表
示例通信公司 客户主管 外派墨西哥
{company_tail} 墨西哥国家经理
"""


def test_candidate_fingerprint_ignores_liepin_quick_locate_counts():
    first = {
        "display_name": "赵先生",
        "current_title": "查看大图",
        "raw_text": _resume_text(2, 1),
    }
    same_resume = {
        "display_name": "赵先生",
        "current_title": "查看大图",
        "raw_text": _resume_text(3, 4),
    }
    same_resume_masked_name = {
        "display_name": "赵**",
        "current_title": "查看大图",
        "raw_text": _resume_text(3, 4),
    }
    different_resume = {
        "display_name": "赵先生",
        "current_title": "查看大图",
        "raw_text": _resume_text(3, 4, company_tail="不同公司"),
    }

    assert _candidate_fingerprint(first) == _candidate_fingerprint(same_resume)
    assert _candidate_fingerprint(first) == _candidate_fingerprint(same_resume_masked_name)
    assert _candidate_fingerprint(first) != _candidate_fingerprint(different_resume)


def test_dedupe_candidate_items_prefers_score_then_latest():
    from apps.api.routes.workflows import _dedupe_candidate_items

    older_better = {
        "id": "old",
        "display_name": "赵先生",
        "education": "本科",
        "city": "深圳",
        "work_years": 4.0,
        "captured_at": "2026-06-12T04:10:34",
        "screening": {"total_score": 92.0, "level": "observe"},
        "metadata": {"card_age": 27, "card_school": "示例外国语大学"},
        "identity_key": "same-person",
    }
    newer_lower = {
        "id": "new",
        "display_name": "赵先生",
        "education": "本科",
        "city": "深圳",
        "work_years": 4.0,
        "captured_at": "2026-06-12T04:24:44",
        "screening": {"total_score": 88.0, "level": "observe"},
        "metadata": {"card_age": 27, "card_school": "示例外国语大学"},
        "identity_key": "same-person",
    }
    unique = {
        "id": "unique",
        "display_name": "杨",
        "education": "本科",
        "city": "深圳",
        "work_years": 3.0,
        "captured_at": "2026-06-12T04:20:00",
        "screening": {"total_score": 80.0, "level": "observe"},
        "metadata": {"card_age": 26, "card_school": "大连外国语大学"},
        "identity_key": "unique-person",
    }

    deduped = _dedupe_candidate_items([newer_lower, older_better, unique])

    assert [item["id"] for item in deduped] == ["old", "unique"]
    assert all("identity_key" not in item for item in deduped)


@pytest.fixture
def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'identity.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


@pytest.mark.asyncio
async def test_save_snapshot_marks_identity_and_duplicate_snapshot(session_factory):
    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        wf = await WorkflowRepository(session).create(
            name="identity",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={"job": {"job_id": "job-1", "description": ""}},
        )
        repo = CandidateRepository(session)
        first = await repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=wf.id,
                platform="liepin",
                display_name="Zhao",
                education="Tianjin Foreign Studies University",
                city="Shenzhen",
                work_years=4,
                raw_text=_resume_text(1, 1),
            )
        )
        duplicate = await repo.save_snapshot(
            CandidateSnapshotData(
                workflow_id=wf.id,
                platform="liepin",
                display_name="Zhao",
                education="Tianjin Foreign Studies University",
                city="Shenzhen",
                work_years=4,
                raw_text=_resume_text(3, 5),
            )
        )

    await engine.dispose()

    assert first.metadata_["candidate_identity_key"]
    assert duplicate.metadata_["candidate_identity_key"] == first.metadata_["candidate_identity_key"]
    assert duplicate.metadata_["duplicate_candidate"] is True
    assert duplicate.metadata_["duplicate_of_snapshot_id"] == first.id
