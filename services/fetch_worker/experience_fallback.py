"""猎聘工作年限筛选项：自定义范围拆成平台标签，结果不足时依次换选。"""

from __future__ import annotations

import re

# 猎聘 LPT 常见单选年限（由窄到宽）
EXPERIENCE_LADDER = [
    "1年以下",
    "1-3年",
    "3-5年",
    "5-10年",
    "10年以上",
    "不限",
]

_LADDER_BOUNDS: list[tuple[str, int, int]] = [
    ("1年以下", 0, 1),
    ("1-3年", 1, 3),
    ("3-5年", 3, 5),
    ("5-10年", 5, 10),
    ("10年以上", 10, 999),
]

_ALIASES: dict[str, str] = {
    "不限": "不限",
    "经验不限": "不限",
    "工作经验不限": "不限",
    "不限经验": "不限",
    "1年以下": "1年以下",
    "1年以内": "1年以下",
    "应届": "1年以下",
    "1-3年": "1-3年",
    "1~3年": "1-3年",
    "1至3年": "1-3年",
    "3-5年": "3-5年",
    "3~5年": "3-5年",
    "3至5年": "3-5年",
    "5-10年": "5-10年",
    "5~10年": "5-10年",
    "5至10年": "5-10年",
    "10年以上": "10年以上",
    "10年+": "10年以上",
    "10+年": "10年以上",
}


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def parse_experience_range(text: str) -> tuple[int, int] | None:
    """解析「3-10年 / 3至10年」等区间。"""
    t = (text or "").strip()
    if t in _ALIASES:
        t = _ALIASES[t]
    if t in EXPERIENCE_LADDER:
        for label, lo, hi in _LADDER_BOUNDS:
            if label == t:
                return lo, hi
        if t == "不限":
            return None
    m = re.match(r"(\d+)\s*[-~至到]\s*(\d+)\s*年?", t)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi
    m = re.match(r"(\d+)\s*年\s*以上", t)
    if m:
        years = int(m.group(1))
        return years, 999
    return None


def ladder_options_intersecting(min_y: int, max_y: int) -> list[str]:
    """返回与 [min_y, max_y] 有实质交集的猎聘年限标签（按 ladder 顺序）。"""
    if min_y > max_y:
        min_y, max_y = max_y, min_y
    out: list[str] = []
    for label, lo, hi in _LADDER_BOUNDS:
        overlap_lo = max(lo, min_y)
        overlap_hi = min(hi, max_y)
        if overlap_lo < overlap_hi:
            out.append(label)
        elif overlap_lo == overlap_hi and lo >= min_y and overlap_lo == min_y:
            # 需求起点落在该段内（如 3-10 命中 3-5 的起点 3）；不含仅碰到上界的「10年以上」
            out.append(label)
    return out


def is_ladder_experience(exp: str) -> bool:
    return normalize_experience(exp) in EXPERIENCE_LADDER


def normalize_experience(exp: str) -> str:
    """规范用户输入文本（可能是平台标签，也可能是自定义区间）。"""
    text = (exp or "").strip()
    if not text:
        return "3-5年"
    if text in _ALIASES:
        return _ALIASES[text]
    m = re.match(r"(\d+)\s*[-~至到]\s*(\d+)\s*年?", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return f"{lo}-{hi}年"
    m = re.match(r"(\d+)\s*年\s*以上", text)
    if m:
        years = int(m.group(1))
        return "10年以上" if years >= 10 else f"{years}年以上"
    if "不限" in text:
        return "不限"
    return text


def primary_ladder_options(requested: str) -> list[str]:
    """把需求年限拆成猎聘页面上可点的标签（优先覆盖需求区间）。"""
    text = normalize_experience(requested)
    if text == "不限":
        return []
    if text in EXPERIENCE_LADDER:
        return [text]

    rng = parse_experience_range(text)
    if rng:
        covering = ladder_options_intersecting(rng[0], rng[1])
        if covering:
            return covering

    if text.endswith("年以上"):
        m = re.match(r"(\d+)", text)
        if m and int(m.group(1)) >= 10:
            return ["10年以上"]

    return ["3-5年"]


def experience_try_sequence(requested: str) -> list[str]:
    """需求年限内的猎聘标签尝试顺序：仅切换区间内的各段，不降级、不超出需求上下界。"""
    return primary_ladder_options(requested)


def initial_experience_filter(requested: str) -> str:
    """首次搜索使用的猎聘年限标签。"""
    seq = experience_try_sequence(requested)
    return seq[0] if seq else "不限"


def resolve_ladder_experience(exp: str) -> str:
    """确保返回猎聘可点击的单选标签。"""
    text = (exp or "").strip()
    norm = normalize_experience(text)
    if norm in EXPERIENCE_LADDER:
        return norm
    return initial_experience_filter(text)


def experience_relaxation_sequence(start: str) -> list[str]:
    """从当前 ladder 标签起，按「先扩邻段、最后不限」生成候选顺序。"""
    start = resolve_ladder_experience(start)
    if start == "不限":
        return []

    if start in EXPERIENCE_LADDER:
        idx = EXPERIENCE_LADDER.index(start)
        sequence: list[str] = []
        for i in range(idx + 1, len(EXPERIENCE_LADDER) - 1):
            sequence.append(EXPERIENCE_LADDER[i])
        for i in range(idx - 1, -1, -1):
            sequence.append(EXPERIENCE_LADDER[i])
        sequence.append("不限")
    else:
        sequence = [opt for opt in EXPERIENCE_LADDER if opt != start]

    seen = {start}
    out: list[str] = []
    for opt in sequence:
        norm = normalize_experience(opt)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def next_experience_fallback(
    current: str,
    tried: set[str],
    *,
    requested: str | None = None,
) -> str | None:
    tried_norm = {resolve_ladder_experience(t) for t in tried if t}
    source = (requested or current).strip()
    for opt in experience_try_sequence(source):
        if opt not in tried_norm:
            return opt
    return None
