"""Playwright-based platform message draft/fill/send."""

from packages.db.repositories import CandidateRepository
from packages.db.session import async_session_factory
from services.fetch_worker.browser import BrowserManager
from services.fetch_worker.liepin_adapter import SELECTORS
from services.fetch_worker.page_detector import PageType, detect_page_type


async def send_platform_message(
    candidate_snapshot_id: str,
    message_text: str,
    send_mode: str = "draft_first",
) -> dict:
    async with async_session_factory() as session:
        repo = CandidateRepository(session)
        snap = await repo.get(candidate_snapshot_id)
        if not snap:
            raise ValueError(f"Candidate snapshot not found: {candidate_snapshot_id}")

    if not snap.source_url:
        raise ValueError("Candidate has no source_url for messaging")

    browser = BrowserManager()
    try:
        page = await browser.new_page()
        await page.goto(snap.source_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        page_type = await detect_page_type(page)
        if page_type == PageType.LOGIN:
            raise RuntimeError("需要登录猎聘账号")

        chat_opened = False
        for sel in ["text=立即沟通", "text=打招呼", "button:has-text('沟通')", "[class*='chat-btn']"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=3000):
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    chat_opened = True
                    break
            except Exception:
                continue

        if not chat_opened:
            raise RuntimeError("无法打开聊天窗口")

        input_filled = False
        for sel in SELECTORS.chat_input:
            try:
                inp = page.locator(sel).first
                if await inp.is_visible(timeout=3000):
                    await inp.fill(message_text)
                    input_filled = True
                    break
            except Exception:
                continue

        if not input_filled:
            raise RuntimeError("无法找到聊天输入框")

        sent = False
        if send_mode == "auto_send":
            for sel in SELECTORS.chat_send:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        sent = True
                        break
                except Exception:
                    continue

        return {
            "status": "sent" if sent else "drafted",
            "send_mode": send_mode,
            "candidate_snapshot_id": candidate_snapshot_id,
        }
    finally:
        await browser.close()
