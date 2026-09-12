"""猎聘 LPT 登录初始化：本机可见浏览器登录并持久化 profile。"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock

from packages.asyncio_compat import run_on_playwright_loop
from packages.settings import get_settings
from services.fetch_worker.browser import BrowserManager
from services.fetch_worker.lpt_adapter import LPT_SEARCH_URL
from services.fetch_worker.page_detector import PageType, detect_page_type

_state_lock = Lock()


class LoginInitStatus(str, Enum):
    IDLE = "idle"
    WAITING = "waiting"
    VERIFYING = "verifying"
    READY = "ready"
    ERROR = "error"


@dataclass
class _Session:
    status: LoginInitStatus = LoginInitStatus.IDLE
    profile_name: str = "hr_default"
    message: str = ""
    error: str = ""
    logged_in: bool | None = None
    verify_result: dict | None = None


_session = _Session()
_browser: BrowserManager | None = None
_page = None


def profile_dir_for(profile_name: str) -> Path:
    settings = get_settings()
    return Path(settings.browser_profile_dir).parent / profile_name


def profile_has_cache(profile_name: str = "hr_default") -> bool:
    root = profile_dir_for(profile_name)
    default = root / "Default"
    if not default.is_dir():
        return False
    markers = ("Cookies", "Local Storage", "Preferences", "Network")
    return any((default / name).exists() for name in markers)


def clear_login_profile(profile_name: str = "hr_default") -> str:
    """删除浏览器 profile 缓存（含 Cookies），用于重新登录。"""
    root = profile_dir_for(profile_name)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    return str(root.resolve())


async def _verify_liepin_login_impl(profile_name: str = "hr_default") -> dict:
    browser = BrowserManager(profile_name=profile_name)
    try:
        page = await browser.new_page()
        await page.goto(LPT_SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)
        page_type = await detect_page_type(page)
        logged_in = page_type != PageType.LOGIN
        return {
            "logged_in": logged_in,
            "page_type": page_type.value,
            "url": page.url,
        }
    finally:
        await browser.close()


async def verify_liepin_login(profile_name: str = "hr_default") -> dict:
    return await run_on_playwright_loop(_verify_liepin_login_impl(profile_name))


def _apply_verify_result(check: dict) -> None:
    _session.verify_result = check
    _session.logged_in = check.get("logged_in")
    page_type = check.get("page_type", "unknown")
    if check.get("logged_in"):
        _session.status = LoginInitStatus.READY
        _session.error = ""
        _session.message = f"检测通过：已登录猎聘 LPT（页面类型：{page_type}）"
    else:
        _session.status = LoginInitStatus.ERROR
        _session.error = "未登录或登录已过期"
        _session.message = f"检测未通过：当前页面类型为「{page_type}」，请清除登录信息后重新登录"


def _public_status() -> dict:
    s = _session
    profile_name = s.profile_name
    cached = profile_has_cache(profile_name)
    can_start = bool(s.logged_in) if s.logged_in is not None else cached
    return {
        "status": s.status.value,
        "profile_name": profile_name,
        "profile_path": str(profile_dir_for(profile_name).resolve()),
        "profile_cached": cached,
        "logged_in": s.logged_in,
        "can_start_task": can_start and s.status != LoginInitStatus.WAITING,
        "message": s.message,
        "error": s.error,
        "verify_result": s.verify_result,
        "hint": (
            "登录缓存保存在运行本系统的电脑上。需要换账号或登录过期时，"
            "点击「清除并重新登录」，在弹出的浏览器窗口完成猎聘登录即可。"
        ),
    }


async def get_login_init_status(profile_name: str = "hr_default") -> dict:
    with _state_lock:
        if _session.profile_name != profile_name and _session.status == LoginInitStatus.IDLE:
            _session.profile_name = profile_name
            if _session.logged_in is None and profile_has_cache(profile_name):
                _session.message = "检测到已有浏览器缓存，可点击「检测登录态」确认"
        return _public_status()


async def _close_browser_impl() -> None:
    global _browser, _page
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
    _browser = None
    _page = None


async def _start_browser_impl(profile_name: str) -> None:
    global _browser, _page
    await _close_browser_impl()
    os.environ["BROWSER_HEADLESS"] = "false"
    browser = BrowserManager(profile_name=profile_name)
    page = await browser.new_page()
    await page.goto(LPT_SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
    _browser = browser
    _page = page


async def start_login_init(profile_name: str = "hr_default") -> dict:
    with _state_lock:
        if _session.status == LoginInitStatus.WAITING:
            return _public_status()
        _session.profile_name = profile_name
        _session.status = LoginInitStatus.WAITING
        _session.error = ""
        _session.message = (
            "已在服务器打开猎聘登录页，请在弹出的浏览器窗口完成登录，"
            "完成后回到控制台点击「我已完成登录」"
        )
        _session.logged_in = None

    try:
        await run_on_playwright_loop(_start_browser_impl(profile_name))
        return await get_login_init_status(profile_name)
    except Exception as e:
        with _state_lock:
            _session.status = LoginInitStatus.ERROR
            _session.error = str(e)
            _session.message = "打开浏览器失败（请确认已安装 Playwright Chromium）"
        await run_on_playwright_loop(_close_browser_impl())
        return _public_status()


async def clear_and_relogin(profile_name: str = "hr_default") -> dict:
    """清除本地登录缓存并打开猎聘登录页。"""
    try:
        await run_on_playwright_loop(_close_browser_impl())
    except Exception:
        pass
    cleared_path = clear_login_profile(profile_name)
    with _state_lock:
        _session.logged_in = None
        _session.verify_result = None
        _session.error = ""
    await start_login_init(profile_name)
    with _state_lock:
        if _session.status == LoginInitStatus.WAITING:
            _session.message = (
                f"已清除登录缓存（{cleared_path}），并打开猎聘登录页。"
                "请在服务器弹出的浏览器窗口完成登录，然后点击「我已完成登录」"
            )
    return _public_status()


async def _complete_login_impl() -> dict:
    global _browser, _page
    if _browser is None or _page is None:
        raise ValueError("登录会话已关闭")
    page = _page
    browser = _browser
    page_type = await detect_page_type(page)
    if page_type == PageType.LOGIN:
        return {"ok": False, "reason": "still_login_page"}
    await browser.close()
    _browser = None
    _page = None
    return {"ok": True}


async def complete_login_init() -> dict:
    with _state_lock:
        if _session.status != LoginInitStatus.WAITING or _page is None:
            raise ValueError("当前没有进行中的登录，请先点击「清除并重新登录」")
        _session.status = LoginInitStatus.VERIFYING
        _session.message = "正在验证登录态…"

    try:
        result = await run_on_playwright_loop(_complete_login_impl())
        if not result.get("ok"):
            with _state_lock:
                _session.status = LoginInitStatus.WAITING
                _session.logged_in = False
                _session.error = "仍未检测到登录成功"
                _session.message = "请在弹出的浏览器窗口完成猎聘登录后重试"
            return _public_status()

        check = await verify_liepin_login(_session.profile_name)
        with _state_lock:
            _apply_verify_result(check)
            if check["logged_in"]:
                _session.message = (
                    "登录态已保存，可以启动筛选任务。"
                    f"（页面类型：{check['page_type']}）"
                )
        return _public_status()
    except Exception as e:
        with _state_lock:
            _session.status = LoginInitStatus.ERROR
            _session.error = str(e)
            _session.message = "保存登录态失败"
        return _public_status()


async def cancel_login_init() -> dict:
    try:
        await run_on_playwright_loop(_close_browser_impl())
    except Exception:
        pass
    with _state_lock:
        if _session.status == LoginInitStatus.WAITING:
            _session.status = LoginInitStatus.IDLE
            _session.message = "已取消登录"
            _session.error = ""
        return _public_status()


async def refresh_login_verify(profile_name: str = "hr_default") -> dict:
    with _state_lock:
        if _session.status == LoginInitStatus.WAITING:
            raise ValueError("登录进行中，请先完成或取消")
        _session.profile_name = profile_name
        _session.status = LoginInitStatus.VERIFYING
        _session.message = "正在检测登录态…"

    try:
        check = await verify_liepin_login(profile_name)
        with _state_lock:
            _apply_verify_result(check)
        return _public_status()
    except Exception as e:
        with _state_lock:
            _session.status = LoginInitStatus.ERROR
            _session.error = str(e)
            _session.message = "检测失败，请确认 Playwright 浏览器已安装"
        return _public_status()
