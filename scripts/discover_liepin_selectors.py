"""登录后探测 LPT 页面元素，区分「搜索栏」与「职位栏」。"""

import asyncio
import logging
from pathlib import Path

from services.fetch_worker.browser import BrowserManager
from services.fetch_worker.lpt_adapter import LPT_SEARCH_URL
from services.fetch_worker.lpt_search import _mark_search_bar_via_dom

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
OUT = Path("data/debug")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    browser = BrowserManager(profile_name="hr_default")
    try:
        page = await browser.new_page()
        await page.goto(LPT_SEARCH_URL, wait_until="load", timeout=60_000)
        await page.wait_for_timeout(5000)
        await page.screenshot(path=str(OUT / "lpt_search_page.png"), full_page=True)

        print("\n=== Visible inputs (with row context) ===")
        rows = await page.evaluate(
            """() => {
            const isVisible = el => {
                const r = el.getBoundingClientRect();
                return r.width > 20 && r.height > 5;
            };
            return Array.from(document.querySelectorAll('input, textarea'))
                .filter(isVisible)
                .map((el, i) => {
                    const row = el.closest('div, form, li');
                    return {
                        i,
                        placeholder: el.placeholder || '',
                        rowText: (row?.innerText || '').replace(/\\s+/g, ' ').slice(0, 120),
                    };
                });
        }"""
        )
        for row in rows:
            print(f"  input[{row['i']}] placeholder={row['placeholder']!r}")
            print(f"           row={row['rowText']!r}")

        meta = await _mark_search_bar_via_dom(page)
        print("\n=== DOM resolver picked 搜索栏 ===")
        print(meta)

        print(f"\nScreenshot: {OUT / 'lpt_search_page.png'}")
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
