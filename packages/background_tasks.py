"""Fire-and-forget asyncio tasks that can be cancelled on API shutdown."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()
_workflow_tasks: dict[str, set[asyncio.Task]] = defaultdict(set)


def spawn(coro, *, workflow_id: str | None = None) -> asyncio.Task:
    """Schedule a coroutine; tracked for graceful shutdown on Ctrl+C."""
    task = asyncio.create_task(coro)

    def _done(t: asyncio.Task) -> None:
        _tasks.discard(t)
        if workflow_id:
            _workflow_tasks[workflow_id].discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("Background task failed: %s", exc, exc_info=exc)

    _tasks.add(task)
    if workflow_id:
        _workflow_tasks[workflow_id].add(task)
    task.add_done_callback(_done)
    return task


def has_workflow_tasks(workflow_id: str) -> bool:
    """Return True if any background task is still running for *workflow_id*."""
    tasks = _workflow_tasks.get(workflow_id)
    if not tasks:
        return False
    return any(not task.done() for task in tasks)


def cancel_workflow_tasks(workflow_id: str) -> int:
    """Cancel background tasks registered for a workflow."""
    tasks = list(_workflow_tasks.get(workflow_id, ()))
    cancelled = 0
    for task in tasks:
        if not task.done():
            task.cancel()
            cancelled += 1
    return cancelled


async def shutdown(*, timeout: float = 3.0) -> None:
    if not _tasks:
        return
    logger.info("Cancelling %d background task(s)...", len(_tasks))
    for task in list(_tasks):
        task.cancel()
    _pending = set(_tasks)
    if _pending:
        await asyncio.wait(_pending, timeout=timeout)
    for task in list(_tasks):
        if not task.done():
            logger.warning("Background task still running after shutdown: %s", task.get_name())
    _tasks.clear()
    _workflow_tasks.clear()
