"""BOSS fetch runner extension point.

The real BOSS RPA steps are intentionally isolated here so the shared
workflow/agent shell can fan out platforms before page-specific automation is
implemented.
"""

from packages.schemas.candidate import FetchInput, FetchOutput


async def run_boss_fetch_task(fetch_input: FetchInput, *, fetch_task_id: str) -> FetchOutput:
    from packages.workflow_control import wait_if_paused
    from packages.workflow_events import emit, workflow_context

    with workflow_context(fetch_input.workflow_id):
        await wait_if_paused(fetch_input.workflow_id)
        emit(
            "info",
            "BOSS 任务已进入并行执行队列",
            category="system",
            workflow_id=fetch_input.workflow_id,
            meta={
                "platform": "boss",
                "keywords": fetch_input.search.keywords,
                "city": fetch_input.search.city,
                "cities": fetch_input.search.cities,
                "experience": fetch_input.search.experience,
            },
        )
        emit(
            "warn",
            "BOSS RPA 未接入，等待补充页面自动化步骤",
            category="system",
            workflow_id=fetch_input.workflow_id,
        )

    return FetchOutput(
        fetch_task_id=fetch_task_id,
        workflow_id=fetch_input.workflow_id,
        captured_count=0,
        candidate_snapshot_ids=[],
        failed_items=[{"error": "BOSS RPA 未接入"}],
    )
