from __future__ import annotations

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base, RecruitingWorkflow
from packages.schemas.workflow import ConsoleStartRequest


@pytest.fixture
def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'platform_fanout.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


def test_console_start_request_defaults_to_liepin_platform():
    body = ConsoleStartRequest(keywords="西班牙语 海外销售")

    assert body.platforms == ["liepin"]


def test_console_start_request_accepts_liepin_and_boss():
    body = ConsoleStartRequest(
        keywords="西班牙语 海外销售",
        platforms=["liepin", "boss"],
    )

    assert body.platforms == ["liepin", "boss"]


def _seed_hr_default_profile(tmp_path, monkeypatch):
    root = tmp_path / "browser_profiles"
    default = root / "hr_default" / "Default"
    default.mkdir(parents=True)
    (default / "Cookies").write_text("ok", encoding="utf-8")
    (default / "Preferences").write_text("{}", encoding="utf-8")

    from services.fetch_worker import login_init as li
    from services.fetch_worker import workflow_browser_profile as wbp

    def profile_dir_for(name: str):
        return root / name

    def profile_has_cache(name: str = "hr_default") -> bool:
        d = root / name / "Default"
        return d.is_dir() and (d / "Cookies").exists()

    monkeypatch.setattr(li, "profile_dir_for", profile_dir_for)
    monkeypatch.setattr(li, "profile_has_cache", profile_has_cache)
    monkeypatch.setattr(wbp, "profile_dir_for", profile_dir_for)
    monkeypatch.setattr(wbp, "profile_has_cache", profile_has_cache)


@pytest.mark.asyncio
async def test_console_start_fans_out_shared_settings_to_liepin_and_boss(
    session_factory,
    tmp_path,
    monkeypatch,
):
    from apps.api.routes import workflows
    import packages.runtime_guards as guards

    _seed_hr_default_profile(tmp_path, monkeypatch)

    setup, engine = session_factory
    factory = await setup()
    spawned: list[str] = []

    def fake_guard() -> None:
        return None

    async def fake_run_fetch_job(workflow_id: str, config) -> None:
        return None

    def fake_spawn(coro, *, workflow_id: str | None = None):
        if workflow_id:
            spawned.append(workflow_id)
        coro.close()
        return None

    monkeypatch.setattr(guards, "require_task_start", fake_guard)
    monkeypatch.setattr(workflows, "run_fetch_job", fake_run_fetch_job)
    monkeypatch.setattr(workflows, "spawn", fake_spawn)

    async with factory() as session:
        result = await workflows.start_liepin_lpt_demo_async(
            ConsoleStartRequest(
                search_requirement="深圳 西班牙语 海外销售",
                screening_criteria="会西班牙语优先",
                keywords="西班牙语 海外销售",
                city="深圳",
                cities=["深圳"],
                experience="3-5年",
                target_count=6,
                platforms=["liepin", "boss"],
            ),
            BackgroundTasks(),
            session,
        )

        rows = list((await session.execute(select(RecruitingWorkflow))).scalars().all())

    assert result["workflow_id"]
    assert result["status"] == "FETCHING"
    assert [item["platform"] for item in result["platform_results"]] == ["liepin", "boss"]
    assert {item["status"] for item in result["platform_results"]} == {"FETCHING"}
    assert {row.platform for row in rows} == {"liepin", "boss"}
    assert {row.id for row in rows} == set(spawned)
    assert all(row.config["search_intent"]["keywords"] == "西班牙语 海外销售" for row in rows)
    assert all(row.config["platform_group"]["platforms"] == ["liepin", "boss"] for row in rows)

    await engine.dispose()
