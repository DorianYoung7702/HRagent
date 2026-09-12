"""Liepin job-selection popup matching helpers."""

from __future__ import annotations

import re
from collections.abc import Sequence

_SKIP_CARD_LABELS = frozenset({"确认", "确定", "取消", "关闭", "退出", "确认开聊"})


def extract_chat_job_title(text: str, *, fallback: str = "") -> str:
    """从需求/筛选 Markdown 推断开聊岗位（仅无 position_name 时的规则兜底；运行时以主页岗位名为准）。"""
    combined = (text or "").strip()
    if not combined:
        return (fallback or "").strip()[:48]

    patterns = (
        r"开聊岗位(?:名称|名)?[：:\s]*([^\n，。；;]{2,48})",
        r"岗位名称[：:\s]*([^\n，。；;]{2,48})",
        r"职位名称[：:\s]*([^\n，。；;]{2,48})",
        r"岗位[：:\s]*([^\n，。；;]{2,48})",
        r"职位[：:\s]*([^\n，。；;]{2,48})",
        r"在招[：:\s]*([^\n，。；;]{2,48})",
    )
    for pat in patterns:
        m = re.search(pat, combined)
        if not m:
            continue
        title = m.group(1).strip()
        title = re.sub(r"[（(].*[）)]\s*$", "", title).strip()
        title = re.sub(r"[，。；;].*$", "", title).strip()
        if len(title) >= 2 and title not in ("要求", "描述", "名称"):
            return title[:48]

    fb = (fallback or "").strip()
    if fb and "招聘" not in fb and len(fb) <= 24:
        return fb[:48]
    return ""


def _normalize_job_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def job_card_matches(card_text: str, target: str) -> bool:
    """岗位名须完整出现在卡片文本中（卡片后可带编号等无关后缀）。"""
    card = (card_text or "").strip()
    target = (target or "").strip()
    if not card or not target:
        return False
    if card in _SKIP_CARD_LABELS:
        return False
    if any(card.startswith(s) for s in _SKIP_CARD_LABELS):
        return False
    tn = _normalize_job_text(target)
    cn = _normalize_job_text(card)
    return bool(tn) and tn in cn


def score_job_card(card_text: str, target: str) -> int:
    """Score job-card text against target title; 100 when target fully contained in card."""
    return 100 if job_card_matches(card_text, target) else 0


def pick_best_job_card_index(cards: Sequence[str], target: str, *, min_score: int = 100) -> tuple[int, int]:
    """Return (best_index, score); return (-1, 0) when no card contains the full target name."""
    if not cards or not (target or "").strip():
        return -1, 0

    hits: list[tuple[int, str]] = [
        (i, (text or "").strip())
        for i, text in enumerate(cards)
        if job_card_matches(text, target)
    ]
    if not hits:
        return -1, 0

    tn = _normalize_job_text(target)

    def _rank(item: tuple[int, str]) -> tuple[int, int, int]:
        idx, text = item
        cn = _normalize_job_text(text)
        prefix = 0 if cn.startswith(tn) else 1
        pos = cn.find(tn) if tn in cn else len(cn)
        return (prefix, pos, len(cn))

    best_idx, _ = min(hits, key=_rank)
    best_score = score_job_card(cards[best_idx], target)
    if best_score < min_score:
        return -1, 0
    return best_idx, best_score
