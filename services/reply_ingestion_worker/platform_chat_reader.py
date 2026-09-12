"""Playwright-based platform chat message reader."""

import logging

from packages.db.repositories import CandidateRepository
from packages.db.session import async_session_factory
from services.fetch_worker.browser import BrowserManager
from services.fetch_worker.liepin_adapter import SELECTORS
from services.fetch_worker.page_detector import PageType, detect_page_type

logger = logging.getLogger(__name__)


async def read_latest_reply(candidate_snapshot_id: str) -> dict | None:
    async with async_session_factory() as session:
        repo = CandidateRepository(session)
        snap = await repo.get(candidate_snapshot_id)
        if not snap or not snap.source_url:
            return None

    browser = BrowserManager()
    try:
        page = await browser.new_page()
        await page.goto(snap.source_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        if await detect_page_type(page) == PageType.LOGIN:
            logger.warning("Login required for candidate %s", candidate_snapshot_id)
            return None

        for sel in ["text=立即沟通", "text=消息", "button:has-text('沟通')"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    break
            except Exception:
                continue

        for sel in SELECTORS.chat_message_inbound:
            try:
                messages = page.locator(sel)
                count = await messages.count()
                if count > 0:
                    latest = messages.nth(count - 1)
                    text = await latest.inner_text()
                    if text.strip():
                        return {
                            "candidate_snapshot_id": candidate_snapshot_id,
                            "message_text": text.strip(),
                            "platform_message_id": f"lp_{candidate_snapshot_id}_{count}",
                        }
            except Exception:
                continue

        return None
    finally:
        await browser.close()
