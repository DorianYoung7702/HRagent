"""从 LPT 弹窗在线简历抽取候选人信息（严格线性：每步确认后再继续）。"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeout

from packages.schemas.candidate import CandidateSnapshotData
from packages.candidate_identity import candidate_identity_hash
from services.fetch_worker.extract_detail import (
    _parse_education,
    _parse_skills,
    _parse_work_years,
    expand_all_sections,
    scroll_to_load,
)
from services.fetch_worker.extract_monitor import JobSelectStuckTracker
from services.fetch_worker.collect_grouping import (
    CollectGroupConfig,
    build_collect_metadata_patch,
    infer_ui_target,
    resolve_collect_folder_tag,
)
from services.fetch_worker.lpt_adapter import (
    LPT_COLLECT_BUTTONS,
    LPT_CONTACT_NOW,
    LPT_EXIT_BUTTONS,
    LPT_JOB_SELECT_CARD,
    LPT_JOB_SELECT_TEXT,
    LPT_POPUP_CLOSE,
    LPT_POPUP_CONTAINER,
    LPT_RESUME_CARD,
    LPT_SECTION_TITLES,
)

logger = logging.getLogger(__name__)
DEBUG_DIR = Path("data/debug")


class ContactNowResult(NamedTuple):
    ok: bool
    prior_communication: bool = False


_DETECT_COMMUNICATE_STATE_JS = """(root) => {
    const nodes = [...root.querySelectorAll('button, a, span, div')];
    let hasImmediate = false;
    let hasContinue = false;
    for (const el of nodes) {
        const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
        if (!t || t.length > 24) continue;
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        if (r.width < 2 || r.height < 2 || s.visibility === 'hidden' || s.display === 'none') continue;
        if (t.includes('立即沟通') || t.includes('立即开聊')) hasImmediate = true;
        if (t.includes('继续沟通')) hasContinue = true;
    }
    if (hasImmediate) return 'fresh';
    if (hasContinue) return 'prior';
    return 'none';
}"""

STEP_TIMEOUT_MS = 30_000
POPUP_WAIT_MS = 20_000
AI_WAIT_MS = 120_000
CONTACT_WAIT_MS = 15_000
CLOSE_WAIT_MS = 10_000
_CARD_MARK = "data-hr-agent-card"
_TOP_OVERLAY_MARK = "data-hr-agent-top-overlay"
_COLLECT_CARD_MARK = "data-hr-collect-card"

# 识别最上层浮层（按 z-index / 面积排序）
_TOPMOST_OVERLAY_JS = """(markAttr) => {
    document.querySelectorAll(`[${markAttr}]`).forEach(el => el.removeAttribute(markAttr));
    const isVisible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 80 && r.height > 80 && r.bottom > 0 && r.top < innerHeight
            && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
    };
    const score = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        const z = parseInt(s.zIndex) || 0;
        return z * 1e6 + r.width * r.height;
    };
    const nodes = [...document.querySelectorAll(
        "[role='dialog'], [class*='modal'], [class*='Modal'], [class*='drawer'], "
        + "[class*='Drawer'], [class*='popup'], [class*='Popup'], [class*='overlay'], "
        + "[class*='dialog'], [class*='mask'] + *"
    )].filter(isVisible);
    nodes.sort((a, b) => score(b) - score(a));
    return nodes;
};
"""
_ACTIVITY_LABELS = re.compile(r"^(今天|刚刚|最近|本周|本月|3天|7天|30天).{0,6}活跃$")


def _step_log(msg: str) -> None:
    print(f"[步骤] {msg}", flush=True)
    sys.stdout.flush()
    from packages.workflow_events import emit

    emit("info", msg, category="extract")


def _step_done(msg: str) -> None:
    print(f"[完成] {msg}", flush=True)
    sys.stdout.flush()
    from packages.workflow_events import emit

    emit("success", msg, category="extract")


def _step_fail(msg: str) -> None:
    print(f"[失败] {msg}", flush=True)
    sys.stdout.flush()
    from packages.workflow_events import emit

    emit("error", msg, category="extract")


async def _find_card_selector(page: Page) -> str | None:
    """保留兼容；实际点击使用 _collect_unique_resume_cards。"""
    for sel in LPT_RESUME_CARD:
        try:
            if await page.locator(sel).count() > 0:
                return sel
        except Exception:
            continue
    return None


async def _collect_unique_resume_cards(page: Page) -> list[dict]:
    """收集顶层简历卡片，去掉嵌套重复节点。"""
    cards = await page.evaluate(
        f"""() => {{
            document.querySelectorAll('[{_CARD_MARK}]').forEach(el => el.removeAttribute('{_CARD_MARK}'));
            const sels = [
                '[class*="resume-card"]', '[class*="ResumeCard"]',
                '[class*="candidate-card"]', '[class*="talent-card"]',
                '[class*="resume-list"] > div', '[class*="resume-list"] > li',
                '[class*="result-list"] > div',
            ];
            const seen = new Set();
            const nodes = [];
            for (const sel of sels) {{
                document.querySelectorAll(sel).forEach(el => {{
                    if (seen.has(el)) return;
                    seen.add(el);
                    const r = el.getBoundingClientRect();
                    if (r.height < 80 || r.width < 200 || r.top < 0) return;
                    nodes.push(el);
                }});
            }}
            const roots = nodes.filter(el =>
                !nodes.some(other => other !== el && other.contains(el))
            );
            roots.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
            return roots.map((el, idx) => {{
                el.setAttribute('{_CARD_MARK}', String(idx));
                const text = (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240);
                return {{ idx, text, top: el.getBoundingClientRect().top }};
            }});
        }}"""
    )
    return cards or []


def _preview_fingerprint(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.strip())[:300]
    return hashlib.md5(norm.encode()).hexdigest()


def _parse_preview_name(lines: list[str]) -> str | None:
    from services.fetch_worker.im_contact_match import parse_name_from_card

    return parse_name_from_card(lines)


async def _extract_card_preview(page: Page, card_locator: Locator) -> dict:
    from services.fetch_worker.im_contact_match import (
        parse_age_from_text,
        parse_education_level,
        parse_name_from_card,
        parse_school_from_text,
    )

    text = await card_locator.inner_text()
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return {
        "display_name": _parse_preview_name(lines) or parse_name_from_card(lines),
        "card_age": parse_age_from_text(text),
        "card_school": parse_school_from_text(text),
        "education_level": parse_education_level(text),
        "card_text": text,
        "fingerprint": _preview_fingerprint(text),
    }


async def _is_popup_visible(page: Page) -> bool:
    for sel in LPT_POPUP_CONTAINER:
        try:
            loc = page.locator(sel).last
            if await loc.is_visible(timeout=300):
                text = await loc.inner_text()
                if any(k in text for k in ("工作经历", "项目经历", "教育经历", "简历")):
                    return True
        except Exception:
            continue
    return False


async def _wait_popup_open(page: Page, timeout_ms: int = POPUP_WAIT_MS) -> Locator | None:
    """等待弹窗出现并返回 locator，未出现则返回 None。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for sel in LPT_POPUP_CONTAINER:
            try:
                loc = page.locator(sel).last
                if await loc.is_visible(timeout=500):
                    text = await loc.inner_text()
                    if len(text.strip()) > 80 and any(
                        k in text for k in ("工作经历", "项目经历", "教育经历")
                    ):
                        return loc
            except Exception:
                continue
        await page.wait_for_timeout(400)
    return None


async def _wait_popup_closed(page: Page, timeout_ms: int = CLOSE_WAIT_MS) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if not await _is_popup_visible(page):
            return True
        await page.wait_for_timeout(300)
    return False


async def _wait_contact_confirmed(page: Page, timeout_ms: int = CONTACT_WAIT_MS) -> bool:
    """点击立即沟通后，等待沟通面板/输入框出现。"""
    markers = [
        "textarea[placeholder*='消息']",
        "textarea[placeholder*='请输入']",
        "input[placeholder*='消息']",
        "[class*='im-chat']",
        "[class*='chat-input']",
        "[class*='message-input']",
    ]
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for sel in markers:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=400):
                    return True
            except Exception:
                continue
        try:
            body = await page.locator("body").inner_text()
            if any(k in body for k in ("发送消息", "写消息", "沟通内容", "请输入沟通")):
                return True
        except Exception:
            pass
        await page.wait_for_timeout(400)
    return False


async def _save_debug_screenshot(page: Page, name: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DEBUG_DIR / f"{name}_{ts}.png"
    try:
        await page.screenshot(path=str(path), full_page=True)
        logger.info("Debug screenshot saved: %s", path)
    except Exception as e:
        logger.warning("Failed to save screenshot: %s", e)


def _is_job_select_text(text: str) -> bool:
    if any(k in text for k in LPT_JOB_SELECT_TEXT):
        return True
    return "岗位" in text and ("开聊" in text or "沟通" in text)


async def _classify_topmost_overlay(page: Page) -> str:
    """返回最上层浮层类型: job_select | resume | other | none。"""
    kind = await page.evaluate(
        f"""() => {{
            const jobKeys = {LPT_JOB_SELECT_TEXT!r};
            const resumeKeys = ['工作经历', '项目经历', '立即沟通', '立即开聊', '在线简历'];
            const getNodes = {_TOPMOST_OVERLAY_JS}
            const nodes = getNodes('{_TOP_OVERLAY_MARK}');
            for (const el of nodes) {{
                const text = (el.innerText || '').slice(0, 2000);
                const isJob = jobKeys.some(k => text.includes(k))
                    || (text.includes('岗位') && (text.includes('开聊') || text.includes('沟通')));
                if (isJob) return 'job_select';
                if (resumeKeys.some(k => text.includes(k))) return 'resume';
                if (text.trim().length > 30) return 'other';
            }}
            return 'none';
        }}"""
    )
    return kind or "none"


async def _is_job_select_popup_visible(page: Page) -> bool:
    """最上层是否为「选择岗位」弹窗。"""
    return await _classify_topmost_overlay(page) == "job_select"


async def _find_topmost_job_select_dialog(page: Page) -> Locator | None:
    """仅定位 z-index 最高的岗位选择弹窗。"""
    marked = await page.evaluate(
        f"""() => {{
            const jobKeys = {LPT_JOB_SELECT_TEXT!r};
            const getNodes = {_TOPMOST_OVERLAY_JS}
            const nodes = getNodes('{_TOP_OVERLAY_MARK}');
            for (const el of nodes) {{
                const text = (el.innerText || '').slice(0, 2000);
                const isJob = jobKeys.some(k => text.includes(k))
                    || (text.includes('岗位') && (text.includes('开聊') || text.includes('沟通')));
                if (!isJob) continue;
                el.setAttribute('{_TOP_OVERLAY_MARK}', 'job');
                return {{ ok: true }};
            }}
            return null;
        }}"""
    )
    if marked and marked.get("ok"):
        loc = page.locator(f"[{_TOP_OVERLAY_MARK}='job']").first
        if await loc.is_visible(timeout=500):
            return loc
    return None


async def _find_job_select_dialog(page: Page) -> Locator | None:
    return await _find_topmost_job_select_dialog(page)


async def _collect_job_position_entries(dialog: Locator) -> list[tuple[str, Locator]]:
    """收集岗位弹窗内可选职位卡片（去重）。"""
    entries: list[tuple[str, Locator]] = []
    seen: set[str] = set()
    skip = {"确认", "确定", "取消", "关闭", "退出", "确认开聊"}

    for csel in LPT_JOB_SELECT_CARD:
        try:
            cards = dialog.locator(csel)
            count = await cards.count()
            for j in range(count):
                card = cards.nth(j)
                if not await card.is_visible(timeout=300):
                    continue
                box = await card.bounding_box()
                if not box or box["height"] < 32 or box["width"] < 80:
                    continue
                text = (await card.inner_text()).strip()
                if not text or text in skip or any(text.startswith(s) for s in skip):
                    continue
                key = text[:120]
                if key in seen:
                    continue
                seen.add(key)
                entries.append((text, card))
        except Exception:
            continue

    if entries:
        return entries

    try:
        metas = await dialog.evaluate(
            """(root) => {
                const skip = new Set(['确认', '确定', '取消', '关闭', '退出', '确认开聊']);
                const items = [...root.querySelectorAll('li, [class*=item], [class*=card], [class*=position]')];
                const out = [];
                for (let i = 0; i < items.length; i++) {
                    const el = items[i];
                    const r = el.getBoundingClientRect();
                    const t = (el.innerText || '').trim();
                    if (r.height < 32 || r.width < 80 || !t) continue;
                    if ([...skip].some(s => t === s || t.startsWith(s))) continue;
                    el.setAttribute('data-hr-agent-job-opt', String(out.length));
                    out.push(t.slice(0, 120));
                }
                return out;
            }"""
        )
        for i, text in enumerate(metas or []):
            loc = dialog.locator(f"[data-hr-agent-job-opt='{i}']").first
            if await loc.count() > 0:
                entries.append((text, loc))
    except Exception:
        pass
    return entries


async def _click_matching_job_position(dialog: Locator, job_title: str | None = None) -> tuple[bool, str | None]:
    """在岗位弹窗中按主页岗位名匹配卡片。"""
    from services.fetch_worker.job_select_match import pick_best_job_card_index

    entries = await _collect_job_position_entries(dialog)
    if not entries:
        return False, None

    texts = [t for t, _ in entries]
    target = (job_title or "").strip()
    if target:
        idx, score = pick_best_job_card_index(texts, target)
        if idx < 0:
            _step_fail(
                f"岗位弹窗：未找到包含岗位名「{target}」的卡片（共 {len(entries)} 项），"
                "请调整筛选需求岗位名称"
            )
            logger.warning(
                "Job select no match: target=%r options=%r",
                target,
                texts[:8],
            )
            return False, None
        chosen_text, chosen = entries[idx]
        _step_log(
            f"岗位弹窗：匹配「{target}」→「{chosen_text[:40]}」"
            f"（score={score}，共 {len(entries)} 项）"
        )
        logger.info(
            "Job select match: target=%r picked=%r score=%d options=%d",
            target,
            chosen_text[:60],
            score,
            len(entries),
        )
    else:
        chosen_text, chosen = entries[0]
        _step_log(f"岗位弹窗：未指定开聊岗位，选择第一项「{chosen_text[:40]}」（共 {len(entries)} 项）")

    try:
        await chosen.scroll_into_view_if_needed()
        try:
            await chosen.click(timeout=5000)
        except Exception:
            await chosen.click(timeout=5000, force=True)
        return True, chosen_text
    except Exception as e:
        logger.warning("Job card click failed: %s", e)
        return False, None


async def _click_first_job_position(dialog: Locator) -> bool:
    """兼容旧逻辑：无岗位名时选第一项。"""
    ok, _ = await _click_matching_job_position(dialog, job_title=None)
    return ok


async def _click_job_confirm_button(page: Page, dialog: Locator) -> bool:
    """仅在顶层岗位弹窗内点击底部「确认/确定」。"""
    clicked = await dialog.evaluate(
        """(root) => {
            const labels = ['确认开聊', '确认', '确定'];
            const rootBox = root.getBoundingClientRect();
            const nodes = [...root.querySelectorAll('button, a, span[role=button]')];
            const picks = [];
            for (const el of nodes) {
                const t = (el.innerText || '').trim();
                if (!labels.some(l => t === l || t.startsWith(l))) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 20 || r.height < 16) continue;
                if (r.bottom < rootBox.top || r.top > rootBox.bottom) continue;
                const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                if (disabled) continue;
                picks.push({ el, bottom: r.bottom });
            }
            picks.sort((a, b) => b.bottom - a.bottom);
            if (!picks.length) return false;
            picks[0].el.click();
            return true;
        }"""
    )
    if clicked:
        return True

    for label in ("确认开聊", "确认", "确定"):
        try:
            btn = dialog.locator(f"button:has-text('{label}'), a:has-text('{label}')").last
            if await btn.is_visible(timeout=400) and await btn.is_enabled():
                await btn.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


_job_select_tracker: "JobSelectStuckTracker | None" = None


def _get_job_select_tracker() -> "JobSelectStuckTracker":
    global _job_select_tracker
    if _job_select_tracker is None:
        _job_select_tracker = JobSelectStuckTracker()
    return _job_select_tracker


async def _dismiss_topmost_overlay(page: Page) -> bool:
    """关闭/取消/退出最上层浮层，不重复点岗位列表。"""
    clicked = await page.evaluate(
        f"""() => {{
            const getNodes = {_TOPMOST_OVERLAY_JS}
            const nodes = getNodes('{_TOP_OVERLAY_MARK}');
            if (!nodes.length) return false;
            const root = nodes[0];
            const labels = ['关闭', '取消', '退出', '返回'];
            const btns = [...root.querySelectorAll('button, a, span[role=button], [class*=close]')];
            const picks = [];
            for (const el of btns) {{
                const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
                const cls = String(el.className || '');
                const hit = labels.some(l => t.includes(l)) || /close/i.test(cls);
                if (!hit) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 10) continue;
                picks.push({{ el, z: parseInt(getComputedStyle(el).zIndex) || 0 }});
            }}
            picks.sort((a, b) => b.z - a.z);
            if (picks.length) {{
                picks[0].el.click();
                return true;
            }}
            return false;
        }}"""
    )
    if clicked:
        await page.wait_for_timeout(650)
        return True
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(450)
    return False


async def _recover_job_select_loop(page: Page, *, reason: str, workflow_id: str | None = None) -> None:
    """岗位弹窗死循环：强制逐层退出，不再重复选职位。"""
    _step_fail(f"[监控] 岗位弹窗卡死: {reason}")
    from packages.workflow_events import emit

    emit(
        "warn",
        f"岗位弹窗卡死，强制退出浮层: {reason}",
        category="watchdog",
        workflow_id=workflow_id,
        meta={"reason": reason},
    )
    await _save_debug_screenshot(page, "job_select_stuck")
    _get_job_select_tracker().reset()

    for _ in range(8):
        if not await _is_job_select_popup_visible(page):
            if await _is_list_interactive(page):
                _step_done("[监控] 岗位弹窗卡死已清理，列表恢复")
                return
        if await _dismiss_topmost_overlay(page):
            continue
        await _click_topmost_exit(page)
        await page.wait_for_timeout(500)


async def _handle_job_select_popup(
    page: Page,
    *,
    job_title: str | None = None,
    workflow_id: str | None = None,
) -> bool:
    """开聊岗位弹窗：按岗位名匹配卡片，重复未关闭则强制退出。"""
    tracker = _get_job_select_tracker()

    if not await _is_job_select_popup_visible(page):
        tracker.reset()
        return True

    if tracker.failed_cycles >= tracker.REPEAT_LIMIT:
        reason = f"岗位弹窗重复操作 {tracker.failed_cycles} 次仍未关闭（可能未点到最上层浮层）"
        await _recover_job_select_loop(page, reason=reason, workflow_id=workflow_id)
        return False

    for _ in range(2):
        dialog = await _find_topmost_job_select_dialog(page)
        if dialog is None:
            await page.wait_for_timeout(350)
            break

        _step_log("岗位弹窗（顶层）：选择开聊职位...")
        job_clicked, picked_title = await _click_matching_job_position(dialog, job_title)
        if not job_clicked:
            _step_fail("顶层岗位弹窗未找到可点击职位")
            await _dismiss_topmost_overlay(page)
            break
        _step_done(f"已选择开聊职位: {(picked_title or '')[:40]}")
        await page.wait_for_timeout(500)

        _step_log("岗位弹窗（顶层）：点击确认...")
        if not await _click_job_confirm_button(page, dialog):
            _step_fail("顶层岗位弹窗未找到确认按钮")
            await _dismiss_topmost_overlay(page)
            break
        _step_done("已点击确认")
        await page.wait_for_timeout(800)

        still = await _is_job_select_popup_visible(page)
        stuck, reason = tracker.on_cycle_complete(still)
        if not still:
            return True
        if stuck:
            await _recover_job_select_loop(page, reason=reason, workflow_id=workflow_id)
            return False

    if await _is_job_select_popup_visible(page):
        stuck, reason = tracker.on_cycle_complete(True)
        if stuck:
            await _recover_job_select_loop(page, reason=reason, workflow_id=workflow_id)
        return False
    tracker.reset()
    return True


async def _has_blocking_overlay(page: Page) -> bool:
    return await _is_job_select_popup_visible(page) or await _is_popup_visible(page)


async def _is_list_interactive(page: Page) -> bool:
    """列表可操作：无残留浮层且可见简历卡片。"""
    if await _has_blocking_overlay(page):
        return False
    return len(await _collect_unique_resume_cards(page)) > 0


async def _click_topmost_exit(page: Page) -> bool:
    """点击最上层「退出/返回/关闭」按钮（开聊后常需连点两级）。"""
    clicked = await page.evaluate(
        """() => {
            const labels = ['退出', '返回', '关闭'];
            const nodes = [...document.querySelectorAll(
                'button, a, span[role=button], [class*=close], [aria-label=Close]'
            )];
            const picks = [];
            for (const el of nodes) {
                const r = el.getBoundingClientRect();
                if (r.width < 12 || r.height < 12 || r.bottom < 0 || r.top > innerHeight) continue;
                const style = getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none' || style.pointerEvents === 'none') continue;
                const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                const cls = String(el.className || '');
                const hit = labels.some(l => text.includes(l)) || /close/i.test(cls);
                if (!hit) continue;
                const z = parseInt(style.zIndex) || 0;
                picks.push({ el, z, top: r.top });
            }
            picks.sort((a, b) => b.z - a.z || a.top - b.top);
            if (!picks.length) return false;
            picks[0].el.click();
            return true;
        }"""
    )
    if clicked:
        await page.wait_for_timeout(650)
        return True

    for sel in LPT_EXIT_BUTTONS + LPT_POPUP_CLOSE:
        try:
            btns = page.locator(sel)
            count = await btns.count()
            for i in range(count - 1, -1, -1):
                btn = btns.nth(i)
                if await btn.is_visible(timeout=250):
                    await btn.click(timeout=3000)
                    await page.wait_for_timeout(650)
                    return True
        except Exception:
            continue
    return False


async def _force_recovery_to_list(
    page: Page,
    reason: str,
    *,
    workflow_id: str,
    loop_attempt: int,
) -> bool:
    """调度监控：检测到卡死时强制连点退出，清掉列表上方所有浮层。"""
    _step_fail(f"[监控] 卡死信号: {reason}")
    from packages.workflow_events import emit

    emit(
        "warn",
        f"调度监控触发恢复: {reason}",
        category="watchdog",
        workflow_id=workflow_id,
        meta={"loop_attempt": loop_attempt, "reason": reason},
    )
    await _save_debug_screenshot(page, f"watchdog_stuck_{loop_attempt}")

    _get_job_select_tracker().reset()

    for round_i in range(12):
        if await _is_list_interactive(page):
            _step_done(f"[监控] 列表已恢复（第 {round_i + 1} 轮清理后）")
            emit(
                "success",
                "调度监控：列表功能已恢复",
                category="watchdog",
                workflow_id=workflow_id,
            )
            return True

        top = await _classify_topmost_overlay(page)
        if top == "job_select":
            await _recover_job_select_loop(
                page,
                reason="调度监控：岗位弹窗阻塞列表",
                workflow_id=workflow_id,
            )
            continue

        await _dismiss_topmost_overlay(page)
        await _click_topmost_exit(page)
        if await _is_popup_visible(page):
            await _close_popup(page)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

    await page.mouse.wheel(0, -600)
    await page.wait_for_timeout(500)
    ok = await _is_list_interactive(page)
    if not ok:
        emit(
            "error",
            "调度监控：强制恢复后列表仍不可操作",
            category="watchdog",
            workflow_id=workflow_id,
        )
    return ok


async def _ensure_back_to_list(page: Page, *, min_exit_levels: int = 2, workflow_id: str | None = None) -> bool:
    """关闭开聊/岗位/简历等浮层；默认至少尝试退出两级再回到列表。"""
    exit_clicks = 0
    for _ in range(10):
        if await _is_list_interactive(page):
            _get_job_select_tracker().reset()
            return True

        top = await _classify_topmost_overlay(page)
        if top == "job_select":
            ok = await _handle_job_select_popup(page, workflow_id=workflow_id)
            if not ok:
                await _dismiss_topmost_overlay(page)
            continue

        if await _click_topmost_exit(page):
            exit_clicks += 1
            continue

        if await _is_popup_visible(page) and await _close_popup(page):
            exit_clicks += 1
            continue

        await page.keyboard.press("Escape")
        await page.wait_for_timeout(450)
        exit_clicks += 1

        if exit_clicks >= min_exit_levels and await _is_list_interactive(page):
            return True

    await page.mouse.wheel(0, -500)
    await page.wait_for_timeout(500)
    return await _is_list_interactive(page)


async def _close_popup(page: Page) -> bool:
    for sel in LPT_POPUP_CLOSE:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                if await _wait_popup_closed(page):
                    return True
        except Exception:
            continue
    await page.keyboard.press("Escape")
    return await _wait_popup_closed(page, timeout_ms=5000)


async def _detect_resume_communicate_state(resume_popup: Locator) -> str:
    """Return ``fresh`` (立即沟通), ``prior`` (仅继续沟通), or ``none``."""
    try:
        state = await resume_popup.evaluate(_DETECT_COMMUNICATE_STATE_JS)
        if state in ("fresh", "prior", "none"):
            return state
    except Exception:
        pass
    return "none"


async def _click_chat_button_in_scope(scope: Locator | Page) -> bool:
    """在简历弹窗内点击「立即沟通」（LPT 当前按钮文案）。"""
    for sel in LPT_CONTACT_NOW:
        try:
            locs = scope.locator(sel)
            count = await locs.count()
            for i in range(count - 1, -1, -1):
                btn = locs.nth(i)
                if not await btn.is_visible(timeout=1500):
                    continue
                text = re.sub(r"\s+", " ", (await btn.inner_text() or "")).strip()
                if not any(k in text for k in ("立即沟通", "立即开聊", "继续沟通")):
                    continue
                await btn.scroll_into_view_if_needed()
                try:
                    await btn.click(timeout=5000)
                except Exception:
                    await btn.click(timeout=5000, force=True)
                return True
        except Exception:
            continue
    return False


async def _resolve_online_resume_popup(page: Page, popup: Locator | None = None) -> Locator | None:
    """定位当前在线简历弹窗，全程在同一搜索结果页内操作，不跳转其他页面。"""
    if popup is not None:
        try:
            if await popup.is_visible(timeout=800):
                text = await popup.inner_text()
                if any(
                    k in text
                    for k in ("工作经历", "项目经历", "教育经历", "立即沟通", "立即开聊", "收藏")
                ):
                    return popup
        except Exception:
            pass
    return await _wait_popup_open(page, timeout_ms=4000)


_COLLECT_FOLDER_MODAL_JS = """() => {
    const mark = '__COLLECT_MARK__';
    document.querySelectorAll(`[${mark}]`).forEach(el => el.removeAttribute(mark));
    const isCollectFolder = (text) => {
        if (!text) return false;
        if (text.includes('收藏简历') && text.includes('分组列表')) return true;
        if (text.includes('分组列表') && text.includes('未分组')) return true;
        if (text.includes('分组列表') && (/追问\\(\\d+\\)/.test(text) || /观察\\(\\d+\\)/.test(text))) return true;
        return false;
    };
    const isVisible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 40 && r.height > 40 && r.bottom > 0 && r.top < innerHeight
            && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
    };
    const pickBest = (nodes) => {
        let best = null;
        let bestArea = Infinity;
        for (const el of nodes) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || '').slice(0, 1500);
            if (!isCollectFolder(text)) continue;
            const r = el.getBoundingClientRect();
            if (r.width > innerWidth * 0.92 || r.height > innerHeight * 0.92) continue;
            const area = r.width * r.height;
            if (area >= bestArea) continue;
            best = el;
            bestArea = area;
        }
        return best;
    };
    const getNodes = __TOPMOST_JS__;
    let best = pickBest(getNodes('__TOP_MARK__'));
    if (!best) {
        best = pickBest([...document.querySelectorAll(
            "[role='dialog'], [class*='modal'], [class*='Modal'], [class*='popup'], [class*='Popup'], [class*='drawer'], div, section, form"
        )]);
    }
    if (!best) return { ok: false };
    best.setAttribute(mark, '1');
    return {
        ok: true,
        preview: (best.innerText || '').slice(0, 100).replace(/\\s+/g, ' '),
    };
}""".replace("__COLLECT_MARK__", _COLLECT_CARD_MARK).replace("__TOPMOST_JS__", _TOPMOST_OVERLAY_JS).replace("__TOP_MARK__", _TOP_OVERLAY_MARK)


async def _wait_collect_folder_modal(page: Page, *, timeout_ms: int = 8000) -> Locator | None:
    """等待「收藏简历」弹窗（含分组列表）。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        marked = await page.evaluate(_COLLECT_FOLDER_MODAL_JS)
        if marked and marked.get("ok"):
            preview = marked.get("preview") or ""
            if preview:
                _step_log(f"收藏简历弹窗已出现: {preview[:72]}…")
            modal = page.locator(f"[{_COLLECT_CARD_MARK}='1']").first
            try:
                if await modal.is_visible(timeout=800):
                    return modal
            except Exception:
                pass
        await page.wait_for_timeout(350)
    return None


async def _verify_collect_folder_clicked(page: Page) -> bool:
    """岗位文件夹点中后应出现「知道了」确认层（非「未分组的人选」列表页）。"""
    return bool(
        await page.evaluate(
            """() => {
                const isVisible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 12 && r.height > 12 && r.bottom > 0 && r.top < innerHeight
                        && s.visibility !== 'hidden' && s.display !== 'none'
                        && s.pointerEvents !== 'none';
                };
                for (const label of ['知道了', '我知道了']) {
                    for (const el of document.querySelectorAll('button, a, span, div')) {
                        if ((el.innerText || '').trim() !== label) continue;
                        if (!isVisible(el)) continue;
                        let root = el;
                        let blocked = false;
                        for (let i = 0; i < 12 && root; i++, root = root.parentElement) {
                            const t = (root.innerText || '').slice(0, 600);
                            if (t.includes('未分组的人选') || t.includes('分组列表')) {
                                blocked = true;
                                break;
                            }
                        }
                        if (!blocked) return true;
                    }
                }
                return false;
            }"""
        )
    )


async def _collect_modal_visible_texts(modal: Locator) -> list[str]:
    try:
        values = await modal.evaluate(
            r"""(root) => {
                const isVisible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width >= 12 && r.height >= 12 && r.bottom > 0 && r.top < innerHeight
                        && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const out = [];
                for (const el of root.querySelectorAll('li, a, button, div, span, label, p')) {
                    if (!isVisible(el)) continue;
                    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
                    if (text && text.length <= 80) out.push(text);
                }
                return [...new Set(out)].slice(0, 80);
            }"""
        )
    except Exception:
        return []
    return [str(item).strip() for item in values or [] if str(item).strip()]


async def _click_collect_folder_option(
    modal: Locator,
    page: Page,
    tag: str,
    *,
    expect_confirm: bool = True,
    action_context: str = "collect_folder",
) -> bool:
    """在分组列表中点击岗位名称文件夹整行，不点「未分组」「增加标签」等小项。"""
    import re

    label_patterns = [
        re.compile(rf"^{re.escape(tag)}$"),
        re.compile(rf"^{re.escape(tag)}[\(（]\d+[\)）]$"),
    ]

    async def _click_folder_row(row: Locator) -> bool:
        try:
            if not await row.is_visible(timeout=800):
                return False
            text = re.sub(r"\s+", " ", (await row.inner_text() or "")).strip()
            if "未分组" in text:
                return False
            if not any(pattern.fullmatch(text) for pattern in label_patterns):
                return False
            if any(k in text for k in ("增加标签", "添加", "新建")):
                return False
            await row.scroll_into_view_if_needed()
            # 优先点 li/a 整行，避免坐标偏移点到「未分组的人选」
            row_target = row.locator("xpath=ancestor::li[1] | ancestor::a[1] | ancestor::button[1]")
            if await row_target.count() > 0:
                await row_target.first.click(timeout=5000)
            else:
                await row.click(timeout=5000)
            await page.wait_for_timeout(600)
            if not expect_confirm:
                return await _is_collect_folder_modal_open(page)
            if await _verify_collect_folder_clicked(page):
                return True
            if await row_target.count() > 0:
                await row_target.first.click(timeout=5000)
            else:
                await row.click(timeout=5000)
            await page.wait_for_timeout(500)
            return await _verify_collect_folder_clicked(page)
        except Exception:
            return False

    async def _click_inferred_text(target_text: str) -> bool:
        try:
            locs = modal.get_by_text(re.compile(rf"^{re.escape(target_text)}$"))
            count = await locs.count()
            for i in range(count):
                row = locs.nth(i)
                if not await row.is_visible(timeout=800):
                    continue
                text = re.sub(r"\s+", " ", (await row.inner_text() or "")).strip()
                if not text or any(k in text for k in ("未分组", "增加标签", "添加标签", "新建标签", "新增标签", "全部收藏")):
                    continue
                await row.scroll_into_view_if_needed()
                row_target = row.locator("xpath=ancestor::li[1] | ancestor::a[1] | ancestor::button[1]")
                target = row_target.first if await row_target.count() > 0 else row
                await target.click(timeout=5000)
                await page.wait_for_timeout(600)
                if not expect_confirm:
                    return await _is_collect_folder_modal_open(page)
                if await _verify_collect_folder_clicked(page):
                    return True
        except Exception:
            return False
        return False

    for _ in range(3):
        # 1. 精确匹配岗位文件夹名称（含数量后缀如 岗位名(6)）
        for pattern in label_patterns:
            try:
                exact = modal.get_by_text(pattern)
                count = await exact.count()
                for i in range(count):
                    if await _click_folder_row(exact.nth(i)):
                        return True
            except Exception:
                pass

        # 2. 在弹窗内找最小可见行节点（排除增加标签）
        target = await modal.evaluate(
            r"""(root, tag) => {
                const escaped = tag.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const exact = new RegExp('^' + escaped + '$');
                const counted = new RegExp('^' + escaped + '[\\(（]\\d+[\\)）]$');
                const bad = /未分组|增加标签|添加标签|新建标签|新增标签|全部收藏/;
                const isVisible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width >= 48 && r.height >= 18 && r.bottom > 0 && r.top < innerHeight
                        && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const pickClickTarget = (el) => {
                    let node = el;
                    for (let i = 0; i < 8 && node; i++) {
                        const tagName = (node.tagName || '').toLowerCase();
                        if (tagName === 'li' || tagName === 'a' || tagName === 'button') return node;
                        node = node.parentElement;
                    }
                    return el;
                };
                const nodes = [...root.querySelectorAll('li, a, button, div, span, label, p')];
                const hits = nodes.filter(el => {
                    if (!isVisible(el)) return false;
                    const t = (el.innerText || '').trim();
                    if ((!exact.test(t) && !counted.test(t)) || bad.test(t)) return false;
                    return true;
                });
                if (!hits.length) return null;
                hits.sort((a, b) => {
                    const ta = (a.innerText || '').trim().length;
                    const tb = (b.innerText || '').trim().length;
                    return ta - tb;
                });
                const el = pickClickTarget(hits[0]);
                el.scrollIntoView({ block: 'center' });
                el.click();
                return { text: (hits[0].innerText || '').trim() };
            }""",
            tag,
        )
        if target and target.get("text"):
            _step_log(f"点击岗位文件夹行「{target['text']}」…")
            await page.wait_for_timeout(600)
            if not expect_confirm:
                return await _is_collect_folder_modal_open(page)
            if await _verify_collect_folder_clicked(page):
                return True

        visible_texts = await _collect_modal_visible_texts(modal)
        inferred = infer_ui_target(
            desired_label=tag,
            visible_texts=visible_texts,
            action_context=action_context,
        )
        _step_log(
            "岗位文件夹推断："
            f"desired={tag}, action={inferred.action}, "
            f"target={inferred.target_text}, confidence={inferred.confidence:.2f}"
        )
        if inferred.action == "click" and inferred.target_text:
            if await _click_inferred_text(inferred.target_text):
                return True

        await page.wait_for_timeout(400)

    return False


async def _is_collect_folder_modal_open(page: Page) -> bool:
    try:
        modal = page.locator(f"[{_COLLECT_CARD_MARK}='1']").first
        return await modal.is_visible(timeout=300)
    except Exception:
        return False


async def _clear_collect_panel_mark(page: Page) -> None:
    await page.evaluate(
        f"""() => {{
            document.querySelectorAll('[{_COLLECT_CARD_MARK}]').forEach(el => el.removeAttribute('{_COLLECT_CARD_MARK}'));
        }}"""
    )


async def _click_decision_collect_tag(
    resume_popup: Locator,
    page: Page,
    decision: str,
    collect_group: CollectGroupConfig | None = None,
    *,
    job_title: str | None = None,
) -> bool:
    """「收藏简历」弹窗：点击岗位名称文件夹（观察/追问仅写入 metadata）。"""
    group = collect_group or CollectGroupConfig.from_values(
        observe_label="\u89c2\u5bdf",
        followup_label="\u8ffd\u95ee",
    )
    tag = group.collect_folder_tag(job_title=job_title)
    if not tag:
        _step_fail("未配置岗位名称，无法在「收藏简历」弹窗中选择岗位文件夹")
        await _save_debug_screenshot(page, "collect_folder_job_missing")
        return False
    action_context = "collect_job_folder"

    modal = await _wait_collect_folder_modal(page, timeout_ms=1500)
    if modal is None:
        await _clear_collect_panel_mark(page)
        modal = await _wait_collect_folder_modal(page, timeout_ms=8000)
    if modal is None:
        _step_fail("点击收藏后未出现「收藏简历」弹窗")
        await _save_debug_screenshot(page, "collect_folder_modal_missing")
        return False

    if await _click_collect_folder_option(
        modal,
        page,
        tag,
        action_context=action_context,
    ):
        _step_log(f"已点击岗位文件夹「{tag}」")
        await page.wait_for_timeout(400)
        await _clear_collect_panel_mark(page)
        return True

    _step_fail(f"岗位文件夹「{tag}」点击未生效（未出现「知道了」确认弹窗）")
    await _save_debug_screenshot(page, f"collect_folder_{tag}_miss")
    return False


async def _wait_and_click_collect_confirm(page: Page, *, timeout_ms: int = 10000) -> bool:
    """选定岗位文件夹后，等待确认浮层并点击「知道了」。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if await _click_text_control(page, ("知道了", "我知道了"), exact=True):
            return True

        clicked = await page.evaluate(
            f"""() => {{
                const isVisible = (el) => {{
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 12 && r.height > 12 && r.bottom > 0 && r.top < innerHeight
                        && s.visibility !== 'hidden' && s.display !== 'none'
                        && s.pointerEvents !== 'none';
                }};
                const labels = ['知道了', '我知道了'];
                const inFolderPicker = (el) => {{
                    let p = el;
                    for (let i = 0; i < 12 && p; i++, p = p.parentElement) {{
                        const t = (p.innerText || '').slice(0, 400);
                        if (t.includes('收藏简历') && t.includes('分组列表')) return true;
                    }}
                    return false;
                }};
                const getNodes = {_TOPMOST_OVERLAY_JS};
                const overlays = getNodes('{_TOP_OVERLAY_MARK}');
                for (const root of overlays) {{
                    const summary = (root.innerText || '').slice(0, 400);
                    if (summary.includes('收藏简历') && summary.includes('分组列表')) continue;
                    const nodes = [...root.querySelectorAll('button, a, span, div')];
                    for (const el of nodes.reverse()) {{
                        const t = (el.innerText || '').trim();
                        if (!labels.includes(t) || !isVisible(el)) continue;
                        if (inFolderPicker(el)) continue;
                        el.click();
                        return true;
                    }}
                }}
                const nodes = [...document.querySelectorAll('button, a, span, div')];
                for (const el of nodes.reverse()) {{
                    const t = (el.innerText || '').trim();
                    if (!labels.includes(t) || !isVisible(el)) continue;
                    if (inFolderPicker(el)) continue;
                    el.click();
                    return true;
                }}
                return false;
            }}"""
        )
        if clicked:
            return True

        await page.wait_for_timeout(350)
    return False


async def _click_collect_got_it(resume_popup: Locator, page: Page) -> bool:
    """点击「知道了」完成收藏。"""
    if await _wait_and_click_collect_confirm(page, timeout_ms=3000):
        return True
    return await _click_text_control(resume_popup, ("知道了", "我知道了"), exact=True)


async def _click_text_control(
    scope: Locator | Page,
    labels: tuple[str, ...],
    *,
    exact: bool = True,
) -> bool:
    """在 scope 内点击可见的文案按钮/标签。"""
    for label in labels:
        try:
            locs = scope.locator(
                f"button:has-text('{label}'), a:has-text('{label}'), "
                f"span:has-text('{label}'), div:has-text('{label}'), label:has-text('{label}')"
            )
            count = await locs.count()
            for i in range(count - 1, -1, -1):
                el = locs.nth(i)
                if not await el.is_visible(timeout=1200):
                    continue
                text = (await el.inner_text() or "").strip()
                if exact and text != label:
                    continue
                await el.scroll_into_view_if_needed()
                try:
                    await el.click(timeout=5000)
                except Exception:
                    await el.click(timeout=5000, force=True)
                await el.page.wait_for_timeout(300)
                return True
        except Exception:
            continue
    return False


async def _click_collect_favorite(resume_popup: Locator, page: Page) -> bool:
    """点击「收藏」并确认「收藏简历」弹窗出现。"""
    if await _wait_collect_folder_modal(page, timeout_ms=600):
        return True

    async def _try_click(el: Locator) -> bool:
        try:
            if not await el.is_visible(timeout=800):
                return False
            text = re.sub(r"\s+", " ", (await el.inner_text() or "")).strip()
            if "已收藏" in text and text != "收藏" and "收藏" not in text:
                return False
            await el.scroll_into_view_if_needed()
            box = await el.bounding_box()
            if not box:
                return False
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            try:
                await el.click(timeout=4000)
            except Exception:
                try:
                    await el.click(timeout=4000, force=True)
                except Exception:
                    await page.mouse.click(cx, cy)
            await page.wait_for_timeout(700)
            return await _wait_collect_folder_modal(page, timeout_ms=2500) is not None
        except Exception:
            return False

    scopes: list[Locator | Page] = [resume_popup, page]
    for _ in range(4):
        for scope in scopes:
            for sel in LPT_COLLECT_BUTTONS:
                try:
                    locs = scope.locator(sel)
                    count = await locs.count()
                    for i in range(count - 1, -1, -1):
                        el = locs.nth(i)
                        text = re.sub(r"\s+", " ", (await el.inner_text() or "")).strip()
                        if text and "收藏" not in text and "已收藏" not in text:
                            continue
                        if await _try_click(el):
                            return True
                except Exception:
                    continue
        await page.wait_for_timeout(400)

    await _save_debug_screenshot(page, "collect_button_miss")
    return False


async def _complete_chat_collect_flow(
    page: Page,
    resume_popup: Locator,
    decision: str,
    collect_group: CollectGroupConfig | None = None,
    *,
    job_title: str | None = None,
) -> bool:
    """在在线简历弹窗内：收藏 → 点岗位文件夹 → 点「知道了」确认。"""
    group = collect_group or CollectGroupConfig()
    folder_tag = group.collect_folder_tag(job_title=job_title)
    _step_log("在简历弹窗内点击「收藏」…")
    if not await _click_collect_favorite(resume_popup, page):
        _step_fail("简历弹窗内未找到「收藏」或收藏简历弹窗未打开")
        return False
    _step_done("已点击收藏，收藏简历弹窗已打开")
    await page.wait_for_timeout(500)

    _step_log(f"在收藏简历弹窗中点击岗位文件夹「{folder_tag or '（未配置）'}」…")
    if not await _click_decision_collect_tag(
        resume_popup, page, decision, collect_group, job_title=job_title
    ):
        _step_fail(f"未在「收藏简历」弹窗中点击岗位文件夹「{folder_tag}」")
        return False
    _step_done(f"已点击岗位文件夹「{folder_tag}」")

    _step_log("等待收藏确认弹窗，点击「知道了」…")
    if not await _wait_and_click_collect_confirm(page):
        _step_fail("选定岗位文件夹后未找到「知道了」确认按钮")
        await _save_debug_screenshot(page, "collect_confirm_got_it_missing")
        return False
    _step_done("已点击「知道了」，收藏完成")
    await page.wait_for_timeout(500)
    await _clear_collect_panel_mark(page)
    return True


async def _click_communicate_in_popup(
    page: Page,
    resume_popup: Locator,
    *,
    job_title: str | None = None,
    workflow_id: str | None = None,
) -> bool:
    """在在线简历弹窗内点击「立即沟通」，并处理同页岗位浮层。"""
    await _clear_collect_panel_mark(page)
    await page.wait_for_timeout(600)

    deadline = time.time() + 10
    while time.time() < deadline:
        resume_popup = await _resolve_online_resume_popup(page, resume_popup)
        if resume_popup is not None:
            try:
                await resume_popup.evaluate(
                    """(root) => {
                        root.scrollTop = root.scrollHeight;
                        const bar = root.querySelector(
                            'footer, [class*="footer"], [class*="Footer"], [class*="toolbar"], [class*="Toolbar"], [class*="action"], [class*="Action"]'
                        );
                        if (bar) bar.scrollIntoView({ block: 'nearest' });
                    }"""
                )
            except Exception:
                pass

            clicked = await _click_chat_button_in_scope(resume_popup)
            if not clicked:
                clicked = await resume_popup.evaluate(
                    """(root) => {
                        const labels = ['立即沟通', '继续沟通', '立即开聊'];
                        const nodes = [...root.querySelectorAll('button, a, span, div')];
                        const hits = nodes.filter(el => {
                            const t = (el.innerText || '').trim();
                            return labels.some(l => t === l || t.includes(l));
                        });
                        if (!hits.length) return false;
                        const prefer = hits.find(el => (el.innerText || '').trim().includes('立即沟通'))
                            || hits.find(el => (el.innerText || '').trim().includes('继续沟通'))
                            || hits[hits.length - 1];
                        prefer.click();
                        return true;
                    }"""
                )
            if clicked:
                _step_log("已在简历弹窗内点击「立即沟通」…")
                await page.wait_for_timeout(900)
                if await _is_job_select_popup_visible(page):
                    _step_log("岗位浮层出现，在页内选岗确认（不跳转）…")
                    job_ok = await _handle_job_select_popup(
                        page, job_title=job_title, workflow_id=workflow_id
                    )
                    if await _is_job_select_popup_visible(page):
                        _step_fail("岗位选择浮层未关闭")
                        return False
                    if not job_ok:
                        _step_fail("开聊职位选择或确认未完成")
                        return False
                    _step_done("开聊职位已选并确认")
                else:
                    _step_log("无岗位选择浮层，沟通已发起")
                return True

        for sel in LPT_POPUP_CONTAINER:
            try:
                loc = page.locator(sel).last
                if not await loc.is_visible(timeout=400):
                    continue
                if await _click_chat_button_in_scope(loc):
                    _step_log("已在简历浮层内点击「立即沟通」…")
                    await page.wait_for_timeout(900)
                    if await _is_job_select_popup_visible(page):
                        job_ok = await _handle_job_select_popup(
                            page, job_title=job_title, workflow_id=workflow_id
                        )
                        if not job_ok or await _is_job_select_popup_visible(page):
                            _step_fail("岗位选择浮层未关闭或未确认")
                            return False
                        _step_done("开聊职位已选并确认")
                    return True
            except Exception:
                continue

        clicked = await page.evaluate(
            """() => {
                const labels = ['立即沟通', '继续沟通', '立即开聊'];
                const isVisible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 20 && r.height > 16 && r.bottom > 0 && r.top < innerHeight
                        && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const nodes = [...document.querySelectorAll('button, a, span, div')];
                const hits = nodes.filter(el => {
                    if (!isVisible(el)) return false;
                    const t = (el.innerText || '').trim();
                    return labels.some(l => t === l || t.includes(l));
                });
                if (!hits.length) return false;
                const prefer = hits.find(el => (el.innerText || '').trim().includes('立即沟通'))
                    || hits.find(el => (el.innerText || '').trim().includes('继续沟通'))
                    || hits[hits.length - 1];
                prefer.click();
                return true;
            }"""
        )
        if clicked:
            _step_log("已在页内底部操作栏点击「立即沟通」…")
            await page.wait_for_timeout(900)
            if await _is_job_select_popup_visible(page):
                job_ok = await _handle_job_select_popup(
                    page, job_title=job_title, workflow_id=workflow_id
                )
                if not job_ok or await _is_job_select_popup_visible(page):
                    _step_fail("岗位选择浮层未关闭或未确认")
                    return False
                _step_done("开聊职位已选并确认")
            return True

        await page.wait_for_timeout(400)

    _step_fail("简历弹窗内未找到「立即沟通/继续沟通」")
    await _save_debug_screenshot(page, "communicate_button_missing")
    return False


async def _click_contact_now(
    page: Page,
    popup: Locator | None = None,
    *,
    job_title: str | None = None,
    workflow_id: str | None = None,
    decision: str | None = None,
    collect_only: bool = False,
    collect_group: CollectGroupConfig | None = None,
) -> ContactNowResult:
    """在线简历弹窗内：先收藏至岗位文件夹 → 再立即沟通（仅收藏模式则跳过沟通）。"""
    resume_popup = await _resolve_online_resume_popup(page, popup)
    if resume_popup is None:
        _step_fail("在线简历弹窗不可见")
        return ContactNowResult(False)

    if decision in ("观察", "追问"):
        if not await _complete_chat_collect_flow(
            page, resume_popup, decision, collect_group, job_title=job_title
        ):
            return ContactNowResult(False)
        if collect_only:
            return ContactNowResult(True)
        resume_popup = await _resolve_online_resume_popup(page, resume_popup)
        if resume_popup is None:
            _step_fail("收藏完成后在线简历弹窗丢失")
            return ContactNowResult(False)
        if await _detect_resume_communicate_state(resume_popup) == "prior":
            _step_log("猎聘显示「继续沟通」，此前已沟通过，跳过重复开聊")
            return ContactNowResult(True, prior_communication=True)

    contacted = await _click_communicate_in_popup(
        page,
        resume_popup,
        job_title=job_title,
        workflow_id=workflow_id,
    )
    return ContactNowResult(contacted)


def _print_card_report(
    index: int,
    name: str | None,
    decision: str,
    visa,
    screening,
) -> None:
    from services.agent_service.screening_display import format_screening_flag_text

    detail = screening.score_detail if screening else {}
    reason = (visa.reason if visa else None) or detail.get("reason") or "—"
    summary = (visa.resume_summary if visa else None) or detail.get("resume_summary") or "—"
    criteria_analysis = (visa.criteria_analysis if visa else None) or detail.get("criteria_analysis") or ""
    flag_text = format_screening_flag_text(
        criteria_analysis=criteria_analysis,
        legacy=visa,
    )
    flag_suffix = f"  ({flag_text})" if flag_text else ""

    print(f"\n{'=' * 60}", flush=True)
    print(f"  卡片 #{index + 1}  {name or '未知候选人'}", flush=True)
    print(f"  >>> 决定: 【{decision}】{flag_suffix}", flush=True)
    print(f"{'-' * 60}", flush=True)
    print("  【在线简历总结】", flush=True)
    for line in summary.split("\n"):
        if line.strip():
            print(f"    {line.strip()}", flush=True)
    print(f"{'-' * 60}", flush=True)
    print("  【AI 判断依据】", flush=True)
    print(f"    {reason}", flush=True)
    if decision == "追问" and screening and screening.missing_info:
        print(f"  【追问】 {screening.missing_info[0].question}", flush=True)
    print(f"{'=' * 60}\n", flush=True)
    sys.stdout.flush()


def _candidate_fingerprint(detail: dict) -> str:
    stable = candidate_identity_hash(
        display_name=detail.get("display_name"),
        raw_text=detail.get("raw_text"),
        fallback_parts=(
            detail.get("education"),
            detail.get("city"),
            detail.get("work_years"),
            detail.get("current_title"),
        ),
    )
    if stable:
        return stable
    key = "|".join([
        detail.get("display_name") or "",
        detail.get("current_title") or "",
    ])
    return hashlib.md5(key.encode()).hexdigest()


async def _extract_from_popup_scope(popup: Locator) -> dict:
    await scroll_to_load(popup)
    await expand_all_sections(popup)

    # 等待展开后内容稳定
    deadline = time.monotonic() + 15
    last_len = 0
    stable_count = 0
    while time.monotonic() < deadline:
        raw_text = await popup.inner_text()
        cur_len = len(raw_text.strip())
        if cur_len > 100 and cur_len == last_len:
            stable_count += 1
            if stable_count >= 3:
                break
        else:
            stable_count = 0
        last_len = cur_len
        await popup.page.wait_for_timeout(500)
    else:
        raw_text = await popup.inner_text()

    if len(raw_text.strip()) < 50:
        raise RuntimeError("弹窗简历内容过短，抽取未完成")

    sections: dict[str, str | None] = {}
    for title in LPT_SECTION_TITLES:
        content = None
        try:
            title_loc = popup.get_by_text(title, exact=False).first
            if await title_loc.is_visible(timeout=1000):
                parent = title_loc.locator("xpath=ancestor::div[1]")
                content = (await parent.inner_text()).replace(title, "", 1).strip()
        except Exception:
            pass
        sections[title] = content

    from services.fetch_worker.im_contact_match import is_likely_company_name, is_likely_person_name

    name = None
    for sel in ["h1", "h2", "[class*='name']", "[class*='user-name']"]:
        try:
            loc = popup.locator(sel).first
            if await loc.is_visible(timeout=500):
                candidate = (await loc.inner_text()).strip()
                if candidate and is_likely_person_name(candidate):
                    name = candidate
                    break
                if candidate and not is_likely_company_name(candidate) and len(candidate) < 10:
                    name = candidate
                    break
        except Exception:
            continue

    experience = sections.get("工作经历")
    education_text = sections.get("教育经历")
    summary = sections.get("个人优势") or sections.get("自我评价")
    skills_text = sections.get("技能标签") or sections.get("语言能力") or ""

    skills = _parse_skills(raw_text + " " + skills_text)
    for kw in ["西班牙语", "美签", "海外销售", "英语", "销售"]:
        if kw in raw_text and kw not in skills:
            skills.append(kw)

    missing_fields = [k for k, v in sections.items() if not v and k in LPT_SECTION_TITLES[:4]]
    if not experience:
        missing_fields.append("experience_summary")

    filled = sum(1 for v in sections.values() if v)
    confidence = round(filled / max(len(LPT_SECTION_TITLES), 1), 2)

    current_title = None
    if experience:
        lines = [line.strip() for line in experience.split("\n") if line.strip()]
        if lines:
            current_title = lines[0][:100]

    return {
        "display_name": name,
        "current_title": current_title,
        "current_company": None,
        "work_years": _parse_work_years(raw_text),
        "education": _parse_education(raw_text) or (education_text[:50] if education_text else None),
        "city": _parse_city_from_text(raw_text),
        "skills": skills,
        "summary": summary,
        "experience_summary": experience,
        "project_summary": sections.get("项目经历"),
        "raw_text": raw_text[:50000],
        "extraction_confidence": max(confidence, 0.3 if raw_text else 0.0),
        "missing_fields": missing_fields,
        "template_type": "liepin_lpt_popup_v1",
        "sections": sections,
    }


def _parse_city_from_text(text: str) -> str | None:
    for city in ["深圳", "北京", "上海", "广州", "杭州", "成都"]:
        if city in text:
            return city
    return None


async def _mark_collect_only(
    snap_id: str,
    decision: str,
    collect_group: CollectGroupConfig | None = None,
) -> None:
    """仅收藏模式：写入岗位文件夹与判定 metadata，不标记 chat_initiated。"""
    from packages.db.repositories import CandidateRepository
    from packages.db.session import async_session_factory
    from packages.db.sqlite_guard import run_sqlite_write

    now_cn = datetime.now(timezone(timedelta(hours=8)))
    meta_patch: dict = {
        "collect_only": True,
        "collected_at": now_cn.strftime("%Y-%m-%d %H:%M"),
    }
    meta_patch.update(build_collect_metadata_patch(decision, collect_group))
    if decision == "追问":
        meta_patch["conversation_type"] = "followup"
    elif decision == "观察":
        meta_patch["conversation_type"] = "observe"

    async def _write() -> None:
        async with async_session_factory() as session:
            repo = CandidateRepository(session)
            await repo.patch_metadata(snap_id, meta_patch)
            await session.commit()

    await run_sqlite_write(_write)


async def _mark_chat_initiated(
    snap_id: str,
    decision: str,
    collect_group: CollectGroupConfig | None = None,
    *,
    prior_communication: bool = False,
) -> None:
    """开聊成功后写入 metadata；观察/追问均须开聊后才会出现在 IM「我发起的」。"""
    from packages.db.repositories import CandidateRepository
    from packages.db.session import async_session_factory
    from packages.db.sqlite_guard import run_sqlite_write

    now_cn = datetime.now(timezone(timedelta(hours=8)))
    meta_patch: dict = {
        "chat_initiated": True,
        "chat_initiated_at": now_cn.isoformat(),
        "collected_at": now_cn.strftime("%Y-%m-%d %H:%M"),
    }
    if prior_communication:
        meta_patch["prior_communication"] = True
    meta_patch.update(build_collect_metadata_patch(decision, collect_group))
    if decision == "追问":
        meta_patch["followup_pending"] = True
        meta_patch["conversation_type"] = "followup"
    elif decision == "观察":
        meta_patch["conversation_type"] = "observe"

    async def _write() -> None:
        async with async_session_factory() as session:
            repo = CandidateRepository(session)
            await repo.patch_metadata(snap_id, meta_patch)
            await session.commit()

    await run_sqlite_write(_write)


def _report_card_im_outreach(index: int, label: str, im_result: dict | None) -> None:
    """区分 IM 已发送、人工确认草稿、真实失败与跳过。"""
    if im_result and (im_result.get("send") or {}).get("ok"):
        _step_done(f"#{index + 1} IM {label}已发送")
    elif im_result and im_result.get("review_pending"):
        action = im_result.get("action") or label
        _step_done(f"#{index + 1} 已完成开聊，IM {action}草稿待人工确认")
    elif im_result:
        err = (im_result.get("send") or {}).get("error") or "发送失败"
        _step_fail(f"#{index + 1} IM {label}发送失败: {err}")
    else:
        _step_log(f"#{index + 1} IM {label}跳过（未生成草稿）")


async def _process_one_card(
    page: Page,
    card: Locator,
    index: int,
    workflow_id: str,
    platform: str,
    *,
    job_id: str | None,
    job_title: str | None = None,
    auto_screen: bool,
    seen_candidate_fps: set[str],
    screening_criteria: str = "",
    collect_only: bool = False,
    im_review_required: bool = False,
    collect_group: CollectGroupConfig | None = None,
) -> tuple[CandidateSnapshotData | None, str | None, dict[str, str] | None, str | None]:
    """线性处理单张卡片，任一步未确认则返回错误，不进入下一步。"""
    from packages.workflow_control import wait_if_paused

    await wait_if_paused(workflow_id)
    preview = await _extract_card_preview(page, card)
    card_name = preview.get("display_name") or f"card_{index}"

    _step_log(f"#{index + 1} 点击卡片「{card_name}」，等待弹窗...")
    await card.scroll_into_view_if_needed()
    box = await card.bounding_box()
    if box:
        await card.click(
            position={"x": box["width"] * 0.5, "y": min(box["height"] * 0.4, 80)},
            timeout=STEP_TIMEOUT_MS,
        )
    else:
        await card.click(timeout=STEP_TIMEOUT_MS)

    popup = await _wait_popup_open(page)
    if popup is None:
        _step_fail(f"#{index + 1} 弹窗未在 {POPUP_WAIT_MS / 1000:.0f}s 内打开，停止本卡片")
        await _ensure_back_to_list(page, workflow_id=workflow_id)
        return None, None, {"candidate": card_name, "error": "弹窗打开超时"}, None

    _step_done(f"#{index + 1} 弹窗已打开")

    _step_log(f"#{index + 1} 抽取在线简历，等待内容稳定...")
    try:
        detail = await _extract_from_popup_scope(popup)
    except Exception as e:
        _step_fail(f"#{index + 1} 简历抽取失败: {e}")
        await _save_debug_screenshot(page, f"extract_fail_{index}")
        await _ensure_back_to_list(page, workflow_id=workflow_id)
        return None, None, {"candidate": card_name, "error": str(e)}, None

    from services.fetch_worker.im_contact_match import (
        extract_person_name_from_text,
        is_likely_person_name,
        resolve_person_name,
    )

    card_text = preview.get("card_text") or ""
    person_name = extract_person_name_from_text(card_text)
    if not person_name:
        person_name = resolve_person_name(detail.get("display_name"), lines=card_text)
    if person_name and is_likely_person_name(person_name):
        detail["display_name"] = person_name
    else:
        detail["display_name"] = person_name
    card_name = person_name
    from services.fetch_worker.im_contact_match import parse_age_from_text, parse_school_from_text

    person_surname = None
    try:
        from services.fetch_worker.im_contact_match import im_match_surname

        person_surname = im_match_surname(person_name or card_name)
    except Exception:
        pass

    card_age = preview.get("card_age") or parse_age_from_text(detail.get("raw_text", ""))
    card_school = preview.get("card_school") or parse_school_from_text(detail.get("raw_text", ""))
    from services.fetch_worker.resume_library_row_match import parse_gender_from_text

    raw_for_meta = detail.get("raw_text", "") or preview.get("card_text") or ""
    gender = parse_gender_from_text(raw_for_meta)

    _step_done(f"#{index + 1} 简历抽取完成（{len(detail.get('raw_text', ''))} 字）")

    cand_fp = _candidate_fingerprint(detail)
    if cand_fp in seen_candidate_fps:
        _step_log(f"#{index + 1} 重复候选人「{detail.get('display_name') or card_name}」，关闭弹窗跳过")
        await _ensure_back_to_list(page, workflow_id=workflow_id)
        return None, None, None, None

    seen_candidate_fps.add(cand_fp)

    snap = CandidateSnapshotData(
        workflow_id=workflow_id,
        platform=platform,
        source_candidate_id=f"lpt_{workflow_id}_{index}",
        display_name=detail.get("display_name"),
        current_title=detail.get("current_title"),
        current_company=None,
        work_years=detail.get("work_years"),
        education=detail.get("education"),
        city=detail.get("city"),
        skills=detail.get("skills", []),
        summary=detail.get("summary"),
        experience_summary=detail.get("experience_summary"),
        project_summary=detail.get("project_summary"),
        raw_text=detail.get("raw_text", ""),
        extraction_confidence=detail.get("extraction_confidence", 0.0),
        missing_fields=detail.get("missing_fields", []),
        template_type=detail.get("template_type", "liepin_lpt_popup_v1"),
        metadata={
            "card_index": index,
            "sections": detail.get("sections", {}),
            "age": card_age,
            "card_age": card_age,
            "school": card_school,
            "card_school": card_school,
            "education_level": preview.get("education_level") or detail.get("education"),
            "person_name": detail.get("display_name"),
            "person_surname": person_surname,
            "card_name": card_name,
            "card_text": preview.get("card_text"),
            "gender": gender,
        },
    )

    if not auto_screen:
        _step_log(f"#{index + 1} 返回列表页...")
        if not await _ensure_back_to_list(page, min_exit_levels=1, workflow_id=workflow_id):
            _step_fail(f"#{index + 1} 未能回到列表页")
            return snap, None, {"candidate": card_name, "error": "未能回到搜索结果列表"}, cand_fp
        _step_done(f"#{index + 1} 已回到列表")
        return snap, None, None, cand_fp

    _step_log(f"#{index + 1} 等待 AI 初筛判断返回（最长 {AI_WAIT_MS / 1000:.0f}s）...")
    from services.agent_service.screening_service import visa_screen_and_persist_one

    try:
        snap_id, screening, decision, visa = await visa_screen_and_persist_one(
            snap, job_id=job_id, screening_criteria=screening_criteria
        )
    except Exception as e:
        _step_fail(f"#{index + 1} AI 判断失败: {e}")
        await _ensure_back_to_list(page, workflow_id=workflow_id)
        return None, None, {"candidate": card_name, "error": f"AI判断失败: {e}"}, cand_fp

    if visa is None or not visa.reason:
        _step_fail(f"#{index + 1} AI 未返回有效判断依据")
        await _ensure_back_to_list(page, workflow_id=workflow_id)
        return None, snap_id, {"candidate": card_name, "error": "AI未返回有效判断依据"}, cand_fp

    _step_done(f"#{index + 1} AI 已返回: 【{decision}】")
    _print_card_report(index, snap.display_name, decision, visa, screening)

    if decision in ("观察", "追问"):
        label = "观察" if decision == "观察" else "追问"
        folder_tag = collect_group.collect_folder_tag(job_title=job_title) if collect_group else ""
        folder_desc = f"岗位文件夹「{folder_tag}」" if folder_tag else "岗位文件夹"
        if collect_only:
            _step_log(
                f"#{index + 1} 判定{label}（仅收藏）：收藏 → 点{folder_desc} → 知道了，不开聊"
            )
        elif im_review_required:
            _step_log(
                f"#{index + 1} 判定{label}（人工确认）：收藏 → 点{folder_desc} → 知道了 → 立即开聊 → 生成 IM 草稿"
            )
        else:
            _step_log(
                f"#{index + 1} 判定{label}：收藏 → 点{folder_desc} → 知道了 → 立即沟通 → IM…"
            )
        contact_result = await _click_contact_now(
            page,
            popup,
            job_title=job_title,
            workflow_id=workflow_id,
            decision=decision,
            collect_only=collect_only,
            collect_group=collect_group,
        )
        if not contact_result.ok:
            err_msg = (
                "收藏流程未在超时内完成（岗位文件夹或确认弹窗）"
                if collect_only
                else "开聊或收藏流程未在超时内完成（岗位文件夹或确认弹窗）"
            )
            _step_fail(f"#{index + 1} {'收藏' if collect_only else '开聊/收藏'}未完成")
            await _ensure_back_to_list(page, min_exit_levels=2, workflow_id=workflow_id)
            return None, snap_id, {
                "candidate": snap.display_name or card_name,
                "error": err_msg,
            }, cand_fp
        if collect_only:
            await _mark_collect_only(snap_id, decision, collect_group)
            _step_done(f"#{index + 1} 已收藏至{folder_desc}（判定{label}，仅收藏模式）")
        elif contact_result.prior_communication:
            await _mark_chat_initiated(
                snap_id,
                decision,
                collect_group,
                prior_communication=True,
            )
            _step_done(
                f"#{index + 1} 已收藏至{folder_desc}（判定{label}，此前已沟通过，跳过重复开聊与 IM）"
            )
        else:
            await _mark_chat_initiated(snap_id, decision, collect_group)
            _step_done(f"#{index + 1} 已收藏至{folder_desc}并发起沟通（判定{label}）")
            _step_log(f"#{index + 1} 单次 IM {label}（本候选人流程未结束，不发下一张）…")
            from services.agent_service.im_autopilot import schedule_auto_im_outreach

            im_result = await schedule_auto_im_outreach(workflow_id, snap_id, decision)
            _report_card_im_outreach(index, label, im_result)
    else:
        _step_log(f"#{index + 1} 判定排除，跳过开聊")

    _step_log(f"#{index + 1} 连点退出回到列表页（至少两级）...")
    if not await _ensure_back_to_list(page, min_exit_levels=2, workflow_id=workflow_id):
        _step_fail(f"#{index + 1} 未能回到列表页（上方仍有浮层）")
        await _save_debug_screenshot(page, f"stuck_overlay_{index}")
        return None, snap_id, {"candidate": card_name, "error": "未能回到搜索结果列表"}, cand_fp
    _step_done(f"#{index + 1} 已回到列表，进入下一张")

    return None, snap_id, None, cand_fp


async def extract_from_popup_cards(
    page: Page,
    workflow_id: str,
    platform: str,
    target_count: int,
    *,
    job_id: str | None = None,
    job_title: str | None = None,
    job_description: str | None = None,
    screening_criteria: str = "",
    min_score: float = 60.0,
    auto_screen: bool = False,
    seen_candidate_fps: set[str] | None = None,
    collect_only: bool = False,
    im_review_required: bool = False,
    collect_parent_group: str = "",
) -> tuple[list[CandidateSnapshotData], list[dict[str, str]], list[str]]:
    """严格线性：每张卡片逐步确认后再处理下一张。"""
    snapshots: list[CandidateSnapshotData] = []
    saved_ids: list[str] = []
    failed_items: list[dict[str, str]] = []
    collect_folder = resolve_collect_folder_tag(
        parent_name=collect_parent_group,
    )
    collect_group = CollectGroupConfig.from_values(
        parent_name=collect_folder,
        observe_label="\u89c2\u5bdf",
        followup_label="\u8ffd\u95ee",
    )

    card_selector = await _find_card_selector(page)
    if not card_selector:
        await _save_debug_screenshot(page, "no_cards")
        failed_items.append({"error": "搜索结果页未找到简历卡片"})
        return snapshots, failed_items, saved_ids, False

    seen_card_fps: set[str] = set()
    if seen_candidate_fps is None:
        seen_candidate_fps = set()
    processed = 0
    cards_attempted = 0
    attempt = 0
    max_attempts = max(target_count * 8, 20)
    scroll_exhaust_streak = 0
    SCROLL_EXHAUST_LIMIT = 5
    list_exhausted = False

    print(f"\n开始线性处理，目标 {target_count} 张（去重后逐张点击）\n", flush=True)
    from packages.workflow_events import emit

    from services.fetch_worker.extract_monitor import ExtractStuckMonitor, capture_page_snapshot

    monitor = ExtractStuckMonitor()

    emit(
        "info",
        f"开始线性处理，目标 {target_count} 张简历（已启用调度监控）"
        + (f"，开聊岗位「{job_title}」" if job_title else "")
        + ("，仅收藏模式（不开聊、不发 IM）" if collect_only else "")
        + (
            "，人工确认 IM（仍立即开聊，只生成草稿）"
            if im_review_required and not collect_only
            else ""
        )
        + (
            "，已沟通过（继续沟通）跳过重复开聊与 IM"
            if not collect_only and not im_review_required
            else ""
        )
        + (
            f"，收藏至岗位文件夹「{collect_group.parent_name}」"
            if collect_group.parent_name
            else "，未配置岗位收藏文件夹"
        ),
        category="extract",
        meta={
            "target_count": target_count,
            "chat_job_title": job_title,
            "collect_only": collect_only,
            "im_review_required": im_review_required,
            "collect_parent_group": collect_group.parent_name,
        },
    )

    from packages.workflow_control import wait_if_paused

    while processed < target_count and attempt < max_attempts:
        attempt += 1
        await wait_if_paused(workflow_id)

        snap = await capture_page_snapshot(
            page,
            collect_cards=_collect_unique_resume_cards,
            has_blocking_overlay=_has_blocking_overlay,
            is_list_interactive=_is_list_interactive,
            is_job_select_visible=_is_job_select_popup_visible,
            is_popup_visible=_is_popup_visible,
        )
        stuck, reason = monitor.on_loop_start(processed, snap)
        if stuck and monitor.can_recover_again():
            recovered = await _force_recovery_to_list(
                page,
                reason,
                workflow_id=workflow_id,
                loop_attempt=attempt,
            )
            snap_after = await capture_page_snapshot(
                page,
                collect_cards=_collect_unique_resume_cards,
                has_blocking_overlay=_has_blocking_overlay,
                is_list_interactive=_is_list_interactive,
                is_job_select_visible=_is_job_select_popup_visible,
                is_popup_visible=_is_popup_visible,
            )
            monitor.on_recovery_done(snap_after)
            if not recovered:
                failed_items.append({"error": f"调度监控恢复失败: {reason}"})
                break
            continue

        card_infos = await _collect_unique_resume_cards(page)
        if not card_infos:
            _step_log("未找到可点击的顶层简历卡片，尝试滚动加载...")
            await page.mouse.wheel(0, 600)
            await page.wait_for_timeout(1200)
            continue

        picked: dict | None = None
        for info in card_infos:
            fp = _preview_fingerprint(info.get("text", ""))
            if fp not in seen_card_fps:
                picked = info
                break

        if not picked:
            scroll_exhaust_streak += 1
            _step_log("当前可见卡片均已处理，尝试翻页或向下滚动...")

            if processed < target_count:
                from services.fetch_worker.lpt_pagination import try_lpt_next_search_page

                if await try_lpt_next_search_page(page):
                    scroll_exhaust_streak = 0
                    msg = f"当前页已处理完（{len(card_infos)} 张），已翻页继续（已完成 {processed}/{target_count}）"
                    _step_log(msg)
                    emit(
                        "info",
                        msg,
                        category="extract",
                        meta={"pagination": True, "processed": processed, "target_count": target_count},
                    )
                    continue

            if scroll_exhaust_streak >= SCROLL_EXHAUST_LIMIT and processed < target_count:
                list_exhausted = True
                msg = (
                    f"当前搜索列表已耗尽（可见 {len(card_infos)} 张均已处理且无下一页，"
                    f"仅完成 {processed}/{target_count}），"
                    f"将先切换需求年限段（不超出设定区间），再考虑删减搜索关键词"
                )
                _step_log(msg)
                emit("warn", msg, category="extract", meta={"list_exhausted": True})
                break
            await page.mouse.wheel(0, 600)
            await page.wait_for_timeout(1200)
            continue

        scroll_exhaust_streak = 0

        card_fp = _preview_fingerprint(picked.get("text", ""))
        seen_card_fps.add(card_fp)

        card = page.locator(f"[{_CARD_MARK}='{picked['idx']}']").first
        try:
            if not await card.is_visible(timeout=5000):
                continue

            cards_attempted += 1
            snap, snap_id, err, _cand_fp = await _process_one_card(
                page,
                card,
                cards_attempted - 1,
                workflow_id,
                platform,
                job_id=job_id,
                job_title=job_title,
                auto_screen=auto_screen,
                seen_candidate_fps=seen_candidate_fps,
                screening_criteria=screening_criteria,
                collect_only=collect_only,
                im_review_required=im_review_required,
                collect_group=collect_group,
            )

            if err:
                failed_items.append(err)
                if not await _is_list_interactive(page):
                    await _force_recovery_to_list(
                        page,
                        "单卡处理失败后列表不可操作",
                        workflow_id=workflow_id,
                        loop_attempt=attempt,
                    )
                await page.wait_for_timeout(1000)
                continue

            if snap_id:
                saved_ids.append(snap_id)
                processed += 1
            elif snap:
                snapshots.append(snap)
                processed += 1

            await page.wait_for_timeout(800)

        except PlaywrightTimeout as e:
            failed_items.append({"candidate": f"card_{cards_attempted}", "error": f"超时: {e}"})
            _step_fail(f"#{cards_attempted} 超时: {e}")
            await _ensure_back_to_list(page, workflow_id=workflow_id)
        except Exception as e:
            failed_items.append({"candidate": f"card_{cards_attempted}", "error": str(e)})
            _step_fail(f"#{cards_attempted} 异常: {e}")
            await _ensure_back_to_list(page, workflow_id=workflow_id)

    print(f"\n线性处理结束: 成功 {processed} 张，失败 {len(failed_items)} 项\n", flush=True)
    emit(
        "success",
        f"线性处理结束: 成功 {processed} 张，失败 {len(failed_items)} 项",
        category="extract",
        meta={"processed": processed, "failed": len(failed_items), "list_exhausted": list_exhausted},
    )
    return snapshots, failed_items, saved_ids, list_exhausted
