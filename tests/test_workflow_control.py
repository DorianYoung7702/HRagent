"""Tests for workflow pause/resume control."""

import asyncio

import pytest

from packages.workflow_control import (
    WorkflowCancelledError,
    clear_workflow_control,
    get_control_state,
    is_cancelled,
    is_globally_paused,
    is_paused,
    pause_global,
    pause_workflow,
    request_cancel,
    resume_global,
    wait_if_paused,
)


@pytest.mark.asyncio
async def test_pause_resume_flags():
    wf = "wf_pause_test"
    clear_workflow_control(wf)
    resume_global()
    assert not is_paused(wf)

    pause_workflow(wf)
    assert is_paused(wf)
    assert is_globally_paused()
    assert get_control_state(wf)["paused"] is True

    resume_global()
    assert not is_paused(wf)
    assert not is_globally_paused()

    clear_workflow_control(wf)


@pytest.mark.asyncio
async def test_wait_if_paused_unblocks_on_resume():
    wf = "wf_wait_test"
    clear_workflow_control(wf)
    resume_global()
    pause_global(wf)

    async def _resume_later():
        await asyncio.sleep(0.15)
        resume_global()

    task = asyncio.create_task(_resume_later())
    await wait_if_paused(wf)
    await task

    assert not is_paused(wf)
    clear_workflow_control(wf)


@pytest.mark.asyncio
async def test_global_pause_affects_all_workflows():
    wf_a = "wf_global_a"
    wf_b = "wf_global_b"
    clear_workflow_control(wf_a)
    clear_workflow_control(wf_b)
    resume_global()

    pause_global(wf_a)
    assert is_paused(wf_a)
    assert is_paused(wf_b)

    resume_global()
    assert not is_paused(wf_a)
    assert not is_paused(wf_b)

    clear_workflow_control(wf_a)
    clear_workflow_control(wf_b)


@pytest.mark.asyncio
async def test_cancel_raises_in_wait_if_paused():
    wf = "wf_cancel_test"
    clear_workflow_control(wf)
    resume_global()
    request_cancel(wf)

    assert is_cancelled(wf)
    assert get_control_state(wf)["cancelled"] is True

    with pytest.raises(WorkflowCancelledError):
        await wait_if_paused(wf)

    clear_workflow_control(wf)
    resume_global()
