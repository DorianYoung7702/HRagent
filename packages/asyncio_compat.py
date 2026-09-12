"""Asyncio helpers for Windows + uvicorn + Playwright."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

_playwright_loop: asyncio.AbstractEventLoop | None = None
_playwright_thread: threading.Thread | None = None
_playwright_ready = threading.Event()


def _ensure_playwright_loop() -> asyncio.AbstractEventLoop:
    global _playwright_loop, _playwright_thread
    if _playwright_loop is not None:
        return _playwright_loop

    def _run() -> None:
        global _playwright_loop
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _playwright_loop = loop
        _playwright_ready.set()
        loop.run_forever()

    _playwright_thread = threading.Thread(target=_run, name="playwright-loop", daemon=True)
    _playwright_thread.start()
    _playwright_ready.wait()
    assert _playwright_loop is not None
    return _playwright_loop


async def run_on_playwright_loop(coro: Awaitable[T]) -> T:
    """Run coroutine on a persistent Proactor loop (Windows uvicorn + Playwright)."""
    if sys.platform != "win32":
        return await coro
    loop = _ensure_playwright_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return await asyncio.wrap_future(future)


def shutdown_playwright_loop(*, timeout: float = 3.0) -> None:
    """Stop the persistent Playwright event loop (Windows uvicorn)."""
    global _playwright_loop, _playwright_thread
    loop = _playwright_loop
    thread = _playwright_thread
    if loop is None:
        return
    try:
        loop.call_soon_threadsafe(loop.stop)
    except RuntimeError:
        pass
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
    _playwright_loop = None
    _playwright_thread = None
    _playwright_ready.clear()


async def run_blocking_async(
    fn: Callable[..., Awaitable[T]],
    /,
    *args,
    **kwargs,
) -> T:
    """Run async code that needs subprocess support under uvicorn on Windows.

    With ``--reload``, uvicorn uses SelectorEventLoop on Windows, which cannot
    spawn Playwright's browser process. A worker thread with ``asyncio.run()``
    gets the default Proactor loop instead.
    """
    if sys.platform != "win32":
        return await fn(*args, **kwargs)

    def _worker() -> T:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        return asyncio.run(fn(*args, **kwargs))

    return await asyncio.to_thread(_worker)
