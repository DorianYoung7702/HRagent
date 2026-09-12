"""简历库列表行匹配（纯逻辑，便于单测）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from services.fetch_worker.im_contact_match import (
    _surname_matches_list_name,
    im_match_surname,
    parse_age_from_text,
)

_GENDER_RE = re.compile(r"(?<![\u4e00-\u9fff])(男|女)(?![\u4e00-\u9fff])")
_NAME_LIKE_RE = re.compile(
    r"^[\u4e00-\u9fff]{1,2}\*{1,4}$|^[\u4e00-\u9fff]{1,2}(?:先生|女士)$"
)
_NAME_IN_TEXT_RE = re.compile(
    r"[\u4e00-\u9fff]{1,2}\*{1,4}|[\u4e00-\u9fff]{1,2}(?:先生|女士)"
)
_SINGLE_SURNAME_RE = re.compile(r"^[\u4e00-\u9fff]$")
# 简历库姓名列也可能显示完整姓名，如「曾琴」（2~4 字）
_FULL_PERSON_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
_BLOCKED_NAME_TEXT = frozenset(
    {
        "未分组", "全部收藏", "追问", "观察", "候选", "管理", "搜索", "更多", "知道了",
        # 操作列按钮（2~4 字，否则会被当成完整姓名）
        "查看", "详情", "操作", "下载", "预览", "编辑", "删除", "简历", "沟通",
        "联系", "邀请", "置顶", "收藏", "分享", "面试", "新",
    }
)
_ACTION_LABELS = _BLOCKED_NAME_TEXT
_EDU_LEVELS = ("博士", "硕士", "本科", "大专", "MBA")
_COMPANY_HINTS = ("有限公司", "股份", "集团", "研究院", "科技", "生物", "医疗")
_COLLECT_TIME_RE = re.compile(
    r"(今天|昨天|刚刚|\d{1,2}:\d{2}|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}|\d{1,2}[-/月]\d{1,2})"
)

# 猎聘简历库表头 → 字段（lpt_adapter.LPT_RESUME_LIBRARY_TABLE_HEADERS 同步）
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("姓名",),
    "gender": ("性别",),
    "age": ("年龄",),
    "education": ("学历", "最高学历"),
    "title": ("目前职位", "职位", "当前职位"),
    "company": ("目前公司", "公司", "当前公司"),
    "collect_time": ("收藏时间", "时间", "收藏日期"),
}

# 四要素模糊匹配：每项相似度均 >= 此阈值则命中
FUZZY_FIELD_THRESHOLD = 0.8


def names_match(expected: str, actual: str) -> bool:
    a = (expected or "").strip()
    b = (actual or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    if a.replace("*", "") == b.replace("*", ""):
        return True
    sur_a = im_match_surname(a)
    if sur_a and _surname_matches_list_name(b, sur_a):
        return True
    sur_b = im_match_surname(b)
    if sur_b and _surname_matches_list_name(a, sur_b):
        return True
    return False


def parse_gender_from_text(text: str) -> str | None:
    if not text:
        return None
    m = _GENDER_RE.search(text.replace("｜", "|"))
    return m.group(1) if m else None


def normalize_education(text: str | None) -> str | None:
    if not text:
        return None
    for level in _EDU_LEVELS:
        if level in text:
            return level
    return text.strip()[:20] or None


def normalize_collect_time(text: str | None) -> str | None:
    if not text:
        return None
    raw = text.strip()
    m = _COLLECT_TIME_RE.search(raw)
    return (m.group(1) if m else raw)[:32]


def _same_day(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    for token in ("今天", "刚刚"):
        if token in a and token in b:
            return True
    return False


@dataclass
class ResumeLibraryMatchProfile:
    display_name: str
    surname: str | None = None
    gender: str | None = None
    age: int | None = None
    education: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    collect_time: str | None = None
    folder: str = ""  # 猎聘简历库侧栏岗位文件夹名
    parent_folder: str | None = None

    @classmethod
    def from_candidate(
        cls,
        *,
        display_name: str,
        current_title: str | None,
        current_company: str | None,
        education: str | None,
        screening_level: str | None,
        metadata: dict[str, Any] | None,
        captured_at: str | None = None,
        job_folder: str | None = None,
    ) -> ResumeLibraryMatchProfile:
        meta = metadata or {}
        raw_text = str(meta.get("card_text") or meta.get("raw_text") or "")
        gender = meta.get("gender") or parse_gender_from_text(raw_text)
        age_raw = meta.get("age") or meta.get("card_age")
        age = None
        if age_raw is not None:
            age = _coerce_age(age_raw)
        if age is None:
            age = extract_age_from_row_text(raw_text)

        from services.fetch_worker.collect_grouping import (
            is_decision_sidebar_label,
            resolve_collect_folder_tag,
        )

        folder_value = meta.get("resume_library_folder") or meta.get("collect_folder")
        folder = resolve_collect_folder_tag(
            parent_name=str(folder_value or job_folder or ""),
        )
        if not folder:
            legacy_parent = str(meta.get("resume_library_parent_folder") or "").strip()
            if legacy_parent and not is_decision_sidebar_label(legacy_parent):
                folder = legacy_parent
        parent_folder = None

        collect_time = (
            meta.get("collected_at")
            or meta.get("collect_time")
            or meta.get("chat_initiated_at")
            or captured_at
        )
        if collect_time and "T" in str(collect_time):
            try:
                dt = datetime.fromisoformat(str(collect_time).replace("Z", "+00:00"))
                collect_time = dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass

        surname = meta.get("person_surname") or im_match_surname(display_name or "")

        agent_parse = meta.get("agent_parse") or {}
        company = (
            agent_parse.get("current_company")
            or current_company
            or meta.get("current_company")
        )

        return cls(
            display_name=display_name or "",
            surname=surname or None,
            gender=str(gender) if gender else None,
            age=age,
            education=normalize_education(education or meta.get("education_level")),
            current_title=(current_title or meta.get("current_title") or "")[:80] or None,
            current_company=(company or "")[:80] or None,
            collect_time=normalize_collect_time(str(collect_time) if collect_time else None),
            folder=folder,
            parent_folder=parent_folder,
        )


@dataclass
class ResumeLibraryRow:
    name: str
    gender: str | None
    age: int | None
    education: str | None
    title: str | None
    company: str | None
    collect_time: str | None
    raw_text: str
    index: int = 0
    list_top: float | None = None


def _normalize_company(text: str | None) -> str:
    if not text:
        return ""
    s = re.sub(r"\s+", "", str(text))
    for suffix in ("股份有限公司", "有限公司", "有限责任公司", "集团"):
        s = s.replace(suffix, "")
    return s.strip()


def _company_key(text: str | None, *, min_len: int = 4) -> str:
    norm = _normalize_company(text)
    if len(norm) >= min_len:
        return norm[: min(len(norm), 8)]
    return norm


def company_matches_strict(expected: str | None, row: ResumeLibraryRow) -> bool:
    key = _company_key(expected)
    if not key or len(key) < 2:
        return False
    source = row.company if row.company else (row.raw_text or "")
    hay = _normalize_company(source)
    return key in hay


def surname_matches_strict(profile: ResumeLibraryMatchProfile, row: ResumeLibraryRow) -> bool:
    surname = profile.surname or im_match_surname(profile.display_name or "")
    if not surname:
        return names_match(profile.display_name, row.name)
    return _surname_matches_list_name(row.name, surname)


def age_matches_strict(profile: ResumeLibraryMatchProfile, row: ResumeLibraryRow) -> bool:
    if profile.age is None or row.age is None:
        return False
    return _coerce_age(profile.age) == _coerce_age(row.age)


def education_matches_strict(profile: ResumeLibraryMatchProfile, row: ResumeLibraryRow) -> bool:
    exp = normalize_education(profile.education)
    act = normalize_education(row.education)
    if not exp or not act:
        return False
    return exp == act


def row_matches_profile_strict(profile: ResumeLibraryMatchProfile, row: ResumeLibraryRow) -> bool:
    """四要素严格相等（单测/兼容）。"""
    return (
        surname_matches_strict(profile, row)
        and age_matches_strict(profile, row)
        and education_matches_strict(profile, row)
        and company_matches_strict(profile.current_company, row)
    )


def _text_similarity(a: str | None, b: str | None) -> float:
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        return max(0.85, len(shorter) / max(len(longer), 1))
    return SequenceMatcher(None, a, b).ratio()


def score_surname(profile: ResumeLibraryMatchProfile, row: ResumeLibraryRow) -> float:
    if surname_matches_strict(profile, row):
        return 1.0
    sur = profile.surname or im_match_surname(profile.display_name or "") or ""
    if sur and _surname_matches_list_name(row.name, sur):
        return 1.0
    return _text_similarity(sur or profile.display_name, row.name)


def score_age(profile: ResumeLibraryMatchProfile, row: ResumeLibraryRow) -> float:
    if profile.age is None or row.age is None:
        return 0.0
    pa, ra = _coerce_age(profile.age), _coerce_age(row.age)
    if pa is None or ra is None:
        return 0.0
    if pa == ra:
        return 1.0
    diff = abs(pa - ra)
    if diff == 1:
        return 0.92
    if diff == 2:
        return 0.84
    return max(0.0, 1.0 - diff / 6.0)


def score_education(profile: ResumeLibraryMatchProfile, row: ResumeLibraryRow) -> float:
    exp = normalize_education(profile.education)
    act = normalize_education(row.education)
    if not exp or not act:
        return 0.0
    if exp == act:
        return 1.0
    return _text_similarity(exp, act)


def _company_similarity(expected: str | None, actual: str | None) -> float:
    exp = _normalize_company(expected)
    hay = _normalize_company(actual)
    if not exp or not hay:
        return 0.0
    if exp in hay or hay in exp:
        shorter, longer = (exp, hay) if len(exp) <= len(hay) else (hay, exp)
        return max(0.85, len(shorter) / max(len(longer), 1))
    return SequenceMatcher(None, exp, hay).ratio()


def _company_haystack_candidates(row: ResumeLibraryRow) -> list[str]:
    """公司字段可能误解析为职位，从多来源收集候选再比相似度。"""
    seen: set[str] = set()
    out: list[str] = []

    def add(val: str | None) -> None:
        v = (val or "").strip()
        if not v or v in seen:
            return
        seen.add(v)
        out.append(v)

    add(row.company)
    add(_guess_company_from_text(row.raw_text or ""))
    for part in re.split(r"[\n|]", row.raw_text or ""):
        p = part.strip()
        if _looks_like_company(p):
            add(p)
    if not out and row.raw_text:
        add(row.raw_text)
    return out


def score_company(expected: str | None, row: ResumeLibraryRow) -> float:
    if not (expected or "").strip():
        return 0.0
    best = 0.0
    for hay_source in _company_haystack_candidates(row):
        best = max(best, _company_similarity(expected, hay_source))
    return best


@dataclass
class RowMatchScores:
    surname: float
    age: float
    education: float
    company: float

    @property
    def min_score(self) -> float:
        return min(self.surname, self.age, self.education, self.company)

    @property
    def avg_score(self) -> float:
        return (self.surname + self.age + self.education + self.company) / 4.0

    def all_above(self, threshold: float = FUZZY_FIELD_THRESHOLD) -> bool:
        return self.min_score >= threshold

    def as_dict(self) -> dict[str, float]:
        return {
            "surname": round(self.surname, 3),
            "age": round(self.age, 3),
            "education": round(self.education, 3),
            "company": round(self.company, 3),
            "min": round(self.min_score, 3),
        }


def score_row_fields(
    profile: ResumeLibraryMatchProfile,
    row: ResumeLibraryRow,
) -> RowMatchScores:
    return RowMatchScores(
        surname=score_surname(profile, row),
        age=score_age(profile, row),
        education=score_education(profile, row),
        company=score_company(profile.current_company, row),
    )


def find_resume_library_row(
    profile: ResumeLibraryMatchProfile,
    rows: list[ResumeLibraryRow],
    *,
    threshold: float = FUZZY_FIELD_THRESHOLD,
) -> tuple[ResumeLibraryRow | None, RowMatchScores | None]:
    """四要素模糊匹配：姓氏/年龄/学历/公司相似度均 >= threshold 则命中。"""
    if not rows:
        return None, None

    ranked: list[tuple[ResumeLibraryRow, RowMatchScores]] = [
        (row, score_row_fields(profile, row)) for row in rows
    ]
    ranked.sort(key=lambda item: (-item[1].min_score, -item[1].avg_score))

    qualified = [item for item in ranked if item[1].all_above(threshold)]
    if not qualified:
        return None, ranked[0][1] if ranked else None

    if len(qualified) == 1:
        return qualified[0][0], qualified[0][1]

    best, second = qualified[0], qualified[1]
    if (
        best[1].min_score - second[1].min_score >= 0.03
        or best[1].avg_score - second[1].avg_score >= 0.05
    ):
        return best[0], best[1]

    names = ", ".join(r[0].name for r in qualified[:3])
    raise ValueError(
        f"当前页存在 {len(qualified)} 条均达到 {threshold:.0%} 相似度的记录（{names}…），请人工确认。"
    )


def validate_profile_for_library_match(profile: ResumeLibraryMatchProfile) -> None:
    missing: list[str] = []
    if not (profile.surname or im_match_surname(profile.display_name or "")):
        missing.append("姓氏")
    if profile.age is None:
        missing.append("年龄")
    if not normalize_education(profile.education):
        missing.append("最高学历")
    if not _company_key(profile.current_company):
        missing.append("目前公司")
    if missing:
        raise ValueError(
            f"跳转简历库缺少匹配字段：{'、'.join(missing)}。"
            f"请确认抓取时已记录年龄、学历与公司。"
        )


def find_strict_resume_library_row(
    profile: ResumeLibraryMatchProfile,
    rows: list[ResumeLibraryRow],
) -> ResumeLibraryRow | None:
    hits = [row for row in rows if row_matches_profile_strict(profile, row)]
    if not hits:
        return None
    if len(hits) > 1:
        names = ", ".join(r.name for r in hits[:3])
        raise ValueError(
            f"当前页存在 {len(hits)} 条同时满足四要素的记录（{names}…），请人工确认。"
        )
    return hits[0]


def score_resume_library_row(profile: ResumeLibraryMatchProfile, row: ResumeLibraryRow) -> float:
    """返回四要素最低相似度（均 >= FUZZY_FIELD_THRESHOLD 视为命中）。"""
    scores = score_row_fields(profile, row)
    return scores.min_score if scores.all_above() else -1.0


def pick_best_resume_library_row(
    profile: ResumeLibraryMatchProfile,
    rows: list[ResumeLibraryRow],
) -> tuple[ResumeLibraryRow | None, float]:
    try:
        hit, scores = find_resume_library_row(profile, rows)
    except ValueError:
        raise
    if hit and scores:
        return hit, scores.min_score
    return None, -1.0


def is_resume_library_name(text: str) -> bool:
    t = (text or "").strip()
    if not t or t in _BLOCKED_NAME_TEXT or "未分组" in t:
        return False
    if t in _EDU_LEVELS or t in ("男", "女", "更多", "操作"):
        return False
    if _NAME_LIKE_RE.match(t):
        return True
    if _SINGLE_SURNAME_RE.match(t):
        return True
    if _FULL_PERSON_NAME_RE.match(t):
        return True
    return False


def _pick_name_from_cells(cells: list[str]) -> str | None:
    """从单元格中选取姓名（跳过「查看」等操作列，优先 * / 先生女士 / 后接性别年龄）。"""
    candidates: list[tuple[int, int, str]] = []
    for i, raw in enumerate(cells):
        c = (raw or "").strip()
        if not c or not is_resume_library_name(c):
            continue
        score = 0
        if _NAME_LIKE_RE.match(c):
            score += 4
        elif _SINGLE_SURNAME_RE.match(c):
            score += 3
        elif _FULL_PERSON_NAME_RE.match(c):
            score += 2
        tail = [(x or "").strip() for x in cells[i + 1 : i + 4]]
        if tail and tail[0] in ("男", "女"):
            score += 4
        if any(re.fullmatch(r"\d{1,2}(?:岁)?", x) for x in tail):
            score += 3
        candidates.append((score, i, c))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def extract_name_from_row_text(text: str) -> str | None:
    """从整行文本中提取姓名（陈** / 梁先生 / 曾琴 / 单字「陈」）。"""
    if not text:
        return None
    t = text.replace("｜", "|")
    for m in _NAME_IN_TEXT_RE.finditer(t):
        candidate = m.group(0)
        if is_resume_library_name(candidate):
            return candidate
    m = re.match(r"^([\u4e00-\u9fff]{2,4})\s*(?:男|女|\||\s|\d)", t)
    if m and is_resume_library_name(m.group(1)):
        return m.group(1)
    m = re.match(r"^([\u4e00-\u9fff])\s*(?:男|女|\||\s|\d)", t)
    if m and is_resume_library_name(m.group(1)):
        return m.group(1)
    return None


def _row_has_age(text: str) -> bool:
    if re.search(r"\d{1,2}岁", text):
        return True
    return bool(re.search(r"(?:^|[\s|/])\d{1,2}(?:[\s|/]|$)", text))


def extract_age_from_row_text(text: str) -> int | None:
    """从简历库行文本解析年龄（支持「25岁」与「女 25 本科」等无「岁」写法）。"""
    if not text:
        return None
    t = text.replace("｜", "|")
    m = re.search(r"(\d{1,2})\s*岁", t)
    if m:
        return _coerce_age(m.group(1))
    m = re.search(r"(?<![\u4e00-\u9fff])(男|女)\s+(\d{1,2})\b", t)
    if m:
        return _coerce_age(m.group(2))
    m = re.search(r"(?:^|[\s|/])(\d{1,2})(?:[\s|/]|$)", t)
    if m:
        age = _coerce_age(m.group(1))
        if age is not None and 16 <= age <= 65:
            return age
    return _coerce_age(parse_age_from_text(t))


def looks_like_candidate_row_text(text: str) -> bool:
    """启发式：整行是否像简历库收藏列表中的一条记录。"""
    if not text:
        return False
    t = text.replace("｜", "|")
    if any(k in t for k in ("未分组", "全部收藏", "简历编号", "姓名 性别", "搜索", "管理")):
        return False
    if len(t) < 4 or len(t) > 500:
        return False
    if not extract_name_from_row_text(t):
        return False
    if not _GENDER_RE.search(t):
        return False
    if not _row_has_age(t):
        return False
    if not any(level in t for level in _EDU_LEVELS):
        return False
    return True


def looks_like_structured_cells(cells: list[str]) -> bool:
    """表格分列：姓名 / 性别 / 年龄 / …"""
    if len(cells) < 3:
        return False
    name = (cells[0] or "").strip()
    if not is_resume_library_name(name):
        return False
    if cells[1] not in ("男", "女") and not _GENDER_RE.search(" ".join(cells)):
        return False
    age_cell = (cells[2] or "").strip()
    if not (re.fullmatch(r"\d{1,2}(?:岁)?", age_cell) or _row_has_age(" ".join(cells))):
        return False
    if not any(level in " ".join(cells) for level in _EDU_LEVELS):
        return False
    return True


def _coerce_age(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace("岁", "").strip())
    except ValueError:
        return None


def _looks_like_company(text: str | None) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return False
    if any(h in t for h in _COMPANY_HINTS):
        return True
    if re.search(r"[\u4e00-\u9fff]{2,}(公司|集团|研究院|大学|有限)", t):
        return True
    return len(t) >= 8 and not any(level in t for level in _EDU_LEVELS)


def _header_field_index(headers: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for field, aliases in _HEADER_ALIASES.items():
        for i, raw in enumerate(headers):
            h = (raw or "").strip()
            if not h:
                continue
            if any(a == h or a in h for a in aliases):
                idx[field] = i
                break
    return idx


def _cell_at(cells: list[str], index: int | None) -> str | None:
    if index is None or index < 0 or index >= len(cells):
        return None
    v = (cells[index] or "").strip()
    return v or None


def _best_company_from_cells(cells: list[str]) -> str | None:
    """职位列常在 company 列前；取最后一个像公司的单元格。"""
    hits = [c.strip() for c in cells if _looks_like_company((c or "").strip())]
    return hits[-1] if hits else None


def parse_row_from_header_cells(
    headers: list[str],
    cells: list[str],
    index: int = 0,
) -> ResumeLibraryRow | None:
    """按表头列名映射（避免全宽表格左侧列导致下标错位）。"""
    if not cells:
        return None
    col = _header_field_index(headers)
    if "name" not in col:
        return None
    name = _cell_at(cells, col.get("name"))
    if not name or not is_resume_library_name(name):
        name = _pick_name_from_cells(cells)
    if not name or not is_resume_library_name(name):
        return None
    joined = " | ".join(cells)
    gender = _cell_at(cells, col.get("gender"))
    if gender not in ("男", "女"):
        gender = parse_gender_from_text(joined)
    age_raw = _cell_at(cells, col.get("age"))
    age = _coerce_age(age_raw) or extract_age_from_row_text(age_raw or "")
    education = normalize_education(_cell_at(cells, col.get("education")) or joined)
    title = _cell_at(cells, col.get("title"))
    company = _cell_at(cells, col.get("company"))
    if company and not _looks_like_company(company):
        company = None
    if not company:
        company = _best_company_from_cells(cells)
    if not company:
        company = _guess_company_from_text(joined)
    collect_time = normalize_collect_time(_cell_at(cells, col.get("collect_time")))
    return ResumeLibraryRow(
        name=name,
        gender=gender,
        age=age,
        education=education,
        title=title,
        company=company,
        collect_time=collect_time,
        raw_text=joined,
        index=index,
        list_top=None,
    )


def parse_row_from_semantic_cells(cells: list[str], index: int = 0) -> ResumeLibraryRow | None:
    """按单元格内容语义识别字段（兼容前置勾选列/操作列）。"""
    cleaned = [(c or "").strip() for c in cells if (c or "").strip()]
    if len(cleaned) < 3:
        return None
    if cleaned[0] in ("姓名", "简历编号") or "姓名" in cleaned[0]:
        return None

    name: str | None = _pick_name_from_cells(cleaned)
    gender: str | None = None
    age: int | None = None
    education: str | None = None
    collect_time: str | None = None
    leftovers: list[str] = []

    for cell in cleaned:
        if cell == name:
            continue
        if cell in ("男", "女"):
            gender = cell
            continue
        if age is None and re.fullmatch(r"\d{1,2}(?:岁)?", cell):
            age = _coerce_age(cell)
            continue
        if education is None and any(level in cell for level in _EDU_LEVELS):
            education = normalize_education(cell)
            continue
        if collect_time is None and _COLLECT_TIME_RE.search(cell):
            collect_time = normalize_collect_time(cell)
            continue
        leftovers.append(cell)

    if not name:
        name = extract_name_from_row_text(" ".join(cleaned))
    if not name or not is_resume_library_name(name):
        return None

    company = _best_company_from_cells(leftovers)
    title: str | None = None
    for cell in leftovers:
        if cell == company:
            continue
        if len(cell) >= 2 and not _COLLECT_TIME_RE.search(cell):
            title = cell
            break

    joined = " | ".join(cleaned)
    if not company:
        company = _guess_company_from_text(joined)
    if not education:
        education = normalize_education(joined)
    if age is None:
        age = extract_age_from_row_text(joined)
    if not gender:
        gender = parse_gender_from_text(joined)

    return ResumeLibraryRow(
        name=name,
        gender=gender,
        age=age,
        education=education,
        title=title,
        company=company,
        collect_time=collect_time,
        raw_text=joined,
        index=index,
        list_top=None,
    )


def _guess_company_from_text(text: str) -> str | None:
    """简历库列表：分列取第 6 列；整行文本则自右向左跳过时间/年龄/学历等短字段。"""
    if not text:
        return None
    parts = [p.strip() for p in re.split(r"[\n|]", text) if p.strip()]
    if len(parts) >= 6:
        return parts[5][:80]
    tokens = text.split()
    for token in reversed(tokens):
        token = token.strip()
        if not token or len(token) < 2:
            continue
        if _COLLECT_TIME_RE.search(token):
            continue
        if token.endswith("岁") or token in _EDU_LEVELS or token in ("男", "女"):
            continue
        if is_resume_library_name(token):
            continue
        if _looks_like_company(token):
            return token[:80]
        return token[:80]
    return None


def parse_row_from_full_text(text: str, index: int = 0) -> ResumeLibraryRow | None:
    """从整行文本解析（姓名与其它字段在同一行，无独立姓名 link）。"""
    text = (text or "").strip()
    if not looks_like_candidate_row_text(text):
        return None
    name = extract_name_from_row_text(text)
    if not name:
        return None
    return parse_row_from_list_text(name, text, index=index)


def parse_row_from_list_text(name: str, text: str, index: int = 0) -> ResumeLibraryRow | None:
    """从右侧 name link + 同行/父级文本解析（无完整表头时使用）。"""
    name = (name or "").strip()
    if not is_resume_library_name(name):
        name = extract_name_from_row_text(text or "") or ""
    if not is_resume_library_name(name):
        return None
    joined = f"{name} {text or ''}".strip()
    gender = parse_gender_from_text(joined)
    age = extract_age_from_row_text(joined)
    education = normalize_education(joined)
    company = _guess_company_from_text(joined)
    if not company:
        company = _guess_company_from_text(text or "")
    collect_time = None
    m = _COLLECT_TIME_RE.search(joined)
    if m:
        collect_time = normalize_collect_time(m.group(0))
    return ResumeLibraryRow(
        name=name,
        gender=gender,
        age=age,
        education=education,
        title=None,
        company=company,
        collect_time=collect_time,
        raw_text=joined[:400],
        index=index,
        list_top=None,
    )


def _header_row_sane(row: ResumeLibraryRow) -> bool:
    """表头映射结果是否自洽（防止前置操作列导致年龄/学历/公司列错位）。"""
    if row.age is None:
        return False
    edu = row.education or ""
    if not any(level in edu for level in _EDU_LEVELS):
        return False
    if row.company and not _looks_like_company(row.company):
        return False
    return True


def _align_cells_to_headers(headers: list[str], cells: list[str]) -> list[str]:
    """去掉表头前/后的操作列，使 cells 与 headers 对齐。"""
    cleaned = [(c or "").strip() for c in cells if (c or "").strip() or c == ""]
    trimmed = list(cleaned)
    while trimmed and trimmed[-1] in _ACTION_LABELS:
        trimmed.pop()
    if not headers or len(trimmed) <= len(headers):
        return trimmed
    col = _header_field_index(headers)
    name_idx = col.get("name", 0)
    while len(trimmed) > len(headers):
        shorter = trimmed[1:]
        if len(shorter) < len(headers):
            break
        name_cell = shorter[name_idx] if name_idx < len(shorter) else ""
        if is_resume_library_name(name_cell):
            trimmed = shorter[: len(headers)]
            continue
        break
    if len(trimmed) > len(headers):
        trimmed = trimmed[: len(headers)]
    return trimmed


def parse_row_from_cells(
    cells: list[str],
    index: int = 0,
    *,
    headers: list[str] | None = None,
) -> ResumeLibraryRow | None:
    if not cells:
        return None
    if len(cells) == 1:
        return parse_row_from_full_text(cells[0], index=index)

    if headers:
        aligned = _align_cells_to_headers(headers, cells)
        by_header = parse_row_from_header_cells(headers, aligned, index=index)
        if by_header and _header_row_sane(by_header):
            return by_header

    by_semantic = parse_row_from_semantic_cells(cells, index=index)
    if by_semantic:
        return by_semantic

    if looks_like_structured_cells(cells):
        joined = " | ".join(cells)
        name = cells[0].strip()
        gender = cells[1] if cells[1] in ("男", "女") else parse_gender_from_text(joined)
        age = _coerce_age(cells[2]) or extract_age_from_row_text(cells[2])
        education = normalize_education(cells[3]) if len(cells) > 3 else normalize_education(joined)
        title = cells[4].strip() if len(cells) > 4 else None
        company = cells[5].strip() if len(cells) > 5 else None
        collect_time = normalize_collect_time(cells[6]) if len(cells) > 6 else None
        if not company:
            company = _guess_company_from_text(joined)
        return ResumeLibraryRow(
            name=name,
            gender=gender,
            age=age,
            education=education,
            title=title or None,
            company=company or None,
            collect_time=collect_time,
            raw_text=joined,
            index=index,
            list_top=None,
        )
    joined = " ".join(cells)
    name = cells[0].strip()
    if not is_resume_library_name(name):
        name = extract_name_from_row_text(joined) or ""
    if not name or len(name) > 20:
        return None

    gender = parse_gender_from_text(joined)
    age = extract_age_from_row_text(joined)
    education = normalize_education(joined)

    title = None
    company = None
    collect_time = None

    for cell in cells[1:]:
        if cell in ("男", "女") and not gender:
            gender = cell
        elif re.fullmatch(r"\d{1,2}(?:岁)?", (cell or "").strip()) and age is None:
            age = _coerce_age(cell)
        elif any(level in cell for level in _EDU_LEVELS) and not education:
            education = normalize_education(cell)
        elif _COLLECT_TIME_RE.search(cell):
            collect_time = normalize_collect_time(cell)
        elif _looks_like_company(cell) and not company:
            company = cell
        elif len(cell) >= 2 and not title and cell not in (gender,):
            title = cell

    return ResumeLibraryRow(
        name=name,
        gender=gender,
        age=age,
        education=education,
        title=title,
        company=company,
        collect_time=collect_time,
        raw_text=joined,
        index=index,
        list_top=None,
    )
