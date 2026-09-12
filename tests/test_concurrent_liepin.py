"""Tests for concurrent Liepin workflow browser isolation."""

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.db.session import async_session_factory, init_db
from packages.db.repositories import WorkflowRepository


@pytest.fixture
async def client(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'concurrent_liepin.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


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
async def test_concurrent_liepin_starts_get_distinct_browser_profiles(client, tmp_path, monkeypatch):
    _seed_hr_default_profile(tmp_path, monkeypatch)

    spawned_profiles: list[str] = []

    async def fake_run_fetch_job(workflow_id: str, config) -> None:
        spawned_profiles.append(config.fetch.browser_profile)

    monkeypatch.setattr("apps.api.routes.workflows.run_fetch_job", fake_run_fetch_job)

    body = {
        "platforms": ["liepin"],
        "keywords": "销售",
        "city": "深圳",
        "cities": ["深圳"],
        "experience": "3-5年",
        "target_count": 2,
        "name": "并发测试",
        "search_requirement": "深圳销售",
        "screening_criteria": "本科",
    }

    r1 = await client.post("/workflows/demo/liepin-lpt/start", json={**body, "name": "任务A"})
    r2 = await client.post("/workflows/demo/liepin-lpt/start", json={**body, "name": "任务B"})
    assert r1.status_code == 200
    assert r2.status_code == 200

    wf_a = r1.json()["workflow_id"]
    wf_b = r2.json()["workflow_id"]
    assert wf_a != wf_b

    async with async_session_factory() as session:
        repo = WorkflowRepository(session)
        row_a = await repo.get(wf_a)
        row_b = await repo.get(wf_b)
        profile_a = (row_a.config or {}).get("fetch", {}).get("browser_profile")
        profile_b = (row_b.config or {}).get("fetch", {}).get("browser_profile")

    assert profile_a and profile_b
    assert profile_a != profile_b
    assert profile_a.startswith("wf_")
    assert profile_b.startswith("wf_")
    assert len(spawned_profiles) == 2
    assert spawned_profiles[0] != spawned_profiles[1]


@pytest.mark.asyncio
async def test_list_active_workflows(client, tmp_path, monkeypatch):
    import asyncio

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

    active = await client.get("/workflows/active")
    assert active.status_code == 200
    ids = [item["id"] for item in active.json()]
    assert wf_id in ids
    hold.set()
