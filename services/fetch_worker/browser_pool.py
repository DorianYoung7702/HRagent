"""按 profile 共享 Chromium 持久化上下文，多标签页并行（抓取 + IM）。"""

from __future__ import annotations

import asyncio

from services.fetch_worker.browser import BrowserManager

_pool: dict[str, tuple[BrowserManager, int]] = {}
_lock = asyncio.Lock()


async def acquire_browser(profile_name: str = "hr_default") -> BrowserManager:
    """获取共享浏览器；引用计数 +1。同一 profile 仅启动一个 Chromium 进程。"""
    async with _lock:
        if profile_name in _pool:
            mgr, refs = _pool[profile_name]
            _pool[profile_name] = (mgr, refs + 1)
            return mgr
        mgr = BrowserManager(profile_name=profile_name)
        await mgr.start()
        _pool[profile_name] = (mgr, 1)
        return mgr


async def release_browser(profile_name: str = "hr_default") -> None:
    """释放引用；计数归零时关闭 Chromium。"""
    async with _lock:
        entry = _pool.get(profile_name)
        if not entry:
            return
        mgr, refs = entry
        refs -= 1
        if refs <= 0:
            await mgr.close()
            _pool.pop(profile_name, None)
        else:
            _pool[profile_name] = (mgr, refs)


async def new_page(profile_name: str = "hr_default"):
    """在共享上下文中新建标签页（与抓取页互不干扰）。"""
    mgr = await acquire_browser(profile_name)
    return await mgr.new_page()
