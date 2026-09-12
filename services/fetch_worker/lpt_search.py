"""猎聘 LPT 企业版搜索页自动化。"""

import logging
from pathlib import Path

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeout

from services.fetch_worker.experience_fallback import (
    EXPERIENCE_LADDER,
    resolve_ladder_experience,
)
from services.fetch_worker.lpt_adapter import (
    LPT_FILTER_CITY,
    LPT_FILTER_CURRENT_CITY,
    LPT_FILTER_EXPECT_CITY,
    LPT_FILTER_EXP_LABEL,
    LPT_JOB_FIELD_LABELS,
    LPT_JOB_TITLE_INPUT_MARKERS,
    LPT_MENU_SEARCH_TALENT,
    LPT_SEARCH_BAR_INPUT,
    LPT_SEARCH_BAR_LABELS,
    LPT_SEARCH_BUTTON,
    LPT_SEARCH_URL,
    LPT_UNLIMITED_JOB_ANCHOR,
    LptSearchParams,
)
from services.fetch_worker.lpt_city_picker import (
    apply_city_filter,
    apply_city_filter_for_row,
)
from services.fetch_worker.lpt_education_filter import apply_education_filters
from services.fetch_worker.lpt_other_filters import apply_other_filters
from services.fetch_worker.page_detector import PageDetectionError, PageType, detect_page_type

logger = logging.getLogger(__name__)
DEBUG_DIR = Path("data/debug")
PAGE_READY_TIMEOUT_MS = 45_000

# 在页面 DOM 上标记目标输入框
_MARK_ATTR = "data-hr-agent-search-bar"


async def _click_by_texts(page: Page, texts: list[str], *, exact: bool = False) -> bool:
    for text in texts:
        try:
            loc = page.get_by_text(text, exact=exact).first
            if await loc.is_visible(timeout=3000):
                await loc.click()
                await page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    return False


def _is_job_title_context(text: str) -> bool:
    t = text.replace("\n", " ")
    if any(k in t for k in ("任意关键词", "搜索栏", "搜索内容")):
        return False
    if any(k in t for k in LPT_JOB_FIELD_LABELS):
        return True
    return any(m.lower() in t.lower() for m in LPT_JOB_TITLE_INPUT_MARKERS)


def _is_search_bar_context(text: str) -> bool:
    t = text.replace("\n", " ")
    if _is_job_title_context(t):
        return False
    return any(
        k in t
        for k in (*LPT_SEARCH_BAR_LABELS, "搜索内容", "搜人才", "搜简历")
    )


async def _dismiss_search_bar_panels(page: Page, search_input: Locator | None = None) -> None:
    """关闭搜索栏联想/标签浮层，避免遮挡下方筛选项。"""
    for _ in range(2):
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(250)
        except Exception:
            pass

    if search_input is not None:
        try:
            await search_input.evaluate("el => el.blur()")
            await page.wait_for_timeout(200)
        except Exception:
            pass

    # 点击筛选栏空白处收起浮层（勿点「期望城市」，后续还要筛城市）
    try:
        anchor = page.get_by_text("工作经验", exact=False).first
        if await anchor.is_visible(timeout=1500):
            box = await anchor.bounding_box()
            if box:
                await page.mouse.click(max(8, box["x"] - 40), box["y"] + box["height"] / 2)
                await page.wait_for_timeout(400)
    except Exception:
        pass

    await page.evaluate(
        """() => {
            const isVisible = el => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 40 && r.height > 20 && r.top >= 0 && r.top < 360
                    && s.visibility !== 'hidden' && s.display !== 'none';
            };
            for (const el of document.querySelectorAll(
                '[class*="dropdown"], [class*="popover"], [class*="suggest"], '
                + '[class*="autocomplete"], [class*="select-dropdown"]'
            )) {
                if (!isVisible(el)) continue;
                el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            }
        }"""
    )
    await page.wait_for_timeout(300)


async def _fill_locator(loc: Locator, keywords: str, reason: str) -> None:
    page = loc.page
    await loc.scroll_into_view_if_needed()
    await loc.click()
    await loc.fill("")
    await loc.fill(keywords)
    filled = await loc.input_value()
    await _dismiss_search_bar_panels(page, loc)
    logger.info("Filled 搜索栏 via %s (len=%d)", reason, len(filled))
    print(f"[搜索] 已填入搜索栏（非职位栏）: {reason}", flush=True)
    from packages.workflow_events import emit

    emit("success", f"已填入搜索栏: {keywords[:80]}", category="search", meta={"reason": reason})


async def _save_debug(page: Page, name: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / f"{name}.png"
    try:
        await page.screenshot(path=str(path), full_page=True)
        logger.info("Debug screenshot: %s", path)
    except Exception as e:
        logger.warning("Screenshot failed: %s", e)


async def _wait_search_page_ready(page: Page, timeout_ms: int = PAGE_READY_TIMEOUT_MS) -> None:
    markers = ["期望城市", "工作经验", "搜索人才", "不限职位", "任意关键词", "职位"]
    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 20000))
    except PlaywrightTimeout:
        pass

    for _ in range(timeout_ms // 500):
        body = await page.locator("body").inner_text()
        if sum(1 for m in markers if m in body) >= 2:
            if await page.locator("input").count() > 0:
                return
        await page.wait_for_timeout(500)

    await _save_debug(page, "search_page_not_ready")
    raise RuntimeError("搜索页未加载完成。请确认已登录 LPT，或重新运行 login_liepin.ps1")


async def _mark_search_bar_via_dom(page: Page) -> dict | None:
    """用页面标签文本识别「搜索栏/任意关键词」，排除「职位」栏。"""
    return await page.evaluate(
        f"""() => {{
            document.querySelectorAll('[{_MARK_ATTR}]').forEach(
                el => el.removeAttribute('{_MARK_ATTR}')
            );
            const isVisible = el => {{
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 30 && r.height > 8 && r.top >= 0 && r.top < 750
                    && s.visibility !== 'hidden' && s.display !== 'none';
            }};
            const inputs = Array.from(
                document.querySelectorAll(
                    'input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea'
                )
            ).filter(isVisible);

            function context(el) {{
                let node = el.parentElement;
                let text = '';
                for (let i = 0; i < 10 && node; i++) {{
                    const t = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (t.length > 8) {{ text = t.slice(0, 400); break; }}
                    node = node.parentElement;
                }}
                const ph = el.placeholder || '';
                const aria = el.getAttribute('aria-label') || '';
                return {{ text, ph, aria, combined: (text + ' ' + ph + ' ' + aria) }};
            }}

            const scored = inputs.map(el => {{
                const c = context(el);
                const t = c.combined;
                let score = 0;
                let kind = 'other';

                if (t.includes('任意关键词') || t.includes('搜索栏')) {{
                    score += 200; kind = 'search_bar';
                }} else if (t.includes('关键词') && !t.includes('职位名称') && !t.includes('职位：')) {{
                    score += 120; kind = 'search_bar';
                }} else if (
                    (t.includes('搜索内容') || t.includes('搜人才') || t.includes('搜简历'))
                    && !t.includes('职位')
                ) {{
                    score += 90; kind = 'search_bar';
                }}

                if (t.includes('职位名称') || t.includes('当前职位') || c.ph.includes('职位')) {{
                    score -= 300; kind = 'job_title';
                }} else if (/职位(?!.*任意关键词)/.test(t) && !t.includes('搜索栏')) {{
                    score -= 200; kind = 'job_title';
                }}
                if (t.includes('公司名称') || t.includes('公司：')) {{
                    score -= 80; kind = 'company';
                }}

                return {{ el, score, kind, ph: c.ph, ctx: c.text.slice(0, 120) }};
            }});

            const searchCandidates = scored
                .filter(s => s.kind === 'search_bar' && s.score > 0)
                .sort((a, b) => b.score - a.score);

            let pick = searchCandidates[0] || null;

            if (!pick) {{
                const nonJob = scored
                    .filter(s => s.kind !== 'job_title' && s.kind !== 'company' && s.score > -100)
                    .sort((a, b) => b.score - a.score);
                if (nonJob.length >= 2) {{
                    const jobs = scored.filter(s => s.kind === 'job_title');
                    if (jobs.length > 0) {{
                        pick = nonJob[0];
                        pick.kind = 'search_bar_fallback';
                    }}
                }}
            }}

            if (!pick) return null;

            pick.el.setAttribute('{_MARK_ATTR}', '1');
            return {{
                kind: pick.kind,
                score: pick.score,
                placeholder: pick.ph,
                context: pick.ctx,
            }};
        }}"""
    )


async def _fill_beside_unlimited_job(page: Page, keywords: str) -> Locator | None:
    """在「不限职位」组件旁边紧挨着的输入框填关键词（用户指定位置）。"""
    anchor = page.get_by_text(LPT_UNLIMITED_JOB_ANCHOR, exact=False).first
    try:
        await anchor.wait_for(state="visible", timeout=10_000)
    except Exception:
        return None

    anchor_box = await anchor.bounding_box()
    if not anchor_box:
        return None

    # 1) 同行、位于「不限职位」右侧最近的 input
    best: tuple[float, Locator] | None = None
    inputs = page.locator("input:visible, textarea:visible")
    count = await inputs.count()
    for i in range(count):
        inp = inputs.nth(i)
        try:
            box = await inp.bounding_box()
            if not box or box["width"] < 60:
                continue
            same_row = abs(box["y"] - anchor_box["y"]) < 45
            to_right = box["x"] >= anchor_box["x"] + anchor_box["width"] - 30
            if same_row and to_right:
                dist = box["x"] - anchor_box["x"]
                if best is None or dist < best[0]:
                    best = (dist, inp)
        except Exception:
            continue

    if best:
        _, loc = best
        await _fill_locator(loc, keywords, "不限职位右侧紧邻输入框")
        return loc

    # 2) XPath：不限职位后的第一个 input
    xpaths = [
        f"//*[contains(text(),'{LPT_UNLIMITED_JOB_ANCHOR}')]/following::input[1]",
        f"//*[contains(text(),'{LPT_UNLIMITED_JOB_ANCHOR}')]/parent::*/following-sibling::*//input[1]",
        f"//*[contains(text(),'{LPT_UNLIMITED_JOB_ANCHOR}')]/ancestor::div[1]//input[last()]",
    ]
    for xp in xpaths:
        try:
            loc = page.locator(f"xpath={xp}").first
            if await loc.is_visible(timeout=2000):
                await _fill_locator(loc, keywords, f"不限职位旁:{xp[:50]}")
                return loc
        except Exception:
            continue

    # 3) JS：标记紧邻输入框
    meta = await page.evaluate(
        f"""() => {{
            const anchorText = '{LPT_UNLIMITED_JOB_ANCHOR}';
            const nodes = Array.from(document.querySelectorAll('*')).filter(el => {{
                const t = (el.innerText || '').trim();
                return t.includes(anchorText) && t.length < 30;
            }});
            for (const anchor of nodes) {{
                const a = anchor.getBoundingClientRect();
                const inputs = Array.from(document.querySelectorAll('input, textarea'))
                    .filter(el => {{
                        const r = el.getBoundingClientRect();
                        return r.width > 60 && r.height > 8
                            && Math.abs(r.top - a.top) < 45
                            && r.left >= a.right - 20;
                    }});
                if (inputs.length) {{
                    inputs.sort((x, y) => x.getBoundingClientRect().left - y.getBoundingClientRect().left);
                    const pick = inputs[0];
                    pick.setAttribute('{_MARK_ATTR}', '1');
                    return {{ ok: true, ph: pick.placeholder || '' }};
                }}
            }}
            return null;
        }}"""
    )
    if meta:
        loc = page.locator(f"input[{_MARK_ATTR}='1'], textarea[{_MARK_ATTR}='1']").first
        if await loc.is_visible(timeout=2000):
            await _fill_locator(loc, keywords, f"不限职位旁js ph={meta.get('ph')!r}")
            return loc

    return None


async def _fill_by_label_xpath(page: Page, keywords: str) -> Locator | None:
    """通过「任意关键词 / 搜索栏」标签定位输入框。"""
    xpaths = [
        "//*[contains(text(),'任意关键词')]/ancestor::*[.//input][1]//input[not(@type='hidden')][1]",
        "//*[contains(text(),'搜索栏')]/ancestor::*[.//input][1]//input[not(@type='hidden')][1]",
        "//label[contains(.,'任意关键词')]/following::input[1]",
        "//label[contains(.,'搜索栏')]/following::input[1]",
        "//*[contains(text(),'任意关键词')]/following::input[1]",
    ]
    for xp in xpaths:
        try:
            loc = page.locator(f"xpath={xp}").first
            if await loc.is_visible(timeout=2000):
                ph = (await loc.get_attribute("placeholder")) or ""
                ctx = await loc.evaluate(
                    "el => (el.closest('div')?.innerText || '').slice(0, 120)"
                )
                if not _is_job_title_context(ctx + ph):
                    await _fill_locator(loc, keywords, f"xpath:{xp[:40]}")
                    return loc
        except Exception:
            continue
    return None


async def _fill_search_bar_input(page: Page, keywords: str) -> Locator | None:
    """只填「不限职位」旁搜索栏，绝不填职位栏。"""
    await _wait_search_page_ready(page)

    loc = await _fill_beside_unlimited_job(page, keywords)
    if loc:
        return loc

    loc = await _fill_by_label_xpath(page, keywords)
    if loc:
        return loc

    meta = await _mark_search_bar_via_dom(page)
    if meta:
        loc = page.locator(f"input[{_MARK_ATTR}='1'], textarea[{_MARK_ATTR}='1']").first
        if await loc.is_visible(timeout=2000):
            await _fill_locator(
                loc,
                keywords,
                f"dom:{meta.get('kind')} ph={meta.get('placeholder')!r} ctx={meta.get('context')!r}",
            )
            return loc

    for sel in LPT_SEARCH_BAR_INPUT:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                ctx = await loc.evaluate(
                    "el => (el.closest('div')?.innerText || '').slice(0, 150)"
                )
                ph = (await loc.get_attribute("placeholder")) or ""
                if _is_search_bar_context(ctx + ph) or not _is_job_title_context(ctx + ph):
                    await _fill_locator(loc, keywords, sel)
                    return loc
        except Exception:
            continue

    await _save_debug(page, "search_bar_not_found")
    raise RuntimeError(
        "无法定位「搜索栏/任意关键词」输入框（已排除职位栏）。"
        "截图: data/debug/search_bar_not_found.png"
    )


async def _click_search_button(page: Page, search_input: Locator | None = None) -> None:
    if search_input is not None:
        try:
            container = search_input.locator("xpath=ancestor::*[position()<=6]")
            btn = container.locator("button:has-text('搜索')").first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                logger.info("Clicked 搜索 button beside 搜索栏")
                await page.wait_for_timeout(2000)
                return
        except Exception:
            pass

    for sel in LPT_SEARCH_BUTTON:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=2000):
                await loc.click()
                logger.info("Clicked search button via %s", sel)
                await page.wait_for_timeout(2000)
                return
        except Exception:
            continue

    if search_input is not None:
        await search_input.press("Enter")
        await page.wait_for_timeout(2000)


async def _click_experience_filter(page: Page, option_text: str) -> bool:
    """选择猎聘「工作经验」筛选项（仅 ladder 标签，如 3-5年）。"""
    opt = resolve_ladder_experience(option_text)
    if opt not in EXPERIENCE_LADDER:
        logger.warning("Cannot resolve experience to ladder option: %s", option_text)
        return False

    anchor_box = None
    try:
        anchor = page.get_by_text("工作经验", exact=False).first
        if await anchor.is_visible(timeout=1500):
            anchor_box = await anchor.bounding_box()
    except Exception:
        pass

    for item in LPT_FILTER_EXP_LABEL:
        try:
            loc = page.get_by_text(item, exact=False).first
            if await loc.is_visible(timeout=1500):
                await loc.click()
                await page.wait_for_timeout(300)
                break
        except Exception:
            continue

    loc = page.get_by_text(opt, exact=True)
    count = await loc.count()
    for i in range(count):
        item = loc.nth(i)
        try:
            if not await item.is_visible(timeout=800):
                continue
            if (await item.inner_text()).strip() != opt:
                continue
            box = await item.bounding_box()
            if anchor_box and box and abs(box["y"] - anchor_box["y"]) > 60:
                continue
            await item.click()
            await page.wait_for_timeout(500)
            logger.info("Selected experience filter: %s (requested=%s)", opt, option_text)
            return True
        except Exception:
            continue

    for variant in (opt, opt.replace("-", "至"), opt.replace("-", "~"), opt.replace("年", "")):
        try:
            chip = page.locator(f"text={variant}").first
            if await chip.is_visible(timeout=1200):
                await chip.click()
                await page.wait_for_timeout(500)
                logger.info("Selected experience chip: %s", variant)
                return True
        except Exception:
            continue

    logger.warning("未能选择工作年限: %s (resolved=%s)", option_text, opt)
    return False


def _is_experience_filter_label(label: str | list[str]) -> bool:
    if isinstance(label, str):
        return label in LPT_FILTER_EXP_LABEL
    return any(item in LPT_FILTER_EXP_LABEL for item in label)


async def _click_filter_option(page: Page, label: str | list[str], option_text: str) -> bool:
    clicked_label = False
    label_text = label if isinstance(label, str) else (label[0] if label else "")
    if label_text in (LPT_FILTER_EXPECT_CITY, LPT_FILTER_CITY) or label_text in LPT_FILTER_CURRENT_CITY:
        from services.fetch_worker.lpt_city_picker import click_city_filter

        clicked_label = await click_city_filter(page, label_text)
    elif label == LPT_FILTER_CITY:
        from services.fetch_worker.lpt_city_picker import click_expect_city_filter

        clicked_label = await click_expect_city_filter(page)
    elif _is_experience_filter_label(label):
        return await _click_experience_filter(page, option_text)
    else:
        labels = [label] if isinstance(label, str) else label
        for item in labels:
            try:
                label_loc = page.get_by_text(item, exact=False).first
                if await label_loc.is_visible(timeout=1500):
                    await label_loc.click()
                    clicked_label = True
                    await page.wait_for_timeout(300)
                    break
            except Exception:
                continue

    variants = _option_variants(option_text)
    for variant in variants:
        try:
            for container_sel in ["[class*='dropdown']", "[class*='popover']", "[class*='filter']", "body"]:
                container = page.locator(container_sel).first
                opt = container.get_by_text(variant, exact=False).first
                if await opt.is_visible(timeout=1500):
                    await opt.click()
                    logger.info("Selected filter option: %s", variant)
                    await page.wait_for_timeout(500)
                    return True
        except Exception:
            continue

    for variant in variants:
        try:
            chip = page.locator(f"text={variant}").first
            if await chip.is_visible(timeout=1500):
                await chip.click()
                logger.info("Selected filter chip: %s", variant)
                await page.wait_for_timeout(500)
                return True
        except Exception:
            continue

    logger.warning("未能选择筛选项: %s (label clicked=%s)", option_text, clicked_label)
    return False


def _option_variants(text: str) -> list[str]:
    variants = [text]
    if "年" in text:
        variants.append(text.replace("年", ""))
        variants.append(text.replace("-", "至"))
        variants.append(text.replace("-", "~"))
    return variants


async def navigate_to_search_talent(page: Page) -> None:
    await page.goto(LPT_SEARCH_URL, wait_until="load", timeout=60_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=20_000)
    except PlaywrightTimeout:
        await page.wait_for_timeout(3000)

    page_type = await detect_page_type(page)
    if page_type == PageType.LOGIN:
        raise PageDetectionError(
            PageType.LOGIN,
            "检测到登录页。请先运行: .\\scripts\\login_liepin.ps1 完成猎聘 LPT 登录",
        )

    if not await _is_on_search_page(page):
        clicked = await _click_by_texts(page, LPT_MENU_SEARCH_TALENT)
        if clicked:
            await page.wait_for_timeout(3000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeout:
                pass
        else:
            logger.warning("未找到「搜索人才」菜单，等待当前页继续加载")
            await page.wait_for_timeout(3000)


async def _is_on_search_page(page: Page) -> bool:
    body = await page.locator("body").inner_text()
    indicators = ["搜索人才", "期望城市", "工作经验", "不限职位", "任意关键词", "职位"]
    return sum(1 for i in indicators if i in body) >= 2


async def apply_lpt_search_filters(page: Page, params: LptSearchParams) -> dict[str, object]:
    """Best-effort 应用全部猎聘筛选项；空字段跳过，失败不阻断。"""
    summary: dict[str, object] = {"skipped": [], "applied": [], "failed": []}

    current = params.resolved_current_cities()
    if current:
        ok = await apply_city_filter_for_row(page, LPT_FILTER_CURRENT_CITY[0], current)
        key = "applied" if ok else "failed"
        summary[key].append({"current_cities": current})
        if not ok:
            logger.warning("Failed to apply 目前城市: %s", current)
    else:
        summary["skipped"].append("current_cities")

    cities = params.resolved_cities()
    if cities:
        ok = await apply_city_filter(page, city=params.city, cities=cities)
        key = "applied" if ok else "failed"
        summary[key].append({"cities": cities})
    else:
        summary["skipped"].append("cities")

    if params.experience:
        ok = await _click_experience_filter(page, params.experience)
        key = "applied" if ok else "failed"
        summary[key].append({"experience": params.experience})
    else:
        summary["skipped"].append("experience")

    edu_result = await apply_education_filters(page, params.education)
    if edu_result:
        summary["applied"].append({"education": edu_result})
    else:
        summary["skipped"].append("education")

    other_result = await apply_other_filters(page, params.other_filters)
    if other_result:
        summary["applied"].append({"other_filters": other_result})
    else:
        summary["skipped"].append("other_filters")

    return summary


async def run_lpt_search(page: Page, params: LptSearchParams) -> None:
    await navigate_to_search_talent(page)
    search_input = await _fill_search_bar_input(page, params.keywords)
    filter_summary = await apply_lpt_search_filters(page, params)
    await _click_search_button(page, search_input)

    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeout:
        await page.wait_for_timeout(3000)

    current = params.resolved_current_cities()
    cities = params.resolved_cities()
    city_label = "、".join(cities)
    current_label = "、".join(current)
    logger.info(
        "LPT search completed: keywords=%s current=%s cities=%s exp=%s filters=%s",
        params.keywords,
        current_label,
        city_label,
        params.experience,
        filter_summary,
    )
    from packages.workflow_events import emit

    emit(
        "success",
        f"搜索完成: 关键词={params.keywords} 目前={current_label or '—'} 期望={city_label} 经验={params.experience}",
        category="search",
        meta={
            "keywords": params.keywords,
            "current_cities": current,
            "city": city_label,
            "cities": cities,
            "experience": params.experience,
            "filter_summary": filter_summary,
        },
    )


async def count_result_cards(page: Page) -> int:
    from services.fetch_worker.lpt_adapter import LPT_RESUME_CARD

    best = 0
    for sel in LPT_RESUME_CARD:
        try:
            count = await page.locator(sel).count()
            if count > best:
                best = count
        except Exception:
            continue
    return best


async def wait_for_result_cards(page: Page, timeout_ms: int = 15000) -> bool:
    from services.fetch_worker.lpt_adapter import LPT_RESUME_CARD

    for sel in LPT_RESUME_CARD:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            count = await page.locator(sel).count()
            if count > 0:
                logger.info("Found %d resume cards via %s", count, sel)
                return True
        except Exception:
            continue
    return False


async def rerun_lpt_search_with_keywords(page: Page, params: LptSearchParams, keywords: str) -> None:
    """保持城市与年限，更换搜索栏关键词后重新搜索。"""
    from packages.workflow_events import emit

    params.keywords = keywords
    await navigate_to_search_talent(page)
    search_input = await _fill_search_bar_input(page, keywords)
    await apply_lpt_search_filters(page, params)
    await _click_search_button(page, search_input)

    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeout:
        await page.wait_for_timeout(3000)

    logger.info(
        "LPT search retried with relaxed keywords: keywords=%s city=%s exp=%s",
        keywords,
        params.city,
        params.experience,
    )
    emit(
        "warn",
        f"搜索结果过少，删减关键词为「{keywords}」后重新搜索",
        category="search",
        meta={
            "keywords": keywords,
            "city": params.city,
            "experience": params.experience,
            "reason": "list_exhausted",
        },
    )


async def rerun_lpt_search_with_experience(page: Page, params: LptSearchParams, experience: str) -> None:
    """保持关键词与城市不变，仅更换工作年限后重新搜索。"""
    from packages.workflow_events import emit

    params.experience = experience
    await navigate_to_search_talent(page)
    search_input = await _fill_search_bar_input(page, params.keywords)
    await apply_lpt_search_filters(page, params)
    await _click_search_button(page, search_input)
    await _click_search_button(page, search_input)

    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeout:
        await page.wait_for_timeout(3000)

    logger.info(
        "LPT search retried with relaxed experience: keywords=%s city=%s exp=%s",
        params.keywords,
        params.city,
        experience,
    )
    emit(
        "warn",
        f"结果不足，放宽工作年限为「{experience}」后重新搜索",
        category="search",
        meta={
            "keywords": params.keywords,
            "city": params.city,
            "experience": experience,
            "reason": "insufficient_results",
        },
    )
