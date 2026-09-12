"""猎聘 LPT 搜索结果翻页（底部分页器 1 2 3 … ›）。"""

from __future__ import annotations

import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from services.fetch_worker.lpt_adapter import LPT_PAGINATION_NEXT

logger = logging.getLogger(__name__)


async def scroll_search_pagination_into_view(page: Page) -> None:
    """滚到列表底部，使分页器进入视口。"""
    await page.evaluate(
        """() => {
            const pag = document.querySelector(
                '.ant-pagination, [class*="Pagination"], [class*="pagination"]'
            );
            if (pag) {
                pag.scrollIntoView({ block: 'center', behavior: 'instant' });
                return;
            }
            window.scrollTo(0, document.body.scrollHeight);
        }"""
    )
    await page.wait_for_timeout(500)


async def has_lpt_next_search_page(page: Page) -> bool:
    """是否存在可点的「下一页 / ›」。"""
    for sel in LPT_PAGINATION_NEXT:
        try:
            loc = page.locator(sel).first
            if not await loc.is_visible(timeout=800):
                continue
            cls = (await loc.get_attribute("class")) or ""
            disabled = await loc.get_attribute("disabled")
            aria = (await loc.get_attribute("aria-disabled")) or ""
            if disabled is not None or aria == "true":
                continue
            if "disabled" in cls.lower():
                continue
            return True
        except Exception:
            continue

    return bool(
        await page.evaluate(
            """() => {
                const isVisible = el => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 8 && r.height > 8
                        && s.display !== 'none' && s.visibility !== 'hidden';
                };
                const next = document.querySelector(
                    '.ant-pagination-next:not(.ant-pagination-disabled)'
                );
                if (next && isVisible(next)) return true;
                const pag = document.querySelector('.ant-pagination, [class*="pagination"]');
                if (!pag || !isVisible(pag)) return false;
                const active = pag.querySelector(
                    '.ant-pagination-item-active, [class*="item-active"], [aria-current="page"]'
                );
                if (!active) return false;
                const cur = parseInt((active.textContent || '').trim(), 10);
                if (Number.isNaN(cur)) return false;
                for (const el of pag.querySelectorAll(
                    '.ant-pagination-item, li[class*="pagination-item"], button, a'
                )) {
                    if (!isVisible(el)) continue;
                    if ((el.textContent || '').trim() === String(cur + 1)) return true;
                }
                return false;
            }"""
        )
    )


async def click_lpt_next_search_page(page: Page) -> bool:
    """点击分页器「› / 下一页」或下一页页码。"""
    await scroll_search_pagination_into_view(page)

    for sel in LPT_PAGINATION_NEXT:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1200):
                await loc.scroll_into_view_if_needed()
                await loc.click(timeout=5000)
                logger.info("Clicked LPT pagination via %s", sel)
                return True
        except Exception:
            continue

    clicked = await page.evaluate(
        """() => {
            const isVisible = el => {
                const r = el.getBoundingClientRect();
                return r.width > 8 && r.height > 8;
            };
            const next = document.querySelector(
                '.ant-pagination-next:not(.ant-pagination-disabled)'
            );
            if (next && isVisible(next)) {
                next.click();
                return { ok: true, via: 'next-arrow' };
            }
            for (const sel of [
                '[class*="pagination-next"]:not([class*="disabled"])',
                'button[aria-label*="下一页"]',
                'a[aria-label*="下一页"]',
            ]) {
                const el = document.querySelector(sel);
                if (el && isVisible(el)) {
                    el.click();
                    return { ok: true, via: sel };
                }
            }
            const pag = document.querySelector('.ant-pagination, [class*="pagination"]');
            if (!pag) return { ok: false };
            const active = pag.querySelector(
                '.ant-pagination-item-active, [aria-current="page"]'
            );
            const cur = active
                ? parseInt((active.textContent || '').trim(), 10)
                : NaN;
            if (!Number.isNaN(cur)) {
                for (const el of pag.querySelectorAll(
                    '.ant-pagination-item, li, a, button, span'
                )) {
                    if (!isVisible(el)) continue;
                    const t = (el.textContent || '').trim();
                    if (t === String(cur + 1)) {
                        el.click();
                        return { ok: true, via: 'page-number', page: cur + 1 };
                    }
                }
            }
            return { ok: false };
        }"""
    )
    if clicked and clicked.get("ok"):
        logger.info("Clicked LPT pagination via JS: %s", clicked.get("via"))
        return True
    return False


async def try_lpt_next_search_page(page: Page) -> bool:
    """当前页无新卡片时尝试翻页；成功则等待列表刷新。"""
    if not await has_lpt_next_search_page(page):
        await scroll_search_pagination_into_view(page)
        if not await has_lpt_next_search_page(page):
            return False

    if not await click_lpt_next_search_page(page):
        return False

    await page.wait_for_timeout(1200)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        await page.wait_for_timeout(1500)

    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(600)
    return True
