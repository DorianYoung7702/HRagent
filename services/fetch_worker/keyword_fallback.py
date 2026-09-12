"""猎聘搜索关键词：结果过少时删减偏「初筛」而非「搜人」的标签后重搜。"""

from __future__ import annotations

import re

# 更适合写入 HR 评判标准、不宜放进猎聘搜索栏的词（优先删除）
SCREENING_ONLY_TERMS: tuple[str, ...] = (
    "电子类产品",
    "电子类",
    "电子产品",
    "电子",
    "企业软件行业",
    "企业软件",
    "渠道管理经验",
    "渠道管理",
    "渠道",
    "ToB端",
    "ToB",
    "拉美区域市场",
    "拉美区域",
    "拉美市场",
    "拉美",
    "中方销售",
    "销售经验",
    "工作经验",
    "产品类",
)

PROTECTED_SEARCH_TERMS: tuple[str, ...] = ("西班牙语", "销售")

FILTER_ONLY_TERMS: tuple[str, ...] = (
    "经验",
    "年经验",
    "工作年限",
    "工作经验",
    "不限经验",
    "经验不限",
    "不限",
    "简历",
    "候选人",
    "份",
)

CITY_TERMS: tuple[str, ...] = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "成都",
    "武汉",
    "南京",
    "苏州",
    "西安",
    "重庆",
    "天津",
    "长沙",
    "郑州",
    "青岛",
    "厦门",
    "宁波",
    "佛山",
    "东莞",
    "珠海",
    "惠州",
    "中山",
    "海外",
)

_SCREENING_ONLY_SORTED = sorted(SCREENING_ONLY_TERMS, key=len, reverse=True)
_FILTER_ONLY_WORDS = set(FILTER_ONLY_TERMS)
_CITY_WORDS = set(CITY_TERMS)


def split_keywords(keywords: str) -> list[str]:
    text = (keywords or "").strip()
    if not text:
        return []
    parts = text.split()
    if len(parts) > 1:
        return [p for p in parts if p]
    # 无空格时尝试按已知 screening 词切分
    tokens: list[str] = []
    rest = text
    while rest:
        matched = False
        for term in _SCREENING_ONLY_SORTED:
            if rest.startswith(term):
                tokens.append(term)
                rest = rest[len(term) :].strip()
                matched = True
                break
        if not matched:
            m = re.match(r"[\u4e00-\u9fffA-Za-z0-9]+", rest)
            if m:
                tokens.append(m.group(0))
                rest = rest[m.end() :].strip()
            else:
                break
    return tokens if tokens else [text]


def is_screening_only_term(term: str) -> bool:
    """仅精确匹配初筛向标签，避免误删「销售」等宽泛搜索词。"""
    return (term or "").strip() in SCREENING_ONLY_TERMS


def _clean_keyword_token(term: str) -> str:
    return (term or "").strip(" \t\r\n,，、;；:：/|()（）[]【】{}<>《》\"'“”‘’")


def is_filter_only_term(term: str) -> bool:
    """明显属于猎聘筛选控件的词，不进入搜索栏。"""
    t = _clean_keyword_token(term)
    if not t:
        return True
    if t in _FILTER_ONLY_WORDS or t in _CITY_WORDS:
        return True
    if re.fullmatch(r"\d+\s*[-~至到]\s*\d+\s*年(?:经验)?", t):
        return True
    if re.fullmatch(r"\d+\s*年(?:以上|以下|经验)?", t):
        return True
    if re.fullmatch(r"\d+\s*(?:份|个|人|条)(?:简历|候选人)?", t):
        return True
    if re.fullmatch(r"(?:目前|当前|现居|base|期望|意向|城市)[=:：]?\s*[\u4e00-\u9fff]{1,8}", t, re.I):
        return True
    return False


def is_protected_search_term(term: str) -> bool:
    """放宽搜索时不可删除的必要检索词。"""
    t = _clean_keyword_token(term)
    if t in ("西班牙语", "西语"):
        return True
    if t == "销售":
        return True
    if t.endswith("销售") and t not in SCREENING_ONLY_TERMS:
        return True
    return False


def tokens_have_spanish(tokens: list[str]) -> bool:
    return any(t in ("西班牙语", "西语") for t in tokens)


def tokens_have_sales(tokens: list[str]) -> bool:
    return any(t == "销售" or (t.endswith("销售") and t not in SCREENING_ONLY_TERMS) for t in tokens)


def _source_needs_spanish(source_text: str) -> bool:
    source = source_text or ""
    return any(k in source for k in ("西班牙语", "西语", "拉美"))


def _source_needs_sales(source_text: str) -> bool:
    return "销售" in (source_text or "")


def ensure_required_search_keywords(keywords: str, source_text: str = "") -> str:
    """按业务信号补全必要搜索词：西班牙语、销售。"""
    tokens = split_keywords(keywords)
    combined_source = f"{source_text} {keywords}".strip()

    if _source_needs_spanish(combined_source) and not tokens_have_spanish(tokens):
        tokens.append("西班牙语")
    if _source_needs_sales(combined_source) and not tokens_have_sales(tokens):
        tokens.append("销售")

    return join_keywords(tokens)


def dedupe_search_keyword_tokens(tokens: list[str]) -> list[str]:
    """去重；已有「海外销售」等复合词时去掉单独的「销售」。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        t = _clean_keyword_token(token)
        if not t or t in seen:
            continue
        seen.add(t)
        ordered.append(t)

    has_compound_sales = any(
        t.endswith("销售") and t != "销售" and t not in SCREENING_ONLY_TERMS
        for t in ordered
    )
    if has_compound_sales:
        ordered = [t for t in ordered if t != "销售"]
    return ordered


def join_keywords(tokens: list[str]) -> str:
    return " ".join(dedupe_search_keyword_tokens(tokens)).strip()


def keyword_relaxation_exhausted(keywords: str) -> bool:
    """是否已删到只剩必要检索词，不可再放宽。"""
    tokens = split_keywords(keywords)
    if not tokens:
        return True
    relaxable = [t for t in tokens if not is_protected_search_term(t)]
    return len(relaxable) == 0


def keyword_relaxation_candidates(start: str) -> list[str]:
    """生成依次删掉一个词后的关键词组合；初筛向标签优先删，必要词不删。"""
    tokens = split_keywords(start)
    if len(tokens) <= 1:
        return []

    options: list[tuple[int, int, str]] = []
    for i, token in enumerate(tokens):
        if is_protected_search_term(token):
            continue
        remaining = tokens[:i] + tokens[i + 1 :]
        new_kw = join_keywords(remaining)
        if not new_kw:
            continue
        priority = 0 if is_screening_only_term(token) else 1
        options.append((priority, -len(token), new_kw))

    options.sort()
    seen: set[str] = set()
    out: list[str] = []
    for _, _, kw in options:
        if kw not in seen and kw != start.strip():
            seen.add(kw)
            out.append(kw)
    return out


def next_keyword_fallback(current: str, tried: set[str]) -> str | None:
    tried_norm = {t.strip() for t in tried if t and t.strip()}
    for kw in keyword_relaxation_candidates(current):
        if kw not in tried_norm:
            return kw
    return None


def filter_keywords_for_search(keywords: str, source_text: str = "") -> str:
    """解析阶段：去掉明显属于初筛标签的搜索词，并补全必要检索词。"""
    tokens = split_keywords(keywords)
    kept = [
        _clean_keyword_token(t)
        for t in tokens
        if (
            not is_filter_only_term(t)
            and (not is_screening_only_term(t) or is_protected_search_term(t))
        )
    ]
    base = join_keywords(kept) if kept else join_keywords(tokens)
    return ensure_required_search_keywords(base, source_text)
