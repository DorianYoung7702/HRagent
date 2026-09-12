"""猎聘 IM 中心：按 DB 候选人（姓名+年龄+学校）逐人对话。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from packages.workflow_control import wait_if_paused
from services.fetch_worker.browser_pool import new_page, release_browser
from services.fetch_worker.im_chat_adapter import (
    IM_CHAT_INPUT,
    IM_SEND_BUTTON,
    IM_TAB_INITIATED,
    IM_URL,
    build_im_contact_key,
)
from services.fetch_worker.im_contact_match import (
    IMContactMatchFields,
    im_match_label,
    match_contact_index,
)

logger = logging.getLogger(__name__)
DEBUG_DIR = Path("data/debug")

# 开聊后猎聘「我发起的」列表同步需要时间，匹配失败时轮询重试
INITIATED_LIST_RETRIES = 6
INITIATED_LIST_WAIT_MS = 2500

_IM_LIST_JS = """
() => {
    const isVisible = el => {
        const r = el.getBoundingClientRect();
        return r.width > 60 && r.height > 28 && r.top > 60 && r.top < innerHeight - 20;
    };
    const selectors = [
        '[class*="im-session"] [class*="item"]',
        '[class*="session-list"] [class*="item"]',
        '[class*="contact-list"] [class*="item"]',
        '[class*="chat-list"] li',
        '[class*="conversation-list"] > div',
        '[class*="list"] [class*="item"]',
    ];
    const seen = new Set();
    const nodes = [];
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (!isVisible(el)) continue;
            const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
            if (!t || t.length < 2 || seen.has(t)) continue;
            seen.add(t);
            nodes.push({ text: t.slice(0, 240), el });
        }
    }
    nodes.sort((a, b) => a.el.getBoundingClientRect().top - b.el.getBoundingClientRect().top);
    nodes.forEach((n, i) => n.el.setAttribute('data-hr-im-contact', String(i)));
    return nodes.map((n, i) => ({ idx: i, text: n.text }));
}
"""


@dataclass
class IMSendTarget:
    candidate_snapshot_id: str
    display_name: str | None
    message_text: str
    conversation_id: str | None = None
    age: str | None = None
    school: str | None = None
    education: str | None = None
    current_title: str | None = None
    chat_initiated_at: str | None = None

    def match_fields(self) -> IMContactMatchFields:
        return IMContactMatchFields(
            display_name=self.display_name,
            age=self.age,
            school=self.school,
            education=self.education,
            chat_initiated_at=self.chat_initiated_at,
        )

    def log_label(self) -> str:
        return im_match_label(self.display_name)


@dataclass
class IMInboundMessage:
    contact_text: str
    message_text: str
    matched_snapshot_id: str | None = None
    candidate_snapshot_id: str | None = None


def _step(msg: str, *, workflow_id: str | None = None) -> None:
    print(f"[IM] {msg}", flush=True)
    from packages.workflow_events import emit

    emit("info", msg, category="im_followup", workflow_id=workflow_id)


async def _save_debug(page: Page, name: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DEBUG_DIR / f"{name}_{ts}.png"
    try:
        await page.screenshot(path=str(path), full_page=True)
    except Exception as e:
        logger.warning("IM screenshot failed: %s", e)


async def _close_im_page(page: Page | None, *, workflow_id: str | None = None) -> None:
    """IM 流程结束关闭本流程打开的标签页，避免与抓取页叠 tab。"""
    if page is None:
        return
    try:
        if not page.is_closed():
            await page.close()
            _step("已关闭 IM 标签页", workflow_id=workflow_id)
    except Exception as e:
        logger.warning("IM page close failed: %s", e)


async def _click_text(page: Page, texts: list[str]) -> bool:
    for text in texts:
        try:
            loc = page.get_by_text(text, exact=False).first
            if await loc.is_visible(timeout=2500):
                await loc.click()
                await page.wait_for_timeout(600)
                return True
        except Exception:
            continue
    return False


async def navigate_to_im_center(page: Page, *, workflow_id: str | None = None) -> None:
    _step("打开 IM 中心…", workflow_id=workflow_id)
    await page.goto(IM_URL, wait_until="load", timeout=60_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        await page.wait_for_timeout(2000)
    await _click_text(page, ["沟通", "消息"])
    await page.wait_for_timeout(800)


async def click_initiated_tab(page: Page) -> bool:

    return await _click_text(page, IM_TAB_INITIATED)


async def _list_contact_texts(page: Page) -> list[tuple[int, str]]:
    items = await page.evaluate(_IM_LIST_JS)
    return [(int(it["idx"]), str(it["text"])) for it in (items or [])]


async def _click_contact_by_index(page: Page, index: int) -> bool:
    return bool(
        await page.evaluate(
            """(idx) => {
                const el = document.querySelector(`[data-hr-im-contact="${idx}"]`);
                if (!el) return false;
                el.click();
                return true;
            }""",
            index,
        )
    )


async def _fill_and_send(page: Page, message_text: str) -> bool:
    filled = False
    for sel in IM_CHAT_INPUT:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=2000):
                await loc.click()
                await loc.fill(message_text)
                filled = True
                break
        except Exception:
            continue
    if not filled:
        filled = bool(
            await page.evaluate(
                """(text) => {
                    const inputs = [...document.querySelectorAll('textarea, [contenteditable=true]')];
                    const pick = inputs.find(el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 100 && r.height > 20;
                    });
                    if (!pick) return false;
                    if (pick.tagName === 'TEXTAREA') {
                        pick.value = text;
                        pick.dispatchEvent(new Event('input', { bubbles: true }));
                    } else {
                        pick.innerText = text;
                    }
                    return true;
                }""",
                message_text,
            )
        )
    if not filled:
        return False

    await page.wait_for_timeout(400)
    for sel in IM_SEND_BUTTON:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500) and await btn.is_enabled():
                await btn.click()
                await page.wait_for_timeout(1000)
                return True
        except Exception:
            continue
    return await _click_text(page, ["发送"])


async def _verify_message_sent(page: Page, message_text: str) -> bool:
    snippet = (message_text or "").strip()[:24]
    if not snippet:
        return True
    found = await page.evaluate(
        """(snippet) => {
            const nodes = [...document.querySelectorAll('[class*="message"], [class*="msg"], [class*="chat-item"]')];
            return nodes.some(el => {
                const cls = String(el.className || '');
                const t = (el.innerText || '').trim();
                if (!t.includes(snippet)) return false;
                return cls.includes('self') || cls.includes('mine') || cls.includes('right') || cls.includes('send');
            });
        }""",
        snippet,
    )
    return bool(found)


async def _read_latest_inbound(page: Page) -> str:
    text = await page.evaluate(
        """() => {
            const bubbles = [...document.querySelectorAll(
                '[class*="message"], [class*="msg"], [class*="chat-item"]'
            )];
            const inbound = bubbles.filter(el => {
                const cls = String(el.className || '');
                const t = (el.innerText || '').trim();
                if (!t || t.length < 2) return false;
                if (cls.includes('self') || cls.includes('mine') || cls.includes('right')) return false;
                return cls.includes('other') || cls.includes('left') || cls.includes('receive');
            });
            if (inbound.length) return (inbound[inbound.length - 1].innerText || '').trim();
            const all = bubbles.map(el => (el.innerText || '').trim()).filter(t => t.length > 2);
            return all.length ? all[all.length - 1] : '';
        }"""
    )
    return (text or "").strip()


async def _open_matched_contact(
    page: Page,
    target: IMSendTarget,
    *,
    workflow_id: str | None,
    debug_tag: str,
) -> tuple[bool, str]:
    fields = target.match_fields()
    label = target.log_label()
    last_score = -1
    last_err = f"未在「我发起的」匹配: {label}"

    for attempt in range(INITIATED_LIST_RETRIES):
        if attempt > 0:
            _step(
                f"「我发起的」未找到 {label}，"
                f"等待列表出现该联系人后重试 ({attempt + 1}/{INITIATED_LIST_RETRIES})…",
                workflow_id=workflow_id,
            )
            await page.wait_for_timeout(INITIATED_LIST_WAIT_MS)
            await click_initiated_tab(page)

        contacts = await _list_contact_texts(page)
        idx, score, matched_text = match_contact_index(contacts, target.match_fields())
        last_score = score
        if idx is None:
            last_err = (
                f"未在「我发起的」匹配: {label} "
                f"(age={fields.age or '-'} school={fields.school or '-'}"
                f"{f' initiated={fields.chat_initiated_at[:16]}' if fields.chat_initiated_at else ''})"
            )
            continue
        if not await _click_contact_by_index(page, idx):
            return False, "点击列表项失败"
        await page.wait_for_timeout(800)
        if attempt > 0:
            _step(f"第 {attempt + 1} 次重试后在「我发起的」匹配成功", workflow_id=workflow_id)
        return True, matched_text

    await _save_debug(page, debug_tag)
    _step(f"未匹配: {label} score={last_score}", workflow_id=workflow_id)
    return False, last_err


async def run_im_send_batch(
    targets: list[IMSendTarget],
    *,
    workflow_id: str,
    browser_profile: str = "hr_default",
) -> list[dict]:
    """「我发起的」逐人发送：单次成功后再处理下一位；结束后关闭 IM 标签页。"""
    if not targets:
        _step("跳过 IM 发送：待发送 0 人", workflow_id=workflow_id)
        return []

    results: list[dict] = []
    page = await new_page(browser_profile)
    try:
        await navigate_to_im_center(page, workflow_id=workflow_id)
        if not await click_initiated_tab(page):
            await _save_debug(page, "im_tab_initiated_fail")
            raise RuntimeError("未能点击「我发起的」标签")

        contacts = await _list_contact_texts(page)
        _step(f"「我发起的」列表可见 {len(contacts)} 项", workflow_id=workflow_id)

        for i, target in enumerate(targets):
            await wait_if_paused(workflow_id)
            ok_open, detail = await _open_matched_contact(
                page, target, workflow_id=workflow_id, debug_tag=f"im_match_fail_{i}"
            )
            if not ok_open:
                results.append({
                    "candidate_snapshot_id": target.candidate_snapshot_id,
                    "ok": False,
                    "error": detail,
                })
                continue

            sent = await _fill_and_send(page, target.message_text)
            if not sent or not await _verify_message_sent(page, target.message_text):
                await _save_debug(page, f"im_send_fail_{i}")
                results.append({
                    "candidate_snapshot_id": target.candidate_snapshot_id,
                    "ok": False,
                    "error": "填入或发送失败",
                })
                continue

            _step(
                f"已发送给 {target.log_label() or target.candidate_snapshot_id} "
                f"({i + 1}/{len(targets)}) 匹配行: {detail[:60]}",
                workflow_id=workflow_id,
            )
            results.append({
                "candidate_snapshot_id": target.candidate_snapshot_id,
                "conversation_id": target.conversation_id,
                "ok": True,
                "im_contact_key": build_im_contact_key(
                    target.display_name,
                    age=target.age,
                    school=target.school,
                    education=target.education,
                    current_title=target.current_title,
                ),
                "matched_text": detail,
            })
            await page.wait_for_timeout(600)

        return results
    finally:
        await _close_im_page(page, workflow_id=workflow_id)
        await release_browser(browser_profile)


async def run_im_sync_replies_from_db(
    targets: list[IMSendTarget],
    *,
    workflow_id: str,
    browser_profile: str = "hr_default",
) -> list[IMInboundMessage]:
    """按 DB 会话清单在「我发起的」逐人打开并读取最新回复（不依赖未读筛选）。"""
    if not targets:
        _step(
            "跳过 IM 回复同步：待查 0 人（同步的是已发出追问/要简历的回复，与开聊是否回复无关）",
            workflow_id=workflow_id,
        )
        return []

    inbound: list[IMInboundMessage] = []
    page = await new_page(browser_profile)
    try:
        await navigate_to_im_center(page, workflow_id=workflow_id)
        if not await click_initiated_tab(page):
            raise RuntimeError("未能点击「我发起的」标签")

        contacts = await _list_contact_texts(page)
        _step(f"按 DB 同步回复，列表 {len(contacts)} 项，待查 {len(targets)} 人", workflow_id=workflow_id)

        for i, target in enumerate(targets):
            await wait_if_paused(workflow_id)
            ok_open, matched_text = await _open_matched_contact(
                page, target, workflow_id=workflow_id, debug_tag=f"im_reply_match_fail_{i}"
            )
            if not ok_open:
                continue
            msg = await _read_latest_inbound(page)
            if not msg:
                continue
            inbound.append(
                IMInboundMessage(
                    contact_text=matched_text,
                    message_text=msg,
                    matched_snapshot_id=target.candidate_snapshot_id,
                    candidate_snapshot_id=target.candidate_snapshot_id,
                )
            )
            _step(
                f"已读取 {target.log_label()} 的回复: {msg[:40]}…",
                workflow_id=workflow_id,
            )
            await page.wait_for_timeout(400)

        return inbound
    finally:
        await _close_im_page(page, workflow_id=workflow_id)
        await release_browser(browser_profile)


@dataclass
class SyncReplyOutcome:
    target: IMSendTarget
    inbound: IMInboundMessage | None = None
    error: str | None = None


async def run_im_sync_replies_serial(
    targets: list[IMSendTarget],
    *,
    workflow_id: str,
    browser_profile: str = "hr_default",
    stop_check: Callable[[], bool] | None = None,
) -> list[SyncReplyOutcome]:
    """单次浏览器会话内串行同步每位候选人的最新 IM 回复。"""
    if not targets:
        _step(
            "跳过 IM 回复同步：待查 0 人（同步的是已发出追问/要简历的回复，与开聊是否回复无关）",
            workflow_id=workflow_id,
        )
        return []

    outcomes: list[SyncReplyOutcome] = []
    page = await new_page(browser_profile)
    try:
        await navigate_to_im_center(page, workflow_id=workflow_id)
        if not await click_initiated_tab(page):
            raise RuntimeError("未能点击「我发起的」标签")

        contacts = await _list_contact_texts(page)
        _step(
            f"回复判定：列表 {len(contacts)} 项，串行待查 {len(targets)} 人",
            workflow_id=workflow_id,
        )

        for i, target in enumerate(targets):
            if stop_check and stop_check():
                break
            await wait_if_paused(workflow_id)
            ok_open, matched_text = await _open_matched_contact(
                page, target, workflow_id=workflow_id, debug_tag=f"im_reply_match_fail_{i}"
            )
            if not ok_open:
                outcomes.append(SyncReplyOutcome(target=target, error="未在「我发起的」匹配"))
                continue
            msg = await _read_latest_inbound(page)
            if not msg:
                outcomes.append(SyncReplyOutcome(target=target, error="暂无新回复"))
                continue
            inbound = IMInboundMessage(
                contact_text=matched_text,
                message_text=msg,
                matched_snapshot_id=target.candidate_snapshot_id,
                candidate_snapshot_id=target.candidate_snapshot_id,
            )
            outcomes.append(SyncReplyOutcome(target=target, inbound=inbound))
            _step(
                f"已读取 {target.log_label()} 的回复: {msg[:40]}… ({i + 1}/{len(targets)})",
                workflow_id=workflow_id,
            )
            await page.wait_for_timeout(400)

        return outcomes
    finally:
        await _close_im_page(page, workflow_id=workflow_id)
        await release_browser(browser_profile)


# 兼容旧名
async def run_im_unread_scan(
    known_contacts: list[dict],
    *,
    workflow_id: str,
    browser_profile: str = "hr_default",
) -> list[IMInboundMessage]:
    targets = [
        IMSendTarget(
            candidate_snapshot_id=kc["candidate_snapshot_id"],
            display_name=kc.get("display_name"),
            message_text="",
            age=kc.get("age"),
            school=kc.get("school"),
            education=kc.get("education"),
            current_title=kc.get("current_title"),
            chat_initiated_at=kc.get("chat_initiated_at"),
        )
        for kc in known_contacts
    ]
    return await run_im_sync_replies_from_db(
        targets, workflow_id=workflow_id, browser_profile=browser_profile
    )
