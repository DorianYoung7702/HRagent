"""Shared Playwright helpers for LPT filter rows."""

from __future__ import annotations

import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def _click_first_visible(page: Page, texts: list[str], *, scope=None, exact: bool = False) -> bool:
    root = scope or page
    for text in texts:
        try:
            loc = root.get_by_text(text, exact=exact).first
            if await loc.is_visible(timeout=1500):
                await loc.click()
                await page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    return False


async def filter_row_scope(page: Page, row_anchors: list[str]):
    """Locate a filter row by anchor label(s)."""
    for anchor in row_anchors:
        try:
            loc = page.get_by_text(anchor, exact=False).first
            if await loc.is_visible(timeout=1500):
                row = loc.locator(
                    "xpath=ancestor::*[contains(@class,'filter') or contains(@class,'search') "
                    "or contains(@class,'condition') or contains(@class,'Screen')][1]"
                )
                if await row.count() > 0:
                    return row
                return loc.locator("xpath=ancestor::div[position()<=6]")
        except Exception:
            continue
    return page.locator("body")


async def click_chip_option(
    page: Page,
    option_text: str,
    *,
    row_anchors: list[str] | None = None,
    allow_global_fallback: bool = True,
) -> bool:
    """Click a visible chip/label matching option_text (optionally scoped to a row)."""
    scope = await filter_row_scope(page, row_anchors) if row_anchors else page.locator("body")
    variants = [option_text]
    if "年" in option_text:
        variants.extend([option_text.replace("年", ""), option_text.replace("-", "至")])

    for variant in variants:
        try:
            loc = scope.get_by_text(variant, exact=True)
            count = await loc.count()
            for i in range(count):
                item = loc.nth(i)
                if not await item.is_visible(timeout=800):
                    continue
                if (await item.inner_text()).strip() != variant:
                    continue
                await item.click()
                await page.wait_for_timeout(500)
                logger.info("Selected chip: %s", variant)
                return True
        except Exception:
            continue

    if allow_global_fallback:
        for variant in variants:
            try:
                chip = page.locator(f"text={variant}").first
                if await chip.is_visible(timeout=1200):
                    await chip.click()
                    await page.wait_for_timeout(500)
                    logger.info("Selected chip (global): %s", variant)
                    return True
            except Exception:
                continue
    return False


async def click_filter_label(page: Page, label_texts: list[str], *, row_anchors: list[str] | None = None) -> bool:
    scope = await filter_row_scope(page, row_anchors) if row_anchors else page.locator("body")
    for label in label_texts:
        for exact in (True, False):
            try:
                loc = scope.get_by_text(label, exact=exact).first
                if await loc.is_visible(timeout=1500):
                    await loc.click()
                    await page.wait_for_timeout(400)
                    logger.info("Clicked filter label: %s", label)
                    return True
            except Exception:
                continue
    return False


async def click_dropdown_option(
    page: Page,
    option_text: str,
    *,
    allow_global_chip_fallback: bool = True,
) -> bool:
    """Pick option in the topmost dropdown/popover."""
    variants = [option_text]
    if "年" in option_text:
        variants.extend([option_text.replace("年", ""), option_text.replace("-", "至"), option_text.replace("-", "~")])

    for variant in variants:
        for container_sel in [
            "[role='dialog']:visible",
            "[class*='dropdown']:visible",
            "[class*='popover']:visible",
            "[class*='filter']:visible",
            "body",
        ]:
            try:
                container = page.locator(container_sel).first
                opt = container.get_by_text(variant, exact=False).first
                if await opt.is_visible(timeout=1500):
                    await opt.click()
                    await page.wait_for_timeout(500)
                    logger.info("Selected dropdown option: %s", variant)
                    return True
            except Exception:
                continue
    return await click_chip_option(
        page,
        option_text,
        allow_global_fallback=allow_global_chip_fallback,
    )


async def click_industry_option(page: Page, industry_keyword: str) -> bool:
    """Industry panels: try direct click, then search input fallback."""
    keyword = (industry_keyword or "").strip()
    if not keyword:
        return False
    if await click_dropdown_option(page, keyword):
        return True

    for sel in [
        "input[placeholder*='行业']",
        "input[placeholder*='搜索']",
        "[class*='search'] input[type='text']",
    ]:
        try:
            inp = page.locator(sel).first
            if await inp.is_visible(timeout=1200):
                await inp.fill(keyword)
                await page.wait_for_timeout(500)
                if await click_dropdown_option(page, keyword):
                    return True
                first = page.locator("[class*='option'], [class*='item'], li").filter(has_text=keyword).first
                if await first.is_visible(timeout=1200):
                    await first.click()
                    await page.wait_for_timeout(500)
                    return True
        except Exception:
            continue
    return False


async def confirm_filter_panel(page: Page) -> bool:
    for text in ("确定", "确认", "完成"):
        try:
            btn = page.get_by_role("button", name=text).first
            if await btn.is_visible(timeout=800):
                await btn.click()
                await page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    return False
