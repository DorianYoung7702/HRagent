"""猎聘 LPT 城市筛选：目前城市 / 期望城市 → 其他 → 城市卡片（最多 5 个）。"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from services.fetch_worker.lpt_adapter import (
    LPT_CITY_CONFIRM_BUTTONS,
    LPT_CITY_OTHER_LABELS,
    LPT_CITY_PICKER_TABS,
    LPT_FILTER_CITY_WRONG,
    LPT_FILTER_CURRENT_CITY,
    LPT_FILTER_EXPECT_CITY,
    LPT_MUNICIPALITY_CITIES,
    LPT_KNOWN_CITIES,
    MAX_LPT_CITIES,
)

logger = logging.getLogger(__name__)

_EXPECT_CITY_ROW_Y_TOLERANCE = 48


def _is_current_city_row(row_LABEL: str) -> bool:
    return resolve_city_row_label(row_LABEL) in LPT_FILTER_CURRENT_CITY


def _labels_for_city_row(row_LABEL: str) -> list[str]:
    if _is_current_city_row(row_LABEL):
        return list(LPT_FILTER_CURRENT_CITY)
    return [LPT_FILTER_EXPECT_CITY]


def _pick_anchor_box(boxes: list[dict], *, is_current: bool) -> dict | None:
    if not boxes:
        return None
    if is_current:
        return min(boxes, key=lambda b: b["y"])
    return max(boxes, key=lambda b: b["y"])


def pick_other_on_city_row(
    anchor_y: float,
    anchor_x: float,
    others: list[tuple[float, float, float]],
    *,
    row_tolerance: float = _EXPECT_CITY_ROW_Y_TOLERANCE,
) -> int | None:
    """在指定城市行候选里选最靠右的「其他」。"""
    candidates: list[tuple[float, float, int]] = []
    for i, (y, x, area) in enumerate(others):
        delta_y = abs(y - anchor_y)
        if delta_y >= row_tolerance:
            continue
        if x <= anchor_x + 20:
            continue
        candidates.append((delta_y, x, i))
    if not candidates:
        return None
    nearest_delta = min(delta_y for delta_y, _, _ in candidates)
    same_row_slack = min(10.0, row_tolerance / 4)
    same_row = [
        (x, i)
        for delta_y, x, i in candidates
        if delta_y <= nearest_delta + same_row_slack
    ]
    same_row.sort(key=lambda item: item[0], reverse=True)
    return same_row[0][1]


pick_other_on_expect_city_row = pick_other_on_city_row


def resolve_city_row_label(row_label: str | None = None) -> str:
    text = (row_label or LPT_FILTER_EXPECT_CITY).strip()
    if text in LPT_FILTER_CURRENT_CITY:
        return text
    return LPT_FILTER_EXPECT_CITY


def _avoid_labels_for_row(row_label: str) -> tuple[str, ...]:
    if row_label in LPT_FILTER_CURRENT_CITY:
        return ("目标城市", LPT_FILTER_EXPECT_CITY)
    return LPT_FILTER_CITY_WRONG


def _allow_generic_city_chip_fallback(row_label: str) -> bool:
    return resolve_city_row_label(row_label) not in LPT_FILTER_CURRENT_CITY


def normalize_city_list(city: str | None = None, cities: list[str] | None = None) -> list[str]:
    """合并 city / cities 为去重列表（city 优先），最多 5 个。"""
    out: list[str] = []
    raw: list[str] = []
    if city and city.strip():
        parts = re.split(r"[,，、/|\s]+", city.strip())
        raw.extend(p for p in parts if p)
    if cities:
        raw.extend(c for c in cities if c)
    for name in raw:
        n = name.strip()
        if not n or n in out:
            continue
        if n in LPT_KNOWN_CITIES or len(n) >= 2:
            out.append(n)
        if len(out) >= MAX_LPT_CITIES:
            break
    return out or ["深圳"]


def normalize_city_list_optional(city: str | None = None, cities: list[str] | None = None) -> list[str]:
    """同 normalize_city_list，但空输入返回 []（用于 optional 筛选项）。"""
    if not (city or "").strip() and not cities:
        return []
    return normalize_city_list(city, cities)


def extract_cities_from_text(text: str) -> list[str]:
    """从自然语言中提取已知城市（按出现顺序，最多 5 个）。"""
    found: list[str] = []
    for c in LPT_KNOWN_CITIES:
        if c in (text or "") and c not in found:
            found.append(c)
        if len(found) >= MAX_LPT_CITIES:
            break
    return found


async def _city_picker_scope(page: Page):
    """城市弹层容器（优先 dialog/modal）。"""
    selectors = [
        "[role='dialog']:visible",
        "[class*='city-picker']:visible",
        "[class*='CityPicker']:visible",
        "[class*='city-select']:visible",
        "[class*='citySelect']:visible",
        "[class*='modal']:visible",
        "[class*='drawer']:visible",
        "[class*='popover']:visible",
    ]
    for sel in selectors:
        loc = page.locator(sel).last
        try:
            if await loc.count() > 0 and await loc.is_visible(timeout=500):
                txt = await loc.inner_text()
                if any(k in txt for k in ("热门", "历史", "确定", "北京", "上海", "城市")):
                    return loc
        except Exception:
            continue
    return page.locator("body")


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


async def _filter_bar_scope(page: Page):
    """搜索页顶部筛选栏（与「工作经验」等同排）。"""
    for anchor in ("工作经验", "不限职位", "任意关键词", "搜索人才"):
        try:
            loc = page.get_by_text(anchor, exact=False).first
            if await loc.is_visible(timeout=1500):
                row = loc.locator(
                    "xpath=ancestor::*[contains(@class,'filter') or contains(@class,'search') "
                    "or contains(@class,'condition') or contains(@class,'Screen')][1]"
                )
                if await row.count() > 0:
                    return row
                return loc.locator("xpath=ancestor::div[position()<=5]")
        except Exception:
            continue
    return page.locator("body")


async def _verify_city_row_active(page: Page, want_label: str) -> bool:
    """确认当前展开的不是其它城市行筛选项。"""
    avoid_labels = list(_avoid_labels_for_row(want_label))
    result = await page.evaluate(
        """(args) => {
            const want = args.want;
            const wrongLabels = args.wrong;
            const isVisible = el => {
                const r = el.getBoundingClientRect();
                return r.width > 8 && r.height > 8 && r.top > 0 && r.top < innerHeight * 0.55;
            };
            const isActive = el => {
                const cls = String(el.className || '') + ' ' + String(el.parentElement?.className || '');
                return el.getAttribute('aria-selected') === 'true'
                    || el.getAttribute('aria-checked') === 'true'
                    || /\\b(active|selected|current|checked|on|open)\\b/i.test(cls);
            };
            for (const w of wrongLabels) {
                for (const el of document.querySelectorAll('*')) {
                    if (!isVisible(el)) continue;
                    if ((el.innerText || '').trim() !== w) continue;
                    if (isActive(el)) return { ok: false, active: w };
                }
            }
            return { ok: true };
        }""",
        {"want": want_label, "wrong": avoid_labels},
    )
    if not result.get("ok"):
        logger.warning("Wrong city filter active: %s (need %s)", result.get("active"), want_label)
        return False
    return True


async def _verify_expect_city_active(page: Page) -> bool:
    return await _verify_city_row_active(page, LPT_FILTER_EXPECT_CITY)


async def _click_city_row_via_js(page: Page, row_label: str) -> bool:
    """在筛选栏区域内精确点击指定城市行叶子节点。"""
    avoid_labels = list(_avoid_labels_for_row(row_label))
    result = await page.evaluate(
        """(args) => {
            const want = args.want;
            const wrong = args.wrong;
            const isVisible = el => {
                const r = el.getBoundingClientRect();
                return r.width > 4 && r.height > 4 && r.top >= 40 && r.top < 320;
            };
            let anchor = null;
            for (const el of document.querySelectorAll('*')) {
                if (!isVisible(el)) continue;
                const t = (el.innerText || '').trim();
                if (t === '工作经验' || t.startsWith('工作经验')) {
                    anchor = el;
                    break;
                }
            }
            const inFilterRow = el => {
                if (!anchor) return isVisible(el);
                const r1 = el.getBoundingClientRect();
                const r2 = anchor.getBoundingClientRect();
                return Math.abs(r1.top - r2.top) < 90 && isVisible(el);
            };
            const candidates = [];
            for (const el of document.querySelectorAll('span, label, div, button, li, a, p')) {
                if (!inFilterRow(el)) continue;
                const txt = (el.innerText || '').trim();
                if (txt !== want) continue;
                if (wrong.includes(txt)) continue;
                const area = el.getBoundingClientRect().width * el.getBoundingClientRect().height;
                if (area <= 0 || area > 8000) continue;
                candidates.push({ el, area, left: el.getBoundingClientRect().left });
            }
            if (!candidates.length) return { ok: false };
            candidates.sort((a, b) => a.area - b.area || a.left - b.left);
            candidates[0].el.click();
            return { ok: true, text: (candidates[0].el.innerText || '').trim() };
        }""",
        {"want": row_label, "wrong": avoid_labels},
    )
    if result.get("ok"):
        await page.wait_for_timeout(500)
        logger.info("Clicked %s via JS (text=%s)", row_label, result.get("text"))
        return await _verify_city_row_active(page, row_label)
    return False


async def click_city_filter(page: Page, row_label: str | None = None) -> bool:
    """点击筛选栏指定城市行（目前城市 / 期望城市）。"""
    label = resolve_city_row_label(row_label)
    bar = await _filter_bar_scope(page)

    for role in ("button", "tab", "radio", "option"):
        try:
            loc = bar.get_by_role(role, name=label, exact=True)
            count = await loc.count()
            for i in range(count):
                item = loc.nth(i)
                if not await item.is_visible(timeout=1000):
                    continue
                txt = (await item.inner_text()).strip()
                if txt != label:
                    continue
                await item.click()
                await page.wait_for_timeout(500)
                if await _verify_city_row_active(page, label):
                    logger.info("Clicked %s via role=%s", label, role)
                    return True
        except Exception:
            continue

    try:
        loc = bar.get_by_text(label, exact=True)
        count = await loc.count()
        candidates: list[tuple[float, int]] = []
        for i in range(count):
            item = loc.nth(i)
            if not await item.is_visible(timeout=500):
                continue
            txt = (await item.inner_text()).strip()
            if txt != label:
                continue
            box = await item.bounding_box()
            if not box or box["y"] > 400:
                continue
            candidates.append((box["width"] * box["height"], i))
        candidates.sort(key=lambda x: x[0])
        for _, idx in candidates:
            item = loc.nth(idx)
            await item.click()
            await page.wait_for_timeout(500)
            if await _verify_city_row_active(page, label):
                logger.info("Clicked %s via scoped text", label)
                return True
    except Exception as e:
        logger.warning("Scoped click %s failed: %s", label, e)

    try:
        if await _click_city_row_via_js(page, label):
            return True
    except Exception as e:
        logger.warning("JS click %s failed: %s", label, e)

    logger.warning("Cannot click city row %s", label)
    return False


async def click_expect_city_filter(page: Page) -> bool:
    return await click_city_filter(page, LPT_FILTER_EXPECT_CITY)


async def _open_city_filter(page: Page, row_label: str) -> bool:
    if await click_city_filter(page, row_label):
        return True
    await page.wait_for_timeout(400)
    return await click_city_filter(page, row_label)


async def _anchor_box_for_city_row(page: Page, row_label: str) -> dict | None:
    """定位筛选栏上指定城市行的标签坐标（目前城市取最上行，期望城市取最下行）。"""
    labels = _labels_for_city_row(row_label)
    is_current = _is_current_city_row(row_label)
    boxes: list[dict] = []
    for alias in labels:
        loc = page.get_by_text(alias, exact=True)
        count = await loc.count()
        for i in range(count):
            item = loc.nth(i)
            try:
                if not await item.is_visible(timeout=500):
                    continue
                if (await item.inner_text()).strip() != alias:
                    continue
                box = await item.bounding_box()
                if not box or box["y"] > 420:
                    continue
                boxes.append(box)
            except Exception:
                continue
    return _pick_anchor_box(boxes, is_current=is_current)


async def _click_other_in_city_row(page: Page, row_label: str) -> bool:
    """点指定城市行里的「其他」（按行标签 Y 轴匹配，避免误点另一行）。"""
    label = resolve_city_row_label(row_label)
    anchor_box = await _anchor_box_for_city_row(page, row_label)
    if not anchor_box:
        logger.warning("Cannot locate %s row for 其他", label)
        return False

    other_labels = set(LPT_CITY_OTHER_LABELS)
    loc = page.get_by_text("其他", exact=True)
    n = await loc.count()
    others_meta: list[tuple[float, float, float]] = []
    for i in range(n):
        item = loc.nth(i)
        try:
            if not await item.is_visible(timeout=300):
                continue
            if (await item.inner_text()).strip() not in other_labels:
                continue
            box = await item.bounding_box()
            if not box:
                continue
            others_meta.append((box["y"], box["x"], box["width"] * box["height"]))
        except Exception:
            continue

    pick = pick_other_on_city_row(anchor_box["y"], anchor_box["x"], others_meta)
    if pick is None:
        logger.warning("No 其他 on %s row (found %d total)", label, len(others_meta))
        return await _click_other_in_city_row_js(page, row_label)

    seen = -1
    for i in range(n):
        item = loc.nth(i)
        try:
            if not await item.is_visible(timeout=300):
                continue
            if (await item.inner_text()).strip() not in other_labels:
                continue
            seen += 1
            if seen == pick:
                await item.click()
                await page.wait_for_timeout(500)
                logger.info("Clicked 其他 on %s row", label)
                return True
        except Exception:
            continue
    return await _click_other_in_city_row_js(page, label)


async def _click_other_in_expect_city_row(page: Page) -> bool:
    return await _click_other_in_city_row(page, LPT_FILTER_EXPECT_CITY)


async def _click_other_in_city_row_js(page: Page, row_label: str) -> bool:
    label = resolve_city_row_label(row_label)
    result = await page.evaluate(
        """(args) => {
            const rowLabels = args.rowLabels;
            const isCurrent = args.isCurrent;
            const otherLabels = args.otherLabels;
            const tol = args.tolerance;
            const isVisible = el => {
                const r = el.getBoundingClientRect();
                return r.width > 4 && r.height > 4 && r.top > 0 && r.top < 420;
            };
            const anchors = [];
            for (const want of rowLabels) {
                for (const el of document.querySelectorAll('span, label, div, button, li, a, p')) {
                    if (!isVisible(el)) continue;
                    if ((el.innerText || '').trim() !== want) continue;
                    const r = el.getBoundingClientRect();
                    anchors.push({ el, y: r.top, x: r.left });
                }
            }
            if (!anchors.length) return { ok: false, reason: 'no_anchor' };
            const anchor = isCurrent
                ? anchors.reduce((a, b) => (a.y < b.y ? a : b))
                : anchors.reduce((a, b) => (a.y > b.y ? a : b));
            const expectY = anchor.y;
            const expectX = anchor.x;
            const candidates = [];
            for (const el of document.querySelectorAll('span, label, div, button, li, a, p')) {
                if (!isVisible(el)) continue;
                const txt = (el.innerText || '').trim();
                if (!otherLabels.includes(txt)) continue;
                const r = el.getBoundingClientRect();
                const deltaY = Math.abs(r.top - expectY);
                if (deltaY >= tol) continue;
                if (r.left <= expectX + 20) continue;
                candidates.push({ el, left: r.left, deltaY });
            }
            if (!candidates.length) return { ok: false, reason: 'no_other' };
            const nearestDelta = Math.min(...candidates.map(c => c.deltaY));
            const sameRowSlack = Math.min(10, tol / 4);
            const sameRow = candidates.filter(c => c.deltaY <= nearestDelta + sameRowSlack);
            sameRow.sort((a, b) => b.left - a.left);
            sameRow[0].el.click();
            return { ok: true };
        }""",
        {
            "rowLabels": _labels_for_city_row(row_label),
            "isCurrent": _is_current_city_row(row_label),
            "otherLabels": list(LPT_CITY_OTHER_LABELS),
            "tolerance": _EXPECT_CITY_ROW_Y_TOLERANCE,
        },
    )
    if result.get("ok"):
        await page.wait_for_timeout(500)
        logger.info("Clicked 其他 on %s row via JS", label)
        return True
    logger.warning("JS 其他 on %s row failed: %s", label, result.get("reason"))
    return False


async def _open_other_city_card(page: Page, row_label: str) -> bool:
    label = resolve_city_row_label(row_label)
    if not await _verify_city_row_active(page, label):
        logger.warning("Retry %s before opening 其他", label)
        if not await click_city_filter(page, label):
            return False

    if await _click_other_in_city_row(page, label):
        return True

    logger.warning("Cannot open 其他 on %s row", label)
    return False


async def _activate_hot_tab(page: Page) -> None:
    scope = await _city_picker_scope(page)
    await _click_first_visible(page, LPT_CITY_PICKER_TABS, scope=scope)
    await page.wait_for_timeout(300)


async def _click_city_option(page: Page, city: str) -> bool:
    scope = await _city_picker_scope(page)

    # 右侧城市名（精确优先）
    for exact in (True, False):
        try:
            loc = scope.get_by_text(city, exact=exact).first
            if await loc.is_visible(timeout=2000):
                await loc.click()
                await page.wait_for_timeout(400)
                break
        except Exception:
            continue
    else:
        clicked = await page.evaluate(
            """(city) => {
                const isVisible = el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 8 && r.height > 8 && r.top > 0 && r.top < innerHeight;
                };
                const dialogs = Array.from(document.querySelectorAll(
                    '[role="dialog"], [class*="modal"], [class*="picker"], [class*="Popover"]'
                )).filter(isVisible);
                const root = dialogs.length ? dialogs[dialogs.length - 1] : document.body;
                const nodes = Array.from(root.querySelectorAll('*')).filter(isVisible);
                for (const el of nodes) {
                    const t = (el.innerText || '').trim();
                    if (t === city || (t.startsWith(city) && t.length <= city.length + 2)) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""",
            city,
        )
        if not clicked:
            logger.warning("City picker: cannot click city %s", city)
            return False
        await page.wait_for_timeout(400)

    if city in LPT_MUNICIPALITY_CITIES:
        whole_label = f"全{city}"
        if not await _click_first_visible(page, [whole_label], scope=scope):
            await _click_first_visible(page, [whole_label], scope=page)
        await page.wait_for_timeout(300)

    return True


async def _confirm_city_picker(page: Page) -> bool:
    scope = await _city_picker_scope(page)
    if await _click_first_visible(page, LPT_CITY_CONFIRM_BUTTONS, scope=scope):
        await page.wait_for_timeout(600)
        return True
    if await _click_first_visible(page, LPT_CITY_CONFIRM_BUTTONS, scope=page):
        await page.wait_for_timeout(600)
        return True
    return False


async def select_cities_via_picker(
    page: Page,
    cities: list[str],
    *,
    row_label: str | None = None,
) -> bool:
    """城市行 → 其他 → 历史/热门 → 选城市（直辖市再选全XX）→ 确定。"""
    label = resolve_city_row_label(row_label)
    is_current = label in LPT_FILTER_CURRENT_CITY
    picked = normalize_city_list_optional(cities=cities) if is_current else normalize_city_list(cities=cities)
    if not picked:
        return False

    from packages.workflow_events import emit

    emit(
        "info",
        f"猎聘{label}筛选: {', '.join(picked)}",
        category="search",
        meta={"cities": picked, "row_label": label},
    )
    print(f"[搜索] {label}（卡片多选）: {', '.join(picked)}", flush=True)

    if not await _open_city_filter(page, label):
        logger.warning("Cannot open %s filter", label)
        return False

    if not await _open_other_city_card(page, label):
        logger.warning("Cannot open 其他 city card for %s", label)
        return False

    try:
        await page.wait_for_timeout(800)
        await _activate_hot_tab(page)

        for city in picked:
            ok = await _click_city_option(page, city)
            if not ok:
                logger.warning("Failed to select city in picker: %s", city)
                emit("warn", f"城市选择失败: {city}", category="search")
            else:
                logger.info("Selected city in picker: %s", city)

        if not await _confirm_city_picker(page):
            logger.warning("Cannot confirm city picker")
            return False

        await page.wait_for_timeout(500)
        return True
    except PlaywrightTimeout as e:
        logger.warning("City picker timeout: %s", e)
        return False


async def apply_city_filter_for_row(
    page: Page,
    row_label: str,
    cities: list[str] | None = None,
) -> bool:
    """指定城市行走卡片多选；失败时回退 chip。"""
    label = resolve_city_row_label(row_label)
    picked = normalize_city_list_optional(cities=cities)
    if not picked:
        return False
    if await select_cities_via_picker(page, picked, row_label=label):
        return True

    from services.fetch_worker.lpt_search import _click_filter_option

    if not _allow_generic_city_chip_fallback(label):
        logger.warning("City picker failed for %s; skip generic chip fallback", label)
        return False

    logger.warning("City picker failed for %s, fallback chip for %s", label, picked[0])
    return await _click_filter_option(page, label, picked[0])


async def apply_city_filter(page: Page, city: str | None = None, cities: list[str] | None = None) -> bool:
    """期望城市筛选（兼容旧接口）。"""
    picked = normalize_city_list(city, cities)
    return await apply_city_filter_for_row(page, LPT_FILTER_EXPECT_CITY, picked)
