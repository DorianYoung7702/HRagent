"""Workflow execution pause / resume / cancel (in-memory, global + per workflow_id)."""

from __future__ import annotations

import asyncio
import threading

_lock = threading.Lock()
_global_paused = False
_paused: dict[str, bool] = {}
_pause_announced: set[str] = set()
_cancelled: set[str] = set()


class WorkflowCancelledError(Exception):
    """Raised when user cancels a running workflow."""


def pause_global(workflow_id: str | None = None) -> None:
    with _lock:
        global _global_paused
        _global_paused = True
        if workflow_id:
            _paused[workflow_id] = True


def resume_global() -> None:
    with _lock:
        global _global_paused
        _global_paused = False
        for wf_id in list(_paused.keys()):
            _paused[wf_id] = False
        _pause_announced.clear()


def is_globally_paused() -> bool:
    with _lock:
        return _global_paused


def pause_workflow(workflow_id: str) -> None:
    pause_global(workflow_id)


def resume_workflow(workflow_id: str) -> None:
    with _lock:
        _paused[workflow_id] = False
        if not _global_paused:
            _pause_announced.discard(workflow_id)


def is_paused(workflow_id: str) -> bool:
    with _lock:
        if _global_paused:
            return True
        return _paused.get(workflow_id, False)


def get_control_state(workflow_id: str) -> dict[str, bool]:
    with _lock:
        paused = _global_paused or _paused.get(workflow_id, False)
        return {
            "paused": paused,
            "global_paused": _global_paused,
            "cancelled": workflow_id in _cancelled,
        }


def request_cancel(workflow_id: str) -> None:
    """Mark workflow cancelled; running loops exit at next checkpoint."""
    with _lock:
        _cancelled.add(workflow_id)
        _paused[workflow_id] = True
        global _global_paused
        _global_paused = True


def is_cancelled(workflow_id: str) -> bool:
    with _lock:
        return workflow_id in _cancelled


def clear_workflow_control(workflow_id: str) -> None:
    with _lock:
        _paused.pop(workflow_id, None)
        _pause_announced.discard(workflow_id)
        _cancelled.discard(workflow_id)


def _raise_if_cancelled(workflow_id: str) -> None:
    if workflow_id and is_cancelled(workflow_id):
        raise WorkflowCancelledError(f"Workflow {workflow_id} cancelled by user")


async def wait_if_paused(workflow_id: str) -> None:
    """Cooperative pause: block between cards/steps until resumed (global or per-workflow)."""
    _raise_if_cancelled(workflow_id)
    if not workflow_id or not is_paused(workflow_id):
        return

    from packages.workflow_events import emit

    announce = False
    with _lock:
        key = workflow_id if not _global_paused else "__global__"
        if key not in _pause_announced:
            _pause_announced.add(key)
            announce = True

    if announce:
        msg = "全局已暂停，等待继续…" if is_globally_paused() else "任务已暂停，等待继续…"
        emit("warn", msg, category="control", workflow_id=workflow_id)

    while is_paused(workflow_id):
        _raise_if_cancelled(workflow_id)
        await asyncio.sleep(0.4)

    _raise_if_cancelled(workflow_id)
    emit("info", "任务已继续执行", category="control", workflow_id=workflow_id)
    with _lock:
        _pause_announced.discard(workflow_id)
        _pause_announced.discard("__global__")
