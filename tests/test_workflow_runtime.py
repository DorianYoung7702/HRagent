"""Tests for stale workflow reconciliation and live active-task detection."""

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.main import app
from packages.db.models import Base
from packages.db.repositories import WorkflowRepository
from packages.db.session import async_session_factory, init_db
from packages.workflow_runtime import (
    is_workflow_active_for_console,
    is_workflow_execution_live,
    reconcile_stale_workflows_on_startup,
    register_workflow_session,
    unregister_workflow_session,
)


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


@pytest.fixture
async def client(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'workflow_runtime.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_reconcile_stale_workflows_marks_orphans(tmp_path, monkeypatch):
    db_path = tmp_path / "reconcile.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        repo = WorkflowRepository(session)
        wf = await repo.create(
            name="遗留任务",
            platform="liepin",
            start_url="https://lpt.liepin.com/search",
            job_id="job-1",
            config={},
        )
        await repo.update_status(wf.id, "FETCHING")
        await session.commit()
        wf_id = wf.id

    monkeypatch.setattr("packages.workflow_runtime.async_session_factory", factory)

    count = await reconcile_stale_workflows_on_startup()
    assert count == 1

    async with factory() as session:
        repo = WorkflowRepository(session)
        wf = await repo.get(wf_id)
        assert wf is not None
        assert wf.status == "PARTIAL_FAILED"
        assert "服务重启" in (wf.error_message or "")

    await engine.dispose()


@pytest.mark.asyncio
async def test_is_workflow_execution_live_without_tasks():
    assert is_workflow_execution_live("wf-not-running") is False


@pytest.mark.asyncio
async def test_active_console_keeps_registered_im_phase_without_live_tasks():
    wf_id = "wf-im-wait"
    register_workflow_session(wf_id)
    try:
        assert is_workflow_active_for_console(wf_id, "CONVERSATIONS_STARTED") is True
        assert is_workflow_active_for_console(wf_id, "FETCHING") is True
    finally:
        unregister_workflow_session(wf_id)


@pytest.mark.asyncio
async def test_active_console_excludes_unregistered_zombie_conversations_started():
    assert is_workflow_active_for_console("wf-zombie", "CONVERSATIONS_STARTED") is False


@pytest.mark.asyncio
async def test_mark_conversations_started_preserves_fetching_status():
    from services.agent_service.im_autopilot import mark_conversations_started_when_ready

    db_path = Path("test_im_status.db")
    if db_path.exists():
        db_path.unlink()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        repo = WorkflowRepository(session)
        wf = await repo.create(
            name="抓取中",
            platform="liepin",
            start_url="https://lpt.liepin.com/search",
            job_id="job-1",
            config={},
        )
        await repo.update_status(wf.id, "FETCHING")
        await session.commit()
        wf_id = wf.id

    async with factory() as session:
        repo = WorkflowRepository(session)
        await mark_conversations_started_when_ready(
            repo, wf_id, current_status="FETCHING"
        )
        await session.commit()

    async with factory() as session:
        repo = WorkflowRepository(session)
        wf = await repo.get(wf_id)
        assert wf is not None
        assert wf.status == "FETCHING"

    await engine.dispose()
    if db_path.exists():
        db_path.unlink()


@pytest.mark.asyncio
async def test_active_api_excludes_stale_db_rows(client, tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'active_filter.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    await init_db()

    async with async_session_factory() as session:
        repo = WorkflowRepository(session)
        wf = await repo.create(
            name="僵尸任务",
            platform="liepin",
            start_url="https://lpt.liepin.com/search",
            job_id="job-1",
            config={},
        )
        await repo.update_status(wf.id, "FETCHING")
        await session.commit()
        stale_id = wf.id

    active = await client.get("/workflows/active")
    assert active.status_code == 200
    assert stale_id not in [item["id"] for item in active.json()]


@pytest.mark.asyncio
async def test_active_api_includes_fetching_when_live(client, tmp_path, monkeypatch):
    _seed_hr_default_profile(tmp_path, monkeypatch)

    hold = asyncio.Event()

    async def fake_run_fetch_job(workflow_id: str, config) -> None:
        async with async_session_factory() as session:
            repo = WorkflowRepository(session)
            await repo.update_status(workflow_id, "FETCHING")
            await session.commit()
        await hold.wait()

    monkeypatch.setattr("apps.api.routes.workflows.run_fetch_job", fake_run_fetch_job)

    body = {
        "platforms": ["liepin"],
        "keywords": "销售",
        "city": "深圳",
        "cities": ["深圳"],
        "experience": "3-5年",
        "target_count": 1,
        "name": "抓取中任务",
        "search_requirement": "深圳销售",
        "screening_criteria": "本科",
    }
    start = await client.post("/workflows/demo/liepin-lpt/start", json=body)
    assert start.status_code == 200
    wf_id = start.json()["workflow_id"]

    for _ in range(20):
        active = await client.get("/workflows/active")
        ids = [item["id"] for item in active.json()]
        if wf_id in ids:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("expected live FETCHING workflow in /workflows/active")

    hold.set()


@pytest.mark.asyncio
async def test_active_api_includes_live_background_task(client, tmp_path, monkeypatch):
    _seed_hr_default_profile(tmp_path, monkeypatch)

    hold = asyncio.Event()

    async def fake_run_fetch_job(workflow_id: str, config) -> None:
        await hold.wait()

    monkeypatch.setattr("apps.api.routes.workflows.run_fetch_job", fake_run_fetch_job)

    body = {
        "platforms": ["liepin"],
        "keywords": "销售",
        "city": "深圳",
        "cities": ["深圳"],
        "experience": "3-5年",
        "target_count": 1,
        "name": "活跃任务",
        "search_requirement": "深圳销售",
        "screening_criteria": "本科",
    }
    start = await client.post("/workflows/demo/liepin-lpt/start", json=body)
    assert start.status_code == 200
    wf_id = start.json()["workflow_id"]

    for _ in range(20):
        active = await client.get("/workflows/active")
        ids = [item["id"] for item in active.json()]
        if wf_id in ids:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("expected live workflow in /workflows/active")

    hold.set()
