from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base, RecruitingWorkflow
from packages.db.repositories import WorkflowRepository
from packages.schemas.workflow import (
    ConsoleStartRequest,
    HRPreferenceChatRequest,
    HRPreferenceMemory,
    HRPreferenceUpdateRequest,
)


@pytest.fixture
def session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'hr_preference.db').as_posix()}"
    engine = create_async_engine(db_url, connect_args={"timeout": 30})

    async def _setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return _setup, engine


@pytest.mark.asyncio
async def test_preference_chat_merges_current_requirement_before_preset_memory(monkeypatch):
    from services.agent_service import hr_preference_agent

    async def fake_agent(payload: HRPreferenceChatRequest):
        assert payload.current_requirement == "Need Mexico sales."
        assert payload.preset_memory.preference_summary == "Old java hiring preference."
        return HRPreferenceMemory(
            must_have=["Mexico sales", "US visa"],
            nice_to_have=["channel management"],
            reject_rules=["No overseas sales"],
            followup_questions=["Confirm valid US visa"],
            preference_summary="Prioritize Mexico sales and US visa.",
            screening_criteria="MUST: Mexico sales\nMUST: US visa",
            assistant_message="Preference updated.",
            ready=True,
            criteria_version=3,
        )

    monkeypatch.setattr(hr_preference_agent, "_run_preference_agent", fake_agent)

    output = await hr_preference_agent.update_preference_memory(
        HRPreferenceChatRequest(
            current_requirement="Need Mexico sales.",
            screening_criteria="Need Spanish.",
            preset_memory=HRPreferenceMemory(
                preference_summary="Old java hiring preference.",
                screening_criteria="Old criteria",
            ),
            messages=[{"role": "user", "content": "Must have US visa."}],
        )
    )

    assert output.must_have == ["Mexico sales", "US visa", "No overseas sales"]
    assert output.reject_rules == []
    assert "## 必备" in output.screening_criteria
    assert "US visa" in output.screening_criteria
    assert output.ready is True


@pytest.mark.asyncio
async def test_preference_memory_replaces_duplicate_topics_and_removes_mirrored_rejects(monkeypatch):
    from services.agent_service import hr_preference_agent

    async def fake_agent(payload: HRPreferenceChatRequest):
        return HRPreferenceMemory(
            must_have=[
                "至少8年以上薪资绩效同岗位工作经验",
                "具备薪资绩效方案的设计、优化或落地实施能力",
                "通过大学英语四级（CET-4），或提供同等水平的英语能力证明",
                "base深圳（目前所在地为深圳，或明确表示愿意来深圳工作）",
            ],
            nice_to_have=[
                "毕业于985、211院校",
                "毕业于985或211院校",
                "有科技、互联网、智能硬件行业工作经验",
            ],
            reject_rules=[
                "薪资绩效同岗位经验不足8年",
                "无任何英语四级或同等英语能力证明",
                "明确不在深圳且拒绝来深圳发展",
            ],
            followup_questions=[
                "薪资绩效方案设计能力具体体现在哪些项目或成果上？",
                "若简历中薪资绩效方案设计能力描述不清晰，需追问具体项目细节和成果",
            ],
            preference_summary="更新后的薪资绩效岗位偏好",
            screening_criteria="",
            assistant_message="已更新",
            ready=True,
            criteria_version=1,
        )

    monkeypatch.setattr(hr_preference_agent, "_run_preference_agent", fake_agent)

    output = await hr_preference_agent.update_preference_memory(
        HRPreferenceChatRequest(
            current_requirement="薪资绩效经理，base深圳",
            screening_criteria="",
            preset_memory=HRPreferenceMemory(
                must_have=[
                    "至少8年以上薪资绩效同岗位工作经验（需要明确的项目经历与成果，不接受仅列举职责）",
                    "通过大学英语四级（CET-4）",
                    "base深圳",
                ],
                nice_to_have=["毕业于985、211院校"],
                reject_rules=["未通过大学英语四级", "base地不在深圳且无意愿来深圳"],
                followup_questions=["薪资绩效方案设计能力具体体现在哪些项目或成果上？"],
            ),
            messages=[
                {
                    "role": "user",
                    "content": "英语四级可以接受同等证明，薪资绩效经验必须两个模块都做过。",
                }
            ],
        )
    )

    assert output.must_have == [
        "至少8年以上薪资绩效同岗位工作经验（需要明确的项目经历与成果，不接受仅列举职责）",
        "具备薪资绩效方案的设计、优化或落地实施能力",
        "通过大学英语四级（CET-4），或提供同等水平的英语能力证明",
        "base深圳（目前所在地为深圳，或明确表示愿意来深圳工作）",
    ]
    assert output.nice_to_have == [
        "毕业于985或211院校",
        "有科技、互联网、智能硬件行业工作经验",
    ]
    assert output.reject_rules == []
    assert any("英语" in item for item in output.must_have)
    assert any("深圳" in item for item in output.must_have)


@pytest.mark.asyncio
async def test_preference_memory_preserves_quick_reject_rules(monkeypatch):
    from services.agent_service import hr_preference_agent

    async def fake_agent(payload: HRPreferenceChatRequest):
        return HRPreferenceMemory(
            must_have=["8 年以上薪资绩效同岗位经验"],
            quick_reject_rules=["近一年内有两次及以上主动跳槽"],
            assistant_message="已补充快速淘汰偏好。",
            ready=True,
        )

    monkeypatch.setattr(hr_preference_agent, "_run_preference_agent", fake_agent)

    output = await hr_preference_agent.update_preference_memory(
        HRPreferenceChatRequest(
            current_requirement="薪资绩效经理",
            screening_criteria="",
            preset_memory=HRPreferenceMemory(
                quick_reject_rules=["明确拒绝来深圳工作"],
            ),
            messages=[{"role": "user", "content": "近一年两次主动跳槽可快速淘汰"}],
        )
    )

    assert output.quick_reject_rules == ["近一年内有两次及以上主动跳槽", "明确拒绝来深圳工作"]
    assert "## 快速淘汰" in output.screening_criteria
    assert "近一年内有两次及以上主动跳槽" in output.screening_criteria


@pytest.mark.asyncio
async def test_console_start_persists_hr_preference_memory_to_each_platform(
    session_factory,
    monkeypatch,
):
    from apps.api.routes import workflows
    import packages.runtime_guards as guards
    from services.fetch_worker import workflow_browser_profile

    setup, engine = session_factory
    factory = await setup()
    spawned: list[str] = []

    monkeypatch.setattr(guards, "require_task_start", lambda: None)
    monkeypatch.setattr(
        workflow_browser_profile,
        "ensure_workflow_browser_profile",
        workflow_browser_profile.workflow_browser_profile_name,
    )

    async def fake_run_fetch_job(workflow_id: str, config) -> None:
        return None

    def fake_spawn(coro, *, workflow_id: str | None = None):
        if workflow_id:
            spawned.append(workflow_id)
        coro.close()
        return None

    monkeypatch.setattr(workflows, "run_fetch_job", fake_run_fetch_job)
    monkeypatch.setattr(workflows, "spawn", fake_spawn)

    memory = HRPreferenceMemory(
        must_have=["US visa"],
        screening_criteria="MUST: US visa",
        preference_summary="US visa is required.",
        criteria_version=2,
    )

    async with factory() as session:
        result = await workflows.start_liepin_lpt_demo_async(
            ConsoleStartRequest(
                platforms=["liepin", "boss"],
                search_requirement="Latam sales Shenzhen",
                screening_criteria="MUST: US visa",
                keywords="Latam sales",
                city="Shenzhen",
                cities=["Shenzhen"],
                experience="3-5 years",
                target_count=3,
                preset_id="preset-1",
                preset_label="Latam sales",
                hr_preference_memory=memory,
            ),
            None,
            session,
        )
        rows = list((await session.execute(select(RecruitingWorkflow))).scalars().all())

    await engine.dispose()

    assert result["workflow_id"]
    assert len(spawned) == 2
    assert {row.platform for row in rows} == {"liepin", "boss"}
    assert all(row.config["hr_preference_memory"]["must_have"] == ["US visa"] for row in rows)
    assert all(row.config["criteria_version"] == 2 for row in rows)
    assert all(row.config["job"]["screening_criteria"] == "MUST: US visa" for row in rows)
    assert all(row.config["initial_screening_criteria"] == "MUST: US visa" for row in rows)
    assert all(row.config["initial_criteria_version"] == 2 for row in rows)


@pytest.mark.asyncio
async def test_update_preference_memory_is_rejected_after_task_start(session_factory):
    from apps.api.routes import workflows

    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        repo = WorkflowRepository(session)
        group = {"id": "group-1", "platforms": ["liepin", "boss"], "primary_platform": "liepin"}
        liepin = await repo.create(
            name="liepin",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={
                "job": {"job_id": "job-1", "description": "old", "screening_criteria": "old"},
                "search_intent": {"screening_criteria": "old"},
                "requirement_preset": {"id": "preset-1", "screening_criteria": "old"},
                "platform_group": group,
                "criteria_version": 1,
            },
        )
        await repo.create(
            name="boss",
            platform="boss",
            start_url="https://example.com",
            job_id="job-1",
            config={
                "job": {"job_id": "job-1", "description": "old", "screening_criteria": "old"},
                "search_intent": {"screening_criteria": "old"},
                "requirement_preset": {"id": "preset-1", "screening_criteria": "old"},
                "platform_group": group,
                "criteria_version": 1,
            },
        )
        await session.commit()

        with pytest.raises(HTTPException) as exc:
            await workflows.update_workflow_preference_memory(
                liepin.id,
                HRPreferenceUpdateRequest(
                    memory=HRPreferenceMemory(
                        must_have=["US visa"],
                        screening_criteria="new criteria",
                        criteria_version=1,
                    )
                ),
                session,
            )
        rows = list((await session.execute(select(RecruitingWorkflow))).scalars().all())

    await engine.dispose()

    assert exc.value.status_code == 409
    assert all(row.config["job"]["screening_criteria"] == "old" for row in rows)


@pytest.mark.asyncio
async def test_rescreen_existing_is_rejected_after_task_start(session_factory):
    from apps.api.routes import workflows

    setup, engine = session_factory
    factory = await setup()

    async with factory() as session:
        repo = WorkflowRepository(session)
        wf = await repo.create(
            name="rescreen",
            platform="liepin",
            start_url="https://example.com",
            job_id="job-1",
            config={
                "job": {
                    "job_id": "job-1",
                    "description": "Need US visa",
                    "screening_criteria": "MUST: US visa",
                },
                "screening": {"top_k": 10, "min_score": 60},
                "fetch": {"search": {}},
                "outreach": {},
                "criteria_version": 2,
            },
        )
        await session.commit()

        with pytest.raises(HTTPException) as exc:
            await workflows.rescreen_existing_with_preference(wf.id, session)

    await engine.dispose()

    assert exc.value.status_code == 409


def test_initial_criteria_snapshot_overrides_mutable_workflow_config():
    from services.agent_service.screening_service import _criteria_context_from_config

    criteria, version = _criteria_context_from_config(
        {
            "initial_screening_criteria": "initial criteria",
            "initial_criteria_version": 1,
            "job": {"screening_criteria": "mutated criteria"},
            "criteria_version": 2,
        }
    )

    assert criteria == "initial criteria"
    assert version == 1
