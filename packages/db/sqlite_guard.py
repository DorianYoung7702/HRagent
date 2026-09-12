"""SQLite 并发写保护：单进程内串行写 + locked 重试。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_write_lock = asyncio.Lock()
_MAX_ATTEMPTS = 8


def is_sqlite_locked_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "database is busy" in msg


def uses_sqlite() -> bool:
    from packages.settings import get_settings

    return get_settings().database_url.startswith("sqlite")


async def run_sqlite_write(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """SQLite 写操作：进程内互斥 + 遇 locked 指数退避重试。"""
    if not uses_sqlite():
        return await coro_factory()

    last: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        async with _write_lock:
            try:
                return await coro_factory()
            except Exception as exc:
                if not is_sqlite_locked_error(exc):
                    raise
                last = exc
                logger.warning(
                    "SQLite write locked (attempt %d/%d), retrying…",
                    attempt + 1,
                    _MAX_ATTEMPTS,
                )
        await asyncio.sleep(min(0.15 * (2**attempt), 2.0))
    assert last is not None
    raise last
