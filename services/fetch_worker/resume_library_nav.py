"""猎聘 LPT 简历库：人才管理 → 简历库 → 左侧点岗位文件夹 → 主页右侧整行匹配并点击。"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path

from playwright.async_api import Locator, Page

from services.fetch_worker.collect_grouping import infer_ui_target, is_decision_sidebar_label
from services.fetch_worker.extract_popup import _wait_popup_open
from services.fetch_worker.lpt_adapter import (
    LPT_POPUP_CLOSE,
    LPT_RESUME_LIBRARY_TOP_TAB,
    LPT_RESUME_LIBRARY_TOP_TAB_SELECTORS,
    LPT_SEARCH_URL,
    LPT_TALENT_MGMT_SIDEBAR,
)
from services.fetch_worker.resume_library_row_match import (
    ResumeLibraryMatchProfile,
    ResumeLibraryRow,
    FUZZY_FIELD_THRESHOLD,
    extract_name_from_row_text,
    find_resume_library_row,
    names_match,
    parse_row_from_cells,
    parse_row_from_full_text,
    parse_row_from_list_text,
    score_row_fields,
    validate_profile_for_library_match,
)

logger = logging.getLogger(__name__)
DEBUG_DIR = Path("data/debug")
_NAV_TIMEOUT_MS = 30_000
_LIST_READY_MS = 18_000
_MAX_LIST_PAGES = 40
_SIDEBAR_MAX_X_RATIO = 0.24
_TOP_TAB_MAX_Y_RATIO = 0.32
_TOP_TAB_MAX_LABEL_W = 140
_TOP_TAB_MAX_LABEL_H = 56
_PAGE_FOLDER_CACHE: dict[int, str] = {}
_FOLDER_PAGE_ROWS_CACHE: dict[tuple[int, str, int], list[ResumeLibraryRow]] = {}
_MATCH_RESULT_CACHE: dict[str, dict[str, object]] = {}

# 侧栏：人才管理
_CLICK_SIDEBAR_MENU_JS = f"""
(labels) => {{
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const leftMaxX = () => window.innerWidth * {_SIDEBAR_MAX_X_RATIO};
    const isVisible = (el) => {{
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width >= 28 && r.height >= 14 && r.bottom > 0 && r.top < innerHeight
            && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
    }};
    const pickClickTarget = (el) => {{
        let node = el;
        for (let i = 0; i < 8 && node; i++) {{
            const tag = (node.tagName || '').toLowerCase();
            if (tag === 'li' || tag === 'a' || tag === 'button' || node.getAttribute('role') === 'menuitem') {{
                return node;
            }}
            node = node.parentElement;
        }}
        return el;
    }};
    for (const label of labels) {{
        for (const el of document.querySelectorAll('a, button, span, div, li, [role="menuitem"]')) {{
            const t = norm(el.innerText);
            if (!t || t.length > 14 || t.includes('\\n')) continue;
            if (t !== label) continue;
            if (!isVisible(el)) continue;
            const r = el.getBoundingClientRect();
            if (r.x >= leftMaxX()) continue;
            const target = pickClickTarget(el);
            target.scrollIntoView({{ block: 'center' }});
            target.click();
            return {{ ok: true, text: t }};
        }}
    }}
    return {{ ok: false }};
}}
"""

# 人才管理展开后：点上方「简历库」子标签（短标签、页面上部，勿用侧栏 x 过滤误伤）
_CLICK_TOP_TAB_JS = f"""
(labels) => {{
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const topMaxY = () => window.innerHeight * {_TOP_TAB_MAX_Y_RATIO};
    const isVisible = (el) => {{
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width >= 20 && r.height >= 10 && r.bottom > 0 && r.top < innerHeight
            && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
    }};
    const pickClickTarget = (el) => {{
        let node = el;
        for (let i = 0; i < 8 && node; i++) {{
            const tag = (node.tagName || '').toLowerCase();
            const role = node.getAttribute('role') || '';
            if (tag === 'a' || tag === 'button' || tag === 'li' || role === 'tab') {{
                return node;
            }}
            node = node.parentElement;
        }}
        return el;
    }};
    const hits = [];
    for (const label of labels) {{
        for (const el of document.querySelectorAll('a, button, span, div, li, [role="tab"]')) {{
            const t = norm(el.innerText);
            if (t !== label) continue;
            if (!isVisible(el)) continue;
            const r = el.getBoundingClientRect();
            if (r.top > topMaxY()) continue;
            if (r.width > {_TOP_TAB_MAX_LABEL_W} || r.height > {_TOP_TAB_MAX_LABEL_H}) continue;
            hits.push({{ el, t, top: r.top, left: r.x, area: r.width * r.height }});
        }}
    }}
    if (!hits.length) return {{ ok: false, reason: 'no_hit' }};
    hits.sort((a, b) => a.top - b.top || a.left - b.left);
    const target = pickClickTarget(hits[0].el);
    target.scrollIntoView({{ block: 'center' }});
    target.click();
    return {{ ok: true, text: hits[0].t, top: hits[0].top, left: hits[0].left }};
}}
"""

_DEBUG_TOP_TABS_JS = f"""
(labels) => {{
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const topMaxY = () => window.innerHeight * {_TOP_TAB_MAX_Y_RATIO};
    const out = [];
    for (const label of labels) {{
        for (const el of document.querySelectorAll('a, button, span, div, li, [role="tab"]')) {{
            const t = norm(el.innerText);
            if (t !== label) continue;
            const r = el.getBoundingClientRect();
            out.push({{ text: t, top: Math.round(r.top), left: Math.round(r.x), w: Math.round(r.width), h: Math.round(r.height) }});
        }}
    }}
    return out.slice(0, 12);
}}
"""

# 点击左侧岗位文件夹：匹配岗位名(N)，排除「未分组」及观察/追问/候选初筛标签
_CLICK_FOLDER_TAB_JS = """(patterns) => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const leftMaxX = window.innerWidth * 0.38;
    const blockedText = (t) => /未分组|全部收藏|管理|分组列表|增加标签|^观察$|^追问$|^候选$|^observe$/i.test(t)
        || /^观察[\(（]\d+[\)）]$/.test(t)
        || /^追问[\(（]\d+[\)）]$/.test(t)
        || /^候选[\(（]\d+[\)）]$/.test(t)
        || /^followup[\(（]\d+[\)）]$/i.test(t)
        || /^observe[\(（]\d+[\)）]$/i.test(t);
    const isVisible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width >= 36 && r.height >= 14 && r.bottom > 0 && r.top < innerHeight
            && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
    };
    const matchOk = (t) => {
        if (!t || blockedText(t)) return false;
        for (const p of patterns) {
            try { if (new RegExp(p).test(t)) return true; } catch (e) {}
        }
        return false;
    };
    const pickClickTarget = (el) => {
        let node = el;
        for (let i = 0; i < 8 && node; i++) {
            const tag = (node.tagName || '').toLowerCase();
            if (tag === 'li' || tag === 'a' || tag === 'button' || node.getAttribute('role') === 'tab') {
                return node;
            }
            node = node.parentElement;
        }
        return el;
    };
    const hits = [];
    for (const el of document.querySelectorAll('li, a, button, div, span, label, p, [role="tab"]')) {
        const t = norm(el.innerText);
        if (!t || t.length > 14 || t.includes('\\n')) continue;
        if (!matchOk(t)) continue;
        if (!isVisible(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.x >= leftMaxX) continue;
        hits.push({ el, t, area: r.width * r.height, top: r.top });
    }
    if (!hits.length) return { ok: false };
    hits.sort((a, b) => a.area - b.area || a.top - b.top);
    const target = pickClickTarget(hits[0].el);
    target.scrollIntoView({ block: 'center' });
    target.click();
    return { ok: true, text: hits[0].t };
}"""

_VERIFY_FOLDER_TAB_JS = """(patterns) => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const leftMaxX = window.innerWidth * 0.38;
    const blockedText = (t) => /未分组|全部收藏/.test(t);
    const matchOk = (t) => {
        if (!t || blockedText(t)) return false;
        for (const p of patterns) {
            try { if (new RegExp(p).test(t)) return true; } catch (e) {}
        }
        return false;
    };
    const activeLike = (el) => {
        const s = getComputedStyle(el);
        const cls = (el.className || '').toString();
        if (/active|selected|current|checked|highlight/.test(cls)) return true;
        if (el.getAttribute('aria-selected') === 'true') return true;
        const bg = s.backgroundColor || '';
        return /244|247|255|219|234|254/.test(bg.replace(/\\s/g, ''));
    };
    const leftItems = [];
    for (const el of document.querySelectorAll('li, a, button, div, span, label, p, [role="tab"]')) {
        const t = norm(el.innerText);
        if (!t || t.length > 14 || t.includes('\\n')) continue;
        const r = el.getBoundingClientRect();
        if (r.x >= leftMaxX) continue;
        leftItems.push({ el, t });
    }
    for (const { el, t } of leftItems) {
        if (!matchOk(t)) continue;
        let node = el;
        for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
            if (activeLike(node)) return { ok: true, selected: t };
        }
    }
    for (const { el, t } of leftItems) {
        if (!blockedText(t)) continue;
        let node = el;
        for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
            if (activeLike(node)) return { ok: false, selected: t, reason: 'uncategorized_active' };
        }
    }
    return { ok: false, selected: '', reason: 'no_active_match' };
}"""

# 主页右侧：整行 list（姓名与其它字段在同一行；表格可能全宽，姓名列在右侧主区域）
_MAIN_PANEL_MIN_X_RATIO = 0.22

_MAIN_LIST_HELPERS_JS = f"""
    const mainMinX = () => window.innerWidth * {_MAIN_PANEL_MIN_X_RATIO};
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const nameInTextRe = /[\u4e00-\u9fff]{{1,2}}\*{{1,4}}|[\u4e00-\u9fff]{{1,2}}(?:先生|女士)/;
    const singleSurnameRe = /^[\u4e00-\u9fff]$/;
    const fullPersonNameRe = /^[\u4e00-\u9fff]{2,4}$/;
    const genderRe = /(?<![\u4e00-\u9fff])(男|女)(?![\u4e00-\u9fff])/;
    const blockedName = (n) => /未分组|全部收藏|追问|观察|候选|管理|搜索|更多|知道了|操作|本科|硕士|博士|大专|查看|详情|下载|预览|编辑|删除|沟通|联系|邀请|置顶|收藏|分享|面试/.test(n);
    const blockedRowText = (t) => /未分组|全部收藏|简历编号|姓名\\s*性别|搜索|管理/.test(t);
    const intersectsMainPanel = (el) => {{
        const r = el.getBoundingClientRect();
        return r.right > mainMinX() + 40 && r.width >= 16 && r.height >= 8
            && r.bottom > 0 && r.top < innerHeight;
    }};
    const nameCellInMainPanel = (row) => {{
        for (const td of row.querySelectorAll('td')) {{
            if (!intersectsMainPanel(td)) continue;
            if (isNameCell(norm(td.innerText))) return true;
        }}
        for (const td of row.querySelectorAll('td')) {{
            if (intersectsMainPanel(td)) return true;
        }}
        return intersectsMainPanel(row);
    }};
    const pickNameFromCells = (cells) => {{
        let best = null;
        let bestScore = -1;
        for (let i = 0; i < cells.length; i++) {{
            const n = norm(cells[i]);
            if (!isNameCell(n)) continue;
            let score = 0;
            if (nameInTextRe.test(n)) score += 4;
            else if (singleSurnameRe.test(n)) score += 3;
            else if (fullPersonNameRe.test(n)) score += 2;
            const tail = cells.slice(i + 1, i + 4).map(norm);
            if (tail[0] === '男' || tail[0] === '女') score += 4;
            if (tail.some(t => /^\\d{{1,2}}(?:岁)?$/.test(t))) score += 3;
            if (score > bestScore) {{ bestScore = score; best = n; }}
        }}
        return best;
    }};
    const isNameCell = (n) => {{
        n = norm(n || '');
        if (!n || blockedName(n)) return false;
        if (nameInTextRe.test(n)) return true;
        if (singleSurnameRe.test(n)) return true;
        if (fullPersonNameRe.test(n)) return true;
        return false;
    }};
    const extractName = (t) => {{
        const masked = (t || '').match(nameInTextRe);
        if (masked && isNameCell(masked[0])) return masked[0];
        const full = (t || '').match(/^([\u4e00-\u9fff]{{2,4}})\s*(?:男|女|\\||\\s|\\d)/);
        if (full && isNameCell(full[1])) return full[1];
        const single = (t || '').match(/^([\u4e00-\u9fff])\\s*(?:男|女|\\||\\s|\\d)/);
        if (single && isNameCell(single[1])) return single[1];
        return '';
    }};
    const hasAge = (t) => /\\d{{1,2}}岁/.test(t) || /(?:^|[\\s|/])\\d{{1,2}}(?:[\\s|/]|$)/.test(t);
    const hasEdu = (t) => /(博士|硕士|本科|大专|MBA)/.test(t);
    const looksLikeRow = (t) => {{
        if (!t || blockedRowText(t)) return false;
        if (t.length < 4 || t.length > 500) return false;
        if (!extractName(t)) return false;
        if (!genderRe.test(t)) return false;
        if (!hasAge(t)) return false;
        if (!hasEdu(t)) return false;
        return true;
    }};
    const parseStructuredCells = (cells) => {{
        if (!cells || cells.length < 3) return null;
        const name = pickNameFromCells(cells);
        if (!name) return null;
        const joined = cells.map(norm).join(' | ');
        const genderOk = cells.some(c => c === '男' || c === '女') || genderRe.test(joined);
        const ageOk = cells.some(c => /^\\d{{1,2}}(?:岁)?$/.test(norm(c))) || hasAge(joined);
        if (!genderOk) return null;
        if (!ageOk) return null;
        if (!hasEdu(joined)) return null;
        return {{ name, text: joined, cells }};
    }};
    const mainPanelCells = (row) => {{
        return [...row.querySelectorAll('td')]
            .filter(td => intersectsMainPanel(td))
            .map(el => norm(el.innerText))
            .filter(Boolean);
    }};
    const readTableHeaders = (table) => {{
        const headRow = table.querySelector('thead tr')
            || [...table.querySelectorAll('tr')].find(tr => /姓名/.test(norm(tr.innerText)));
        if (!headRow) return [];
        return [...headRow.querySelectorAll('th,td')]
            .filter(el => intersectsMainPanel(el))
            .map(el => norm(el.innerText))
            .filter(Boolean);
    }};
    const pushUnique = (results, seen, item) => {{
        const key = (item.text || item.name || '').slice(0, 80) + '|' + Math.round(item.top / 3);
        if (seen.has(key)) return;
        seen.add(key);
        results.push(item);
    }};
    const scanMainList = () => {{
        const results = [];
        const seen = new Set();
        // 1) table 分列（全宽表格：用姓名列位置判断是否在主区域）
        for (const table of document.querySelectorAll('table')) {{
            const tb = table.getBoundingClientRect();
            if (tb.right <= mainMinX() + 40 || tb.width < 120) continue;
            const tableHeaders = readTableHeaders(table);
            const body = table.querySelectorAll('tbody tr');
            const rows = body.length ? [...body] : [...table.querySelectorAll('tr')].slice(1);
            for (const row of rows) {{
                if (!nameCellInMainPanel(row)) continue;
                const cells = mainPanelCells(row);
                if (cells.length >= 3 && cells[0] !== '姓名') {{
                    const parsed = parseStructuredCells(cells);
                    if (parsed) {{
                        pushUnique(results, seen, {{
                            ...parsed,
                            headers: tableHeaders.length ? tableHeaders : null,
                            top: row.getBoundingClientRect().top,
                        }});
                        continue;
                    }}
                }}
                const t = norm(row.innerText);
                if (looksLikeRow(t)) {{
                    pushUnique(results, seen, {{
                        name: extractName(t),
                        text: t.slice(0, 400),
                        cells: cells.length >= 2 ? cells : null,
                        headers: tableHeaders.length ? tableHeaders : null,
                        top: row.getBoundingClientRect().top,
                    }});
                }}
            }}
            if (results.length) break;
        }}
        // 2) list / item 行
        if (!results.length) {{
            for (const sel of ['li', '[class*="list"] [class*="item"]', '[class*="List"] [class*="Item"]', '[class*="row"]', '[class*="Row"]']) {{
                for (const el of document.querySelectorAll(sel)) {{
                    if (!intersectsMainPanel(el)) continue;
                    const t = norm(el.innerText);
                    if (!looksLikeRow(t)) continue;
                    pushUnique(results, seen, {{
                        name: extractName(t),
                        text: t.slice(0, 400),
                        cells: null,
                        top: el.getBoundingClientRect().top,
                    }});
                }}
                if (results.length) break;
            }}
        }}
        // 3) 主区域文本块
        if (!results.length) {{
            for (const el of document.querySelectorAll('div, span, p, a, td')) {{
                if (!intersectsMainPanel(el)) continue;
                const t = norm(el.innerText);
                if (!looksLikeRow(t)) continue;
                if (el.children && el.children.length > 4) continue;
                pushUnique(results, seen, {{
                    name: extractName(t),
                    text: t.slice(0, 400),
                    cells: null,
                    top: el.getBoundingClientRect().top,
                }});
            }}
        }}
        results.sort((a, b) => a.top - b.top);
        return results.map((item, idx) => ({{ ...item, index: idx }}));
    }};
    const debugMainPanel = () => {{
        const tables = [];
        for (const table of document.querySelectorAll('table')) {{
            const tb = table.getBoundingClientRect();
            const rows = [...table.querySelectorAll('tbody tr, tr')].slice(0, 5).map((row) => {{
                const cells = mainPanelCells(row);
                if (!cells.length) {{
                    cells.push(...[...row.querySelectorAll('td,th')].map(el => norm(el.innerText)).filter(Boolean));
                }}
                return {{ cells, text: norm(row.innerText).slice(0, 120) }};
            }});
            tables.push({{ left: Math.round(tb.left), width: Math.round(tb.width), rows }});
        }}
        const samples = scanMainList().slice(0, 3).map(r => r.text || r.name);
        return {{ mainMinX: mainMinX(), tables: tables.slice(0, 3), samples }};
    }};
"""

_SCAN_MAIN_LIST_JS = (
    "() => {"
    + _MAIN_LIST_HELPERS_JS
    + """
    return scanMainList();
}"""
)

_WAIT_MAIN_LIST_JS = (
    "() => {"
    + _MAIN_LIST_HELPERS_JS
    + """
    const rows = scanMainList();
    if (rows.length > 0) {
        return { ready: true, rows: rows.length, mode: 'full_rows' };
    }
    return { ready: false, rows: 0, mode: 'none' };
}"""
)

_CLICK_NEXT_LIST_PAGE_JS = f"""
() => {{
    const mainMinX = () => window.innerWidth * {_MAIN_PANEL_MIN_X_RATIO};
    const isVisible = (el) => {{
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 8 && r.height > 8 && r.right > mainMinX() + 40
            && s.visibility !== 'hidden' && s.display !== 'none';
    }};
    const disabled = (el) => {{
        if (el.disabled || el.getAttribute('aria-disabled') === 'true') return true;
        const cls = (el.className || '').toString();
        return /disabled|ant-pagination-disabled/.test(cls);
    }};
    const tryClick = (el) => {{
        if (!el || !isVisible(el) || disabled(el)) return false;
        el.scrollIntoView({{ block: 'center' }});
        el.click();
        return true;
    }};
    for (const sel of ['.ant-pagination-next button', '.ant-pagination-next', '[class*="pagination-next"]', '[class*="Pagination-next"]']) {{
        const el = document.querySelector(sel);
        if (tryClick(el)) return {{ ok: true, via: sel }};
    }}
    for (const el of document.querySelectorAll('a, button, li, span')) {{
        if (!isVisible(el) || disabled(el)) continue;
        const t = (el.innerText || '').trim();
        if (t === '下一页' || t === '›' || t === '»' || t === '>') {{
            if (tryClick(el)) return {{ ok: true, via: 'text' }};
        }}
    }}
    for (const el of document.querySelectorAll('a, button, li, span')) {{
        if (!isVisible(el)) continue;
        const t = (el.innerText || '').trim();
        if (/^\\d+$/.test(t)) {{
            const active = (el.className || '').toString();
            if (/active|current|selected/.test(active)) continue;
            const num = parseInt(t, 10);
            const activeEl = document.querySelector('.ant-pagination-item-active, [class*="active"]');
            const activeText = activeEl ? (activeEl.innerText || '').trim() : '';
            const cur = parseInt(activeText, 10);
            if (!isNaN(cur) && num === cur + 1) {{
                if (tryClick(el)) return {{ ok: true, via: 'page_num', page: num }};
            }}
        }}
    }}
    return {{ ok: false }};
}}
"""

_GET_LIST_PAGE_STATE_JS = f"""
() => {{
    const mainMinX = () => window.innerWidth * {_MAIN_PANEL_MIN_X_RATIO};
    let current = '';
    for (const el of document.querySelectorAll('.ant-pagination-item-active, [class*="pagination"] [class*="active"], li, a, button')) {{
        const r = el.getBoundingClientRect();
        if (r.left < mainMinX()) continue;
        const t = (el.innerText || '').trim();
        if (/^\\d+$/.test(t) && /active|current|selected/.test((el.className || '').toString())) {{
            current = t;
            break;
        }}
    }}
    return {{ current }};
}}
"""


def _cache_resume_library_folder(page: Page, folder: str) -> None:
    _PAGE_FOLDER_CACHE[id(page)] = folder


def _cached_resume_library_folder(page: Page) -> str | None:
    return _PAGE_FOLDER_CACHE.get(id(page))


def _clear_resume_library_folder_cache(page: Page) -> None:
    _PAGE_FOLDER_CACHE.pop(id(page), None)
    _clear_resume_library_page_rows_cache(page)


def _normalize_cache_part(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _folder_cache_key(parent_folder: str | None, folder: str) -> str:
    parent = str(parent_folder or "").strip()
    child = str(folder or "").strip()
    return f"{parent}/{child}" if parent else child


def _profile_cache_key(profile: ResumeLibraryMatchProfile) -> str:
    parts = [
        profile.parent_folder,
        profile.folder,
        profile.display_name,
        profile.surname,
        profile.gender,
        profile.age,
        profile.education,
        profile.current_title,
        profile.current_company,
        profile.collect_time,
    ]
    raw = "\x1f".join(_normalize_cache_part(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_folder_page_rows(
    page: Page,
    folder: str,
    page_no: int,
    rows: list[ResumeLibraryRow],
) -> None:
    if not folder or page_no < 1:
        return
    _FOLDER_PAGE_ROWS_CACHE[(id(page), folder, page_no)] = list(rows)


def _cached_folder_page_rows(
    page: Page,
    folder: str,
    page_no: int,
) -> list[ResumeLibraryRow] | None:
    rows = _FOLDER_PAGE_ROWS_CACHE.get((id(page), folder, page_no))
    return list(rows) if rows is not None else None


def _clear_resume_library_page_rows_cache(page: Page, folder: str | None = None) -> None:
    page_id = id(page)
    for key in list(_FOLDER_PAGE_ROWS_CACHE):
        if key[0] == page_id and (folder is None or key[1] == folder):
            _FOLDER_PAGE_ROWS_CACHE.pop(key, None)


def _cache_resume_library_match(
    profile: ResumeLibraryMatchProfile,
    *,
    page_no: int,
    row: ResumeLibraryRow,
) -> None:
    if page_no < 1:
        return
    folder_key = _folder_cache_key(profile.parent_folder, profile.folder)
    _MATCH_RESULT_CACHE[_profile_cache_key(profile)] = {
        "folder": folder_key,
        "page_no": page_no,
        "row_index": row.index,
        "row_name": row.name,
    }


def _cached_resume_library_match(profile: ResumeLibraryMatchProfile) -> dict[str, object] | None:
    hit = _MATCH_RESULT_CACHE.get(_profile_cache_key(profile))
    if not hit or hit.get("folder") != _folder_cache_key(profile.parent_folder, profile.folder):
        return None
    return dict(hit)


def _clear_resume_library_match_cache(profile: ResumeLibraryMatchProfile | None = None) -> None:
    if profile is None:
        _MATCH_RESULT_CACHE.clear()
        return
    _MATCH_RESULT_CACHE.pop(_profile_cache_key(profile), None)


async def _current_list_page_number(page: Page) -> int:
    try:
        state = await page.evaluate(_GET_LIST_PAGE_STATE_JS)
    except Exception:
        return 1
    current = str((state or {}).get("current") or "").strip()
    try:
        return max(int(current), 1)
    except ValueError:
        return 1


async def _list_page_is_first(page: Page) -> bool:
    try:
        state = await page.evaluate(_GET_LIST_PAGE_STATE_JS)
    except Exception:
        return False
    current = str((state or {}).get("current") or "").strip()
    return current in ("", "1")


async def _right_list_ready_now(page: Page) -> bool:
    try:
        state = await page.evaluate(_WAIT_MAIN_LIST_JS)
    except Exception:
        return False
    return bool(state and state.get("ready") and (state.get("rows") or 0) > 0)


async def _can_reuse_current_folder(
    page: Page,
    folder: str,
    parent_folder: str | None = None,
) -> bool:
    if _cached_resume_library_folder(page) != _folder_cache_key(parent_folder, folder):
        return False
    if not await _list_page_is_first(page):
        return False
    return await _right_list_ready_now(page)


def _folder_tab_labels(folder: str) -> list[str]:
    """Match a job folder tab in the resume library sidebar."""
    raw = str(folder or "").strip()
    if not raw or is_decision_sidebar_label(raw):
        return []
    open_full = "\uFF08"
    close_full = "\uFF09"
    return [
        rf"^{re.escape(raw)}$",
        rf"^{re.escape(raw)}[\({open_full}]\d+[\){close_full}]$",
    ]


async def _verify_folder_tab_selected(page: Page, folder: str) -> bool:
    patterns = _folder_tab_labels(folder)
    state = await page.evaluate(_VERIFY_FOLDER_TAB_JS, patterns)
    if state and state.get("ok"):
        return True
    if state and state.get("reason") == "uncategorized_active":
        logger.warning("Resume library sidebar stuck on: %s", state.get("selected"))
    return False


def _folder_parent_labels(parent_folder: str) -> list[str]:
    parent = str(parent_folder or "").strip()
    if not parent:
        return []
    open_full = "\uFF08"
    close_full = "\uFF09"
    return [rf"^{re.escape(parent)}$", rf"^{re.escape(parent)}[\({open_full}]\d+[\){close_full}]$"]


async def _collect_sidebar_visible_texts(page: Page) -> list[str]:
    try:
        values = await page.evaluate(
            r"""() => {
                const maxX = innerWidth * 0.38;
                const isVisible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width >= 12 && r.height >= 12 && r.left <= maxX
                        && r.bottom > 0 && r.top < innerHeight
                        && s.visibility !== 'hidden' && s.display !== 'none';
                };
                const out = [];
                for (const el of document.querySelectorAll('li, a, button, div, span, label, p')) {
                    if (!isVisible(el)) continue;
                    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
                    if (text && text.length <= 80) out.push(text);
                }
                return [...new Set(out)].slice(0, 100);
            }"""
        )
    except Exception:
        return []
    return [str(item).strip() for item in values or [] if str(item).strip()]


async def _click_parent_folder_tab(page: Page, parent_folder: str) -> None:
    parent = str(parent_folder or "").strip()
    if not parent:
        return
    patterns = _folder_parent_labels(parent)
    for attempt in range(3):
        hit = await page.evaluate(_CLICK_FOLDER_TAB_JS, patterns)
        if hit and hit.get("ok"):
            logger.info("Clicked resume library parent folder: %s", hit.get("text"))
            await page.wait_for_timeout(350)
            return

        vp = page.viewport_size or {"width": 1440, "height": 900}
        for pattern in patterns:
            try:
                loc = page.get_by_text(re.compile(pattern))
            except Exception:
                continue
            count = await loc.count()
            for i in range(count):
                item = loc.nth(i)
                if not await item.is_visible(timeout=500):
                    continue
                box = await item.bounding_box()
                if not box or box["x"] > vp["width"] * 0.38:
                    continue
                row = item.locator("xpath=ancestor::li[1] | ancestor::a[1] | ancestor::button[1]")
                if await row.count() > 0:
                    await row.first.click(timeout=5000)
                else:
                    await item.click(timeout=5000)
                await page.wait_for_timeout(350)
                return

        visible_texts = await _collect_sidebar_visible_texts(page)
        inferred = infer_ui_target(
            desired_label=parent,
            visible_texts=visible_texts,
            action_context="resume_library_parent_group",
        )
        logger.info(
            "Resume library job folder inference: desired=%s action=%s target=%s confidence=%.2f",
            parent,
            inferred.action,
            inferred.target_text,
            inferred.confidence,
        )
        if inferred.action == "click" and inferred.target_text:
            try:
                loc = page.get_by_text(re.compile(rf"^{re.escape(inferred.target_text)}$")).first
                if await loc.is_visible(timeout=800):
                    row = loc.locator("xpath=ancestor::li[1] | ancestor::a[1] | ancestor::button[1]")
                    if await row.count() > 0:
                        await row.first.click(timeout=5000)
                    else:
                        await loc.click(timeout=5000)
                    await page.wait_for_timeout(350)
                    return
            except Exception:
                pass
        if attempt < 2:
            await page.wait_for_timeout(400)

    await _save_debug_screenshot(page, f"resume_lib_parent_{parent}_miss")
    raise RuntimeError(f"未能选中简历库岗位文件夹「{parent}」")


async def _save_debug_screenshot(page: Page, name: str) -> None:
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=True)
    except Exception as e:
        logger.warning("Screenshot failed: %s", e)


async def _click_sidebar_menu(page: Page, labels: list[str]) -> bool:
    """侧栏菜单（如「人才管理」）。"""
    hit = await page.evaluate(_CLICK_SIDEBAR_MENU_JS, labels)
    if hit and hit.get("ok"):
        return True
    vp = page.viewport_size or {"width": 1440, "height": 900}
    left_max_x = vp["width"] * _SIDEBAR_MAX_X_RATIO
    for label in labels:
        try:
            loc = page.get_by_text(label, exact=True)
        except Exception:
            continue
        count = await loc.count()
        for i in range(count):
            item = loc.nth(i)
            if not await item.is_visible(timeout=800):
                continue
            box = await item.bounding_box()
            if not box or box["x"] >= left_max_x:
                continue
            await item.click(timeout=5000)
            return True
    return False


async def _click_top_tab(page: Page, labels: list[str]) -> bool:
    """主区域上方「简历库」子标签：Playwright 真实点击优先。"""
    top_max_y = (page.viewport_size or {"height": 900})["height"] * _TOP_TAB_MAX_Y_RATIO

    for attempt in range(6):
        if attempt:
            await page.wait_for_timeout(700)

        for sel in LPT_RESUME_LIBRARY_TOP_TAB_SELECTORS:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                for i in range(count):
                    item = loc.nth(i)
                    if not await item.is_visible(timeout=500):
                        continue
                    box = await item.bounding_box()
                    if not box or box["y"] > top_max_y:
                        continue
                    if box["width"] > _TOP_TAB_MAX_LABEL_W or box["height"] > _TOP_TAB_MAX_LABEL_H:
                        continue
                    await item.scroll_into_view_if_needed()
                    await item.click(timeout=8000)
                    await page.wait_for_timeout(500)
                    if await _is_resume_library_page(page):
                        return True
            except Exception:
                continue

        for label in labels:
            try:
                loc = page.get_by_text(label, exact=True)
            except Exception:
                continue
            count = await loc.count()
            candidates: list[tuple[Locator, float, float]] = []
            for i in range(count):
                item = loc.nth(i)
                if not await item.is_visible(timeout=500):
                    continue
                box = await item.bounding_box()
                if not box or box["y"] > top_max_y:
                    continue
                if box["width"] > _TOP_TAB_MAX_LABEL_W or box["height"] > _TOP_TAB_MAX_LABEL_H:
                    continue
                candidates.append((item, box["y"], box["x"]))
            if candidates:
                candidates.sort(key=lambda c: (c[1], c[2]))
                try:
                    await candidates[0][0].scroll_into_view_if_needed()
                    await candidates[0][0].click(timeout=8000)
                    await page.wait_for_timeout(500)
                    if await _is_resume_library_page(page):
                        return True
                except Exception:
                    pass

        hit = await page.evaluate(_CLICK_TOP_TAB_JS, labels)
        if hit and hit.get("ok"):
            await page.wait_for_timeout(600)
            if await _is_resume_library_page(page):
                return True

    debug = await page.evaluate(_DEBUG_TOP_TABS_JS, labels)
    logger.warning("Resume library top tab debug: %s", debug)
    return False


async def _click_text(page: Page, labels: list[str], *, exact: bool = False) -> bool:
    for label in labels:
        try:
            loc = page.get_by_text(label, exact=exact).first
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


async def _is_resume_library_page(page: Page) -> bool:
    """已进入简历库：左侧有分组 + 表格含收藏时间/目前公司（不能仅凭页面出现「简历库」三字）。"""
    try:
        body = await page.locator("body").inner_text()
    except Exception:
        return False
    if "未分组的人选" in body:
        return True
    if "收藏时间" in body and "目前公司" in body and "姓名" in body:
        return True
    return False


async def _navigate_to_resume_library(page: Page) -> None:
    if await _is_resume_library_page(page):
        return

    await page.goto(LPT_SEARCH_URL, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
    _clear_resume_library_folder_cache(page)
    await page.wait_for_timeout(700)

    if not await _click_sidebar_menu(page, list(LPT_TALENT_MGMT_SIDEBAR)):
        await _save_debug_screenshot(page, "resume_lib_talent_mgmt_miss")
        raise RuntimeError("未找到侧栏「人才管理」，请确认已登录猎聘 LPT")

    await page.wait_for_timeout(500)

    for attempt in range(3):
        if await _click_top_tab(page, list(LPT_RESUME_LIBRARY_TOP_TAB)):
            break
        if attempt < 2:
            await _click_sidebar_menu(page, list(LPT_TALENT_MGMT_SIDEBAR))
            await page.wait_for_timeout(400)
    else:
        await _save_debug_screenshot(page, "resume_lib_top_tab_miss")
        raise RuntimeError(
            "未能点中上方「简历库」标签。"
            "请确认侧栏已选「人才管理」，且顶部子标签栏可见「简历库」。"
        )

    await page.wait_for_timeout(500)

    if not await _is_resume_library_page(page):
        await _save_debug_screenshot(page, "resume_lib_page_miss")
        raise RuntimeError("未能进入简历库页面，请检查账号权限或页面结构是否变更")


async def _click_folder_tab(page: Page, folder: str, parent_folder: str | None = None) -> None:
    """点击左侧岗位名称文件夹，右侧才出现收藏 list。"""
    _ = parent_folder  # 兼容旧调用；收藏已按岗位单层分组，不再点观察/追问/候选
    folder = str(folder or "").strip()
    if not folder or is_decision_sidebar_label(folder):
        raise RuntimeError(
            "简历库跳转需要岗位文件夹名称；观察/追问/候选仅作系统标签，不能作为侧栏分组点击。"
        )
    patterns = _folder_tab_labels(folder)
    if not patterns:
        raise RuntimeError(f"无效的简历库岗位文件夹：{folder!r}")
    cache_key = _folder_cache_key(None, folder)

    for attempt in range(4):
        hit = await page.evaluate(_CLICK_FOLDER_TAB_JS, patterns)
        if hit and hit.get("ok"):
            logger.info("Clicked resume library tab: %s (attempt %d)", hit.get("text"), attempt + 1)
            await page.wait_for_timeout(350)
            if await _verify_folder_tab_selected(page, folder):
                _clear_resume_library_page_rows_cache(page, cache_key)
                _cache_resume_library_folder(page, cache_key)
                return
            logger.warning("Folder tab not active after click: %s", hit.get("text"))

        # Playwright 兜底：仅 regex 精确匹配
        vp = page.viewport_size or {"width": 1440, "height": 900}
        for pattern in patterns:
            try:
                loc = page.get_by_text(re.compile(pattern))
            except Exception:
                continue
            count = await loc.count()
            for i in range(count):
                item = loc.nth(i)
                if not await item.is_visible(timeout=500):
                    continue
                text = re.sub(r"\s+", " ", (await item.inner_text() or "")).strip()
                if "未分组" in text:
                    continue
                box = await item.bounding_box()
                if not box or box["x"] > vp["width"] * 0.38:
                    continue
                row = item.locator("xpath=ancestor::li[1] | ancestor::a[1] | ancestor::button[1]")
                if await row.count() > 0:
                    await row.first.click(timeout=5000)
                else:
                    await item.click(timeout=5000)
                await page.wait_for_timeout(350)
                if await _verify_folder_tab_selected(page, folder):
                    _clear_resume_library_page_rows_cache(page, cache_key)
                    _cache_resume_library_folder(page, cache_key)
                    return

        await page.wait_for_timeout(400)

    await _save_debug_screenshot(page, f"resume_lib_tab_{folder}_miss")
    raise RuntimeError(
        f"未能选中简历库岗位文件夹「{folder}」（勿点「未分组的人选」或观察/追问/候选标签）。"
        f"请确认左侧存在该岗位分组且其中有收藏记录。"
    )


_DEBUG_MAIN_PANEL_JS = (
    "() => {"
    + _MAIN_LIST_HELPERS_JS
    + """
    return debugMainPanel();
}"""
)


async def _wait_right_list_ready(page: Page, timeout_ms: int = _LIST_READY_MS) -> None:
    """等待主页右侧出现收藏列表行（整行含姓名/性别/年龄/学历等字段）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        state = await page.evaluate(_WAIT_MAIN_LIST_JS)
        if state and state.get("ready") and (state.get("rows") or 0) > 0:
            await page.wait_for_timeout(120)
            return
        await page.wait_for_timeout(180)

    debug = await page.evaluate(_DEBUG_MAIN_PANEL_JS)
    logger.warning("Resume library main list scan debug: %s", debug)
    await _save_debug_screenshot(page, "resume_lib_main_list_timeout")
    hint = ""
    if debug and debug.get("tables"):
        first_rows = debug["tables"][0].get("rows") if debug["tables"] else []
        if first_rows:
            hint = f" 页面首行样例: {first_rows[0]}"
    raise RuntimeError(
        "点击岗位文件夹后，主页右侧未扫描到收藏列表行。"
        "请确认该岗位分组下有收藏记录；若页面结构已变更请查看 data/debug/resume_lib_main_list_timeout.png"
        f"{hint}"
    )


async def _scan_right_rows(page: Page) -> list[ResumeLibraryRow]:
    folder = _cached_resume_library_folder(page)
    page_no = await _current_list_page_number(page) if folder else 1
    if folder:
        cached = _cached_folder_page_rows(page, folder, page_no)
        if cached is not None:
            return cached

    raw_rows = await page.evaluate(_SCAN_MAIN_LIST_JS)
    rows: list[ResumeLibraryRow] = []
    for i, item in enumerate(raw_rows or []):
        cells = item.get("cells")
        headers = item.get("headers")
        parsed = None
        if cells:
            parsed = parse_row_from_cells(cells, index=item.get("index", i), headers=headers)
        if not parsed and item.get("text"):
            parsed = parse_row_from_full_text(item.get("text") or "", index=item.get("index", i))
        if not parsed and item.get("name") and item.get("text"):
            parsed = parse_row_from_list_text(
                item.get("name") or "",
                item.get("text") or "",
                index=item.get("index", i),
            )
        if not parsed and item.get("name"):
            parsed = parse_row_from_list_text(
                item.get("name") or "",
                item.get("text") or "",
                index=item.get("index", i),
            )
        if parsed:
            top = item.get("top")
            if top is not None:
                parsed.list_top = float(top)
            rows.append(parsed)
    if folder:
        _cache_folder_page_rows(page, folder, page_no, rows)
    return rows


async def _click_next_list_page(page: Page) -> bool:
    before = await page.evaluate(_GET_LIST_PAGE_STATE_JS)
    hit = await page.evaluate(_CLICK_NEXT_LIST_PAGE_JS)
    if not hit or not hit.get("ok"):
        return False
    await page.wait_for_timeout(350)
    after = await page.evaluate(_GET_LIST_PAGE_STATE_JS)
    if before.get("current") and after.get("current") == before.get("current"):
        await page.wait_for_timeout(350)
        after = await page.evaluate(_GET_LIST_PAGE_STATE_JS)
        if before.get("current") == after.get("current"):
            return False
    return True


async def _go_to_list_page(page: Page, target_page: int) -> bool:
    if target_page <= 1:
        return await _list_page_is_first(page)

    current = await _current_list_page_number(page)
    if current == target_page:
        return True
    if current > target_page:
        return False

    while current < target_page:
        before = current
        if not await _click_next_list_page(page):
            return False
        await _wait_right_list_ready(page, timeout_ms=8000)
        current = await _current_list_page_number(page)
        if current <= before:
            return False
    return current == target_page


async def _try_cached_resume_library_match(
    page: Page,
    profile: ResumeLibraryMatchProfile,
) -> ResumeLibraryRow | None:
    hit = _cached_resume_library_match(profile)
    if not hit:
        return None

    page_no = int(hit.get("page_no") or 1)
    if not await _go_to_list_page(page, page_no):
        _clear_resume_library_match_cache(profile)
        await _click_folder_tab(page, profile.folder, profile.parent_folder)
        await _wait_right_list_ready(page)
        return None

    rows = await _scan_right_rows(page)
    matched, scores = find_resume_library_row(profile, rows)
    if matched and scores:
        logger.info(
            "Resume library cached page match: %s page=%d scores=%s",
            matched.name,
            page_no,
            scores.as_dict(),
        )
        return matched

    logger.info(
        "Resume library cached match stale: %s page=%d row=%s",
        profile.display_name,
        page_no,
        hit.get("row_name"),
    )
    _clear_resume_library_match_cache(profile)
    await _click_folder_tab(page, profile.folder, profile.parent_folder)
    await _wait_right_list_ready(page)
    return None


async def _find_row_across_pages(page: Page, profile: ResumeLibraryMatchProfile) -> ResumeLibraryRow:
    """逐页扫描，四要素模糊相似度均 >= 80% 则命中。"""
    cached = await _try_cached_resume_library_match(page, profile)
    if cached:
        return cached

    best_near: tuple[ResumeLibraryRow, dict[str, float]] | None = None
    best_surname: tuple[ResumeLibraryRow, dict[str, float]] | None = None
    total_rows = 0
    pages_scanned = 0
    for page_no in range(1, _MAX_LIST_PAGES + 1):
        rows = await _scan_right_rows(page)
        pages_scanned = page_no
        total_rows += len(rows)
        logger.info("Resume library page %d: scanned %d list rows", page_no, len(rows))
        if rows:
            try:
                matched, scores = find_resume_library_row(profile, rows)
            except ValueError:
                raise
            if matched and scores:
                logger.info(
                    "Resume library fuzzy match: %s scores=%s",
                    matched.name,
                    scores.as_dict(),
                )
                _cache_resume_library_match(profile, page_no=page_no, row=matched)
                return matched
            for row in rows:
                cs = score_row_fields(profile, row)
                if best_near is None or cs.min_score > best_near[1]["min"]:
                    best_near = (row, cs.as_dict())
                if cs.surname >= FUZZY_FIELD_THRESHOLD and (
                    best_surname is None or cs.min_score > best_surname[1]["min"]
                ):
                    best_surname = (row, cs.as_dict())
        if page_no >= _MAX_LIST_PAGES:
            break
        if not await _click_next_list_page(page):
            break
        await _wait_right_list_ready(page, timeout_ms=8000)
    detail = ""
    report = best_surname or best_near
    if report:
        row, sc = report
        logger.warning(
            "Resume library best near miss: %s scores=%s (need all >= %.0f%%)",
            row.name,
            sc,
            FUZZY_FIELD_THRESHOLD * 100,
        )
        weak = [
            k
            for k in ("surname", "age", "education", "company")
            if sc.get(k, 0) < FUZZY_FIELD_THRESHOLD
        ]
        label = "姓氏匹配最接近" if best_surname else "全局最接近"
        detail = (
            f" 已在「{profile.folder}」扫描 {pages_scanned} 页共 {total_rows} 行。"
            f"{label}：{row.name}（{row.raw_text[:60]}…），"
            f"相似度 {sc}，未达标项：{'、'.join(weak) or '无'}。"
        )
    else:
        detail = (
            f" 已在「{profile.folder}」扫描 {pages_scanned} 页共 {total_rows} 行，"
            "未解析到任何有效列表行；请确认该分组下有收藏记录。"
        )
    raise RuntimeError(
        f"已翻页扫描仍未找到四要素均 ≥{FUZZY_FIELD_THRESHOLD:.0%} 相似的记录："
        f"姓氏 {profile.surname}、年龄 {profile.age}、学历 {profile.education}、"
        f"公司 {profile.current_company}。{detail}"
        "若人在其他岗位文件夹，请确认收藏时使用的岗位名称与任务一致。"
    )


def _row_text_matches_hint(row: ResumeLibraryRow, text: str) -> bool:
    from services.fetch_worker.resume_library_row_match import extract_name_from_row_text

    name_in_row = extract_name_from_row_text(text) or ""
    if not names_match(name_in_row, row.name):
        return False
    if row.raw_text and len(row.raw_text) >= 10:
        norm_text = text.replace(" ", "")
        key = row.raw_text[:24].replace(" ", "")
        if key and key[:20] not in norm_text:
            if row.age is not None and str(row.age) not in text:
                return False
    return True


async def _is_checkbox_cell(td: Locator) -> bool:
    """勾选列（勿点）。"""
    try:
        if await td.locator(
            "input[type='checkbox'], .ant-checkbox, .ant-checkbox-wrapper, [class*='checkbox']"
        ).count() > 0:
            return True
    except Exception:
        pass
    try:
        text = re.sub(r"\s+", " ", (await td.inner_text() or "")).strip()
    except Exception:
        return False
    return text in ("", "☑", "☐", "✓")


async def _find_name_td(
    tr: Locator,
    row: ResumeLibraryRow,
    *,
    main_min_x: float,
) -> Locator | None:
    """定位姓名列（跳过左侧勾选框与其它列）。"""
    name_hint = (row.name or "").strip()
    td_loc = tr.locator("td")
    count = await td_loc.count()
    best: tuple[Locator, int] | None = None

    for i in range(count):
        td = td_loc.nth(i)
        try:
            box = await td.bounding_box()
        except Exception:
            continue
        if not box or box["x"] + box["width"] * 0.25 < main_min_x:
            continue
        if await _is_checkbox_cell(td):
            continue

        text = re.sub(r"\s+", " ", (await td.inner_text() or "")).strip()
        link_text = ""
        link = td.locator("a").first
        if await link.count() > 0:
            try:
                link_text = re.sub(r"\s+", " ", (await link.inner_text() or "")).strip()
            except Exception:
                pass

        score = 0
        for candidate in (link_text, text, extract_name_from_row_text(text) or ""):
            if not candidate:
                continue
            if name_hint and names_match(name_hint, candidate):
                score = max(score, 12 if candidate == link_text else 10)
            elif name_hint and name_hint in candidate:
                score = max(score, 8)
        if await link.count() > 0 and score == 0 and name_hint and name_hint in (text + link_text):
            score = 7

        if score > 0 and (best is None or score > best[1]):
            best = (td, score)

    return best[0] if best else None


async def _click_name_td(td: Locator, row: ResumeLibraryRow) -> None:
    """点击姓名（优先 name link / 文本节点，绝不点勾选框）。"""
    name = (row.name or "").strip()
    link = td.locator("a").first
    if await link.count() > 0:
        try:
            lt = re.sub(r"\s+", " ", (await link.inner_text() or "")).strip()
        except Exception:
            lt = ""
        if not name or names_match(name, lt) or name in lt:
            await link.scroll_into_view_if_needed()
            await link.click(timeout=8000)
            return

    if name:
        for exact in (True, False):
            loc = td.get_by_text(name, exact=exact)
            if await loc.count() > 0:
                target = loc.first
                await target.scroll_into_view_if_needed()
                await target.click(timeout=8000)
                return

    await td.scroll_into_view_if_needed()
    box = await td.bounding_box()
    if box:
        await td.click(
            position={
                "x": min(max(box["width"] * 0.5, 6), box["width"] - 2),
                "y": min(max(box["height"] * 0.5, 6), box["height"] - 2),
            },
            timeout=8000,
        )
    else:
        await td.click(timeout=8000)


async def _click_row_name(
    tr: Locator,
    row: ResumeLibraryRow,
    *,
    main_min_x: float,
) -> None:
    td = await _find_name_td(tr, row, main_min_x=main_min_x)
    if td is None:
        raise RuntimeError(f"未找到姓名列（{row.name}）")
    await _click_name_td(td, row)


async def _dblclick_row_name(
    tr: Locator,
    row: ResumeLibraryRow,
    *,
    main_min_x: float,
) -> None:
    td = await _find_name_td(tr, row, main_min_x=main_min_x)
    if td is None:
        raise RuntimeError(f"未找到姓名列（{row.name}）")
    link = td.locator("a").first
    target = link if await link.count() > 0 else td
    await target.scroll_into_view_if_needed()
    await target.dblclick(timeout=8000)


async def _first_main_panel_td(row: Locator, main_min_x: float) -> Locator | None:
    """全宽表格中跳过左侧勾选/操作列，取主区域第一个 td。"""
    td_loc = row.locator("td")
    count = await td_loc.count()
    for i in range(count):
        td = td_loc.nth(i)
        try:
            box = await td.bounding_box()
        except Exception:
            continue
        if box and box["x"] + box["width"] * 0.25 >= main_min_x:
            return td
    return None


async def _find_row_locator(
    page: Page,
    row: ResumeLibraryRow,
    *,
    main_min_x: float,
) -> Locator | None:
    """Playwright 定位已匹配行（JS 仅用于扫描，点击必须用 locator）。"""
    candidates: list[tuple[Locator, float]] = []

    for sel in ("table tbody tr", "tr", "li"):
        loc = page.locator(sel)
        count = await loc.count()
        for i in range(count):
            item = loc.nth(i)
            try:
                if not await item.is_visible(timeout=300):
                    continue
            except Exception:
                continue

            tr_box = await item.bounding_box()
            if not tr_box:
                continue

            name_td = await _find_name_td(item, row, main_min_x=main_min_x)
            if name_td is None:
                name_td = await _first_main_panel_td(item, main_min_x)
            ref_box = await name_td.bounding_box() if name_td else tr_box
            if ref_box["x"] + ref_box["width"] * 0.25 < main_min_x:
                continue

            text = re.sub(r"\s+", " ", (await item.inner_text() or "")).strip()
            if not text or not _row_text_matches_hint(row, text):
                continue

            top_delta = abs(tr_box["y"] - row.list_top) if row.list_top is not None else 0.0
            if row.list_top is not None and top_delta > 80:
                continue
            candidates.append((item, top_delta))

    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[1])
    return candidates[0][0]


async def _refresh_matched_row(
    page: Page,
    profile: ResumeLibraryMatchProfile,
    hint: ResumeLibraryRow,
) -> ResumeLibraryRow:
    """匹配后页面可能滚动/关弹窗导致 top 偏移，点击前重新定位行。"""
    rows = await _scan_right_rows(page)
    try:
        hit, _ = find_resume_library_row(profile, rows)
        if hit:
            return hit
    except ValueError:
        raise
    for row in rows:
        if names_match(row.name, hint.name) and hint.raw_text:
            key = hint.raw_text[:60].replace(" ", "")
            if key and key[:24] in row.raw_text.replace(" ", ""):
                return row
    return hint


async def _click_list_row(
    page: Page,
    row: ResumeLibraryRow,
    *,
    profile: ResumeLibraryMatchProfile | None = None,
) -> None:
    """点击姓名列打开在线简历；弹窗出现即视为本任务完成。"""
    vp = page.viewport_size or {"width": 1440, "height": 900}
    main_min_x = vp["width"] * _MAIN_PANEL_MIN_X_RATIO
    click_strategies = (
        lambda tr: _click_row_name(tr, row, main_min_x=main_min_x),
        lambda tr: _dblclick_row_name(tr, row, main_min_x=main_min_x),
    )

    for attempt in range(4):
        if attempt > 0:
            await _close_popup_if_open(page)
            await page.wait_for_timeout(400)
            if profile:
                row = await _refresh_matched_row(page, profile, row)

        target = await _find_row_locator(page, row, main_min_x=main_min_x)
        if target is None:
            continue

        for strategy in click_strategies:
            try:
                await strategy(target)
                await page.wait_for_timeout(500)
                popup = await _wait_popup_open(page, timeout_ms=7000)
                if popup is not None:
                    logger.info(
                        "Resume library name click ok, popup open: %s",
                        row.name,
                    )
                    return
            except Exception as exc:
                logger.debug("Name click failed: %s", exc)
                continue

    await _save_debug_screenshot(page, "resume_lib_click_row_miss")
    raise RuntimeError(
        f"已尝试点击姓名「{row.name}」但未打开在线简历弹窗；"
        "请确认未误点左侧勾选框。"
    )


async def _close_popup_if_open(page: Page) -> None:
    for sel in LPT_POPUP_CLOSE:
        try:
            loc = page.locator(sel).last
            if await loc.is_visible(timeout=300):
                await loc.click(timeout=3000)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def open_candidate_in_resume_library(page: Page, profile: ResumeLibraryMatchProfile) -> dict:
    validate_profile_for_library_match(profile)
    folder = str(profile.folder or "").strip()
    if not folder or is_decision_sidebar_label(folder):
        raise RuntimeError(
            "缺少简历库岗位文件夹名称，无法跳转。"
            "请确认任务已配置开聊/收藏岗位，且候选人已完成收藏。"
        )

    await _navigate_to_resume_library(page)
    await _close_popup_if_open(page)

    if await _can_reuse_current_folder(page, profile.folder, profile.parent_folder):
        logger.info("Resume library folder reused: %s", profile.folder)
    else:
        await _click_folder_tab(page, profile.folder, profile.parent_folder)
        await _wait_right_list_ready(page)

    matched = await _find_row_across_pages(page, profile)

    logger.info(
        "Resume library strict match: %s -> %s | %s",
        profile.display_name,
        matched.name,
        matched.raw_text[:120],
    )

    await _click_list_row(page, matched, profile=profile)

    return {
        "ok": True,
        "completed": True,
        "popup_open": True,
        "matched_name": matched.name,
        "match_score": 1.0,
        "folder": profile.folder,
        "url": page.url,
    }
