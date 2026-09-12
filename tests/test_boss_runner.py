from __future__ import annotations

import pytest

from packages.schemas.candidate import FetchInput
from packages.schemas.workflow import LiepinSearchConfig


@pytest.mark.asyncio
async def test_boss_fetch_runner_reports_rpa_extension_point():
    from services.fetch_worker.boss_runner import run_boss_fetch_task

    result = await run_boss_fetch_task(
        FetchInput(
            platform="boss",
            workflow_id="wf_boss",
            start_url="https://www.zhipin.com/web/geek/job",
            search=LiepinSearchConfig(mode="boss_search", keywords="西班牙语 海外销售"),
        ),
        fetch_task_id="fetch_boss",
    )

    assert result.fetch_task_id == "fetch_boss"
    assert result.workflow_id == "wf_boss"
    assert result.captured_count == 0
    assert result.failed_items == [{"error": "BOSS RPA 未接入"}]
