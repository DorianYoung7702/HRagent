"""猎聘 IM 列表项匹配：姓氏 + 年龄/学校 + 开聊时间（与 LPT 卡片/我发起的列表一致）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_CN_TZ = timezone(timedelta(hours=8))

_AGE_RE = re.compile(r"(\d{1,2})\s*岁")
_SCHOOL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]{2,20}(?:大学|学院|学校)")
_EDU_LEVELS = ("博士", "硕士", "本科", "大专", "MBA")
_COMPANY_MARKERS = (
    "有限公司",
    "股份有限公司",
    "有限责任公司",
    "集团公司",
    "控股集团",
    "实业",
    "研究院",
    "研究所",
)
_PERSON_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,3}(?:[·•][A-Za-z\u4e00-\u9fff]{1,20})?$")
_MASKED_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{1,2}\*{1,4}$")
_TIME_HM_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_JUST_NOW_RE = re.compile(r"刚刚")
_MINUTES_AGO_RE = re.compile(r"(\d+)\s*分钟前")
_HOURS_AGO_RE = re.compile(r"(\d+)\s*小时前")
_SKIP_NAME_LINE_KEYWORDS = (
    "活跃",
    "在线",
    "沟通",
    "收藏",
    "查看",
    "简历",
    "薪",
    "K·",
    "大学",
    "学院",
    "本科",
    "硕士",
    "博士",
    "大专",
    "专员",
    "经理",
    "工程师",
    "主管",
    "总监",
    "销售",
    "采购",
    "运营",
    "翻译",
)
# 猎聘卡片上常见非姓名短词（城市、行业、占位符等）
_NON_PERSON_SHORT_TERMS = frozenset({
    "医疗器械",
    "西班牙语",
    "德语",
    "法语",
    "日语",
    "韩语",
    "英语",
    "今日活跃",
    "日内活跃",
    "查看大图",
    "立即沟通",
    "家用电器",
    "通信设备",
    "智能硬件",
    "消费电子",
    "跨境电商",
    "国际贸易",
    "海外市场",
    "隐藏",
    "未知",
    "候选人",
    "姓名隐藏",
    "未公开",
    "深圳",
    "北京",
    "上海",
    "广州",
    "杭州",
    "成都",
    "武汉",
    "南京",
    "西安",
    "苏州",
    "东莞",
    "佛山",
    "惠州",
    "中山",
    "珠海",
    "厦门",
    "青岛",
    "大连",
    "沈阳",
    "天津",
    "重庆",
    "长沙",
    "郑州",
    "合肥",
    "昆明",
    "南宁",
    "石家庄",
    "太原",
    "济南",
    "福州",
    "南昌",
    "贵阳",
    "兰州",
    "海口",
    "广东",
    "浙江",
    "江苏",
    "山东",
    "河南",
    "四川",
    "湖北",
    "湖南",
    "内蒙古",
    "黑龙江",
    "吉林",
    "辽宁",
    "佛山",
    "宁波",
    "无锡",
    "常州",
    "温州",
    "烟台",
    "潍坊",
    "南通",
    "徐州",
    "义乌",
    "台州",
    "销售总监",
    "销售经理",
    "产品经理",
    "项目经理",
    "商务经理",
    "运营经理",
    "采购专员",
    "外贸专员",
})
_JOB_TITLE_RE = re.compile(
    r"(总监|经理|专员|主管|工程师|顾问|总监|总监|助理|代表|总监)$"
)
_INVALID_NAME_PLACEHOLDERS = frozenset({"隐藏", "未知", "候选人", "姓名隐藏", "未公开", "—", "-"})


def is_invalid_name_placeholder(text: str | None) -> bool:
    t = (text or "").strip()
    return not t or t in _INVALID_NAME_PLACEHOLDERS


def is_masked_person_name(text: str | None) -> bool:
    return bool(_MASKED_NAME_RE.match((text or "").strip()))


def extract_masked_name_from_text(text: str | None) -> str | None:
    """猎聘列表/弹窗常见脱敏姓名：张**、李**。"""
    if not text:
        return None
    for chunk in re.split(r"[\n|/]+", text):
        part = chunk.strip()
        if is_masked_person_name(part):
            return part
    m = re.search(r"[\u4e00-\u9fff]{1,2}\*{1,4}", text)
    return m.group(0) if m else None


def is_likely_company_name(text: str | None) -> bool:
    """区分姓名 vs 公司名（IM/卡片解析用，不用于抽取当前雇主）。"""
    t = (text or "").strip()
    if not t:
        return False
    if any(m in t for m in _COMPANY_MARKERS):
        return True
    if "公司" in t and len(t) >= 5:
        return True
    if len(t) > 8:
        return True
    return False


def is_likely_job_title(text: str | None) -> bool:
    t = (text or "").strip()
    return bool(t and _JOB_TITLE_RE.search(t))


def is_likely_person_name(text: str | None) -> bool:
    t = (text or "").strip()
    if not t or is_likely_company_name(t):
        return False
    if is_invalid_name_placeholder(t):
        return False
    if is_masked_person_name(t):
        return True
    if t in _NON_PERSON_SHORT_TERMS:
        return False
    if is_likely_job_title(t):
        return False
    if len(t) > 6:
        return False
    if _PERSON_NAME_RE.match(t):
        return True
    if re.match(r"^[\u4e00-\u9fff]{2,3}$", t):
        return True
    return False


def im_match_label(name: str | None) -> str:
    """日志/提示用：脱敏名只显示姓氏（刘** → 刘）。"""
    n = (name or "").strip()
    if not n:
        return "未知"
    if is_masked_person_name(n):
        return person_surname(n) or n
    if is_likely_person_name(n):
        return n
    sur = person_surname(n)
    return sur if sur else n


def im_match_surname(name: str | None) -> str | None:
    """IM 列表匹配用姓氏（张** → 张）。"""
    n = (name or "").strip()
    if not n:
        return None
    if is_masked_person_name(n):
        return person_surname(n)
    return person_surname(n)


def _surname_matches_list_name(text: str, surname: str | None) -> bool:
    """列表行是否以该姓氏开头（支持 刘 / 刘** / 刘先生）。"""
    if not surname:
        return False
    t = (text or "").strip()
    if not t:
        return False
    esc = re.escape(surname)
    if re.match(rf"^{esc}(\*{{1,4}}|先生|女士)?", t):
        return True
    # 完整姓名：曾琴、欧阳娜娜（列表可能不脱敏）
    if re.match(rf"^{esc}[\u4e00-\u9fff]{{0,3}}$", t) and len(t) <= 4:
        return True
    return bool(re.search(rf"(?:^|[\s|/·]){esc}(\*{{1,4}}|先生|女士)?", t))


def parse_im_list_time(text: str, reference: datetime | None = None) -> datetime | None:
    """从 IM 列表行解析时间（刚刚 / N分钟前 / HH:MM）。"""
    ref = reference or datetime.now(_CN_TZ)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_CN_TZ)

    if _JUST_NOW_RE.search(text):
        return ref

    m = _MINUTES_AGO_RE.search(text)
    if m:
        return ref - timedelta(minutes=int(m.group(1)))

    m = _HOURS_AGO_RE.search(text)
    if m:
        return ref - timedelta(hours=int(m.group(1)))

    m = _TIME_HM_RE.search(text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        candidate = ref.replace(hour=h, minute=mi, second=0, microsecond=0)
        if candidate > ref + timedelta(minutes=5):
            candidate -= timedelta(days=1)
        return candidate

    return None


def _parse_initiated_at(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CN_TZ)
    return dt.astimezone(_CN_TZ)


def time_proximity_score(
    list_text: str,
    chat_initiated_at: str | datetime | None,
    *,
    reference: datetime | None = None,
) -> int:
    """开聊时间与列表行时间的接近程度加分。"""
    initiated = _parse_initiated_at(chat_initiated_at)
    if initiated is None:
        return 0
    ref = reference or datetime.now(_CN_TZ)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_CN_TZ)
    list_time = parse_im_list_time(list_text, ref)
    if list_time is None:
        return 0
    diff = abs((list_time - initiated).total_seconds())
    if diff <= 120:
        return 20
    if diff <= 300:
        return 12
    if diff <= 600:
        return 6
    return 0


def person_surname(name: str | None) -> str | None:
    """中文姓名取姓氏（首字），用于 IM 列表匹配兜底。"""
    n = (name or "").strip()
    if not n or is_likely_company_name(n):
        return None
    if re.match(r"^[\u4e00-\u9fff]", n):
        return n[0]
    return None


def resolve_person_name(
    *names: str | None,
    lines: list[str] | str | None = None,
) -> str | None:
    """从卡片预览/弹窗等多源中选出最可信的人名。"""
    for n in names:
        if n and is_likely_person_name(n):
            return n.strip()
    if lines:
        parsed = parse_name_from_card(lines)
        if parsed and is_likely_person_name(parsed):
            return parsed
    return None


def extract_person_name_from_text(text: str | None) -> str | None:
    """从卡片/简历文本提取人名（含猎聘脱敏张**）。"""
    if not text:
        return None
    masked = extract_masked_name_from_text(text)
    if masked:
        return masked
    return parse_name_from_card(text)


def _snapshot_text_sources(snap) -> list[str]:
    meta = (getattr(snap, "metadata_", None) or getattr(snap, "metadata", None) or {}) or {}
    sources: list[str] = []
    card_text = meta.get("card_text")
    if card_text:
        sources.append(str(card_text))
    raw = getattr(snap, "raw_text", None) or ""
    if raw:
        sources.append(str(raw)[:2000])
    return sources


def resolve_person_raw_name(snap) -> str | None:
    """解析匹配用姓名（张**/王磊）：优先 card_text，不信任污染的 metadata。"""
    meta = (getattr(snap, "metadata_", None) or getattr(snap, "metadata", None) or {}) or {}

    for text in _snapshot_text_sources(snap):
        masked = extract_masked_name_from_text(text)
        if masked:
            return masked
        parsed = parse_name_from_card(text)
        if parsed and is_likely_person_name(parsed):
            return parsed

    for key in ("person_name", "card_name"):
        val = meta.get(key)
        if val and is_likely_person_name(val):
            return str(val).strip()

    dn = getattr(snap, "display_name", None)
    if dn and is_likely_person_name(dn):
        return str(dn).strip()

    return None


def format_candidate_list_name(name: str | None) -> str | None:
    """列表展示：脱敏名只保留姓氏（张** → 张）。"""
    if not name or is_invalid_name_placeholder(name):
        return None
    if is_masked_person_name(name):
        return person_surname(name)
    if is_likely_person_name(name):
        return name
    sur = person_surname(name)
    return sur if sur and not is_invalid_name_placeholder(sur) else None


def resolve_person_display_name(snap) -> str | None:
    """IM 匹配用姓名（保留张** 便于列表项精确匹配）。"""
    return resolve_person_raw_name(snap)


def candidate_display_name(snap) -> str:
    """候选人列表展示名：至少姓氏，绝不显示隐藏/城市/公司。"""
    raw = resolve_person_raw_name(snap)
    label = format_candidate_list_name(raw)
    return label or "未知"


@dataclass
class IMContactMatchFields:
    display_name: str | None = None
    age: str | None = None
    school: str | None = None
    education: str | None = None
    chat_initiated_at: str | None = None

    @classmethod
    def from_snapshot(cls, snap) -> IMContactMatchFields:
        meta = (getattr(snap, "metadata_", None) or getattr(snap, "metadata", None) or {}) or {}
        school = meta.get("school") or meta.get("card_school")
        edu = getattr(snap, "education", None) or meta.get("education_level")
        if not school and edu:
            school = _extract_school_name(str(edu))
        return cls(
            display_name=resolve_person_raw_name(snap),
            age=_normalize_age(meta.get("age") or meta.get("card_age")),
            school=school,
            education=edu if isinstance(edu, str) and len(edu) <= 8 else None,
            chat_initiated_at=meta.get("chat_initiated_at"),
        )

    @classmethod
    def from_card_text(cls, text: str, display_name: str | None = None) -> IMContactMatchFields:
        return cls(
            display_name=display_name or parse_name_from_card(text),
            age=parse_age_from_text(text),
            school=parse_school_from_text(text),
            education=parse_education_level(text),
        )


def _normalize_age(age) -> str | None:
    if age is None:
        return None
    s = str(age).strip().replace("岁", "")
    return s if s.isdigit() else None


def parse_age_from_text(text: str) -> str | None:
    m = _AGE_RE.search(text or "")
    return m.group(1) if m else None


def parse_education_level(text: str) -> str | None:
    for edu in _EDU_LEVELS:
        if edu in (text or ""):
            return edu
    return None


def _extract_school_name(text: str) -> str | None:
    m = _SCHOOL_RE.search(text or "")
    return m.group(0) if m else None


def parse_school_from_text(text: str) -> str | None:
    if not text:
        return None
    m = _SCHOOL_RE.search(text)
    if m:
        return m.group(0)
    for line in text.split("\n"):
        line = line.strip()
        if "大学" in line or "学院" in line:
            sm = _SCHOOL_RE.search(line)
            if sm:
                return sm.group(0)
    return None


def _line_looks_like_name_candidate(line: str) -> bool:
    if not line or len(line) > 20:
        return False
    if is_likely_company_name(line):
        return False
    if line in _NON_PERSON_SHORT_TERMS:
        return False
    if _AGE_RE.search(line):
        return False
    if any(k in line for k in _SKIP_NAME_LINE_KEYWORDS):
        return False
    if line in ("沟通", "立即沟通", "收藏", "已收藏", "查看大图", "查看简历"):
        return False
    if is_invalid_name_placeholder(line):
        return False
    if is_likely_job_title(line):
        return False
    return True


def parse_name_from_card(lines: list[str] | str) -> str | None:
    if isinstance(lines, str):
        text = lines
        masked = extract_masked_name_from_text(text)
        if masked:
            return masked
        lines = [line.strip() for line in text.split("\n") if line.strip()]
    for line in lines:
        if not _line_looks_like_name_candidate(line):
            continue
        if is_masked_person_name(line):
            return line
    for line in lines:
        if not _line_looks_like_name_candidate(line):
            continue
        if is_likely_person_name(line):
            return line
    return None


def build_im_contact_key(
    display_name: str | None,
    age: str | None = None,
    school: str | None = None,
    *,
    education: str | None = None,
    current_title: str | None = None,
) -> str:
    """兼容旧调用：优先 姓名|年龄|学校。"""
    name = (display_name or "").strip()
    age_s = _normalize_age(age) or ""
    sch = (school or "").strip()
    if not sch and education:
        sch = _extract_school_name(education) or (education or "").strip()
    parts: list[str] = []
    if name:
        parts.append(name)
    if age_s:
        parts.append(f"{age_s}岁")
    if sch:
        parts.append(sch)
    if len(parts) <= 1 and current_title:
        title = (current_title or "").strip()
        if title and title not in parts:
            parts.append(title)
    return "|".join(parts) if parts else (current_title or name)


def format_candidate_subtitle(
    display_name: str | None,
    age: str | None = None,
    school: str | None = None,
    education: str | None = None,
) -> str:
    age_s = _normalize_age(age)
    age_part = f"{age_s}岁" if age_s else ""
    sch = (school or "").strip()
    if not sch and education:
        sch = _extract_school_name(str(education)) or str(education).strip()
    parts = [p for p in (age_part, sch) if p]
    return " · ".join(parts) if parts else "—"


def _score_contact_match(
    text: str,
    *,
    name: str,
    surname: str | None,
    age: str | None,
    school: str | None,
    edu: str | None,
    chat_initiated_at: str | None = None,
    use_surname_only: bool = False,
) -> int:
    score = 0
    matched_name = False
    sur = surname or im_match_surname(name)

    if name and not use_surname_only and name in text:
        matched_name = True
        score += 20
        if text.startswith(name):
            score += 5
    elif sur and _surname_matches_list_name(text, sur):
        matched_name = True
        score += 16 if use_surname_only else 14
    elif sur and len(sur) >= 1 and sur in text:
        if age and (f"{age}岁" in text or f" {age} " in f" {text} "):
            matched_name = True
            score += 14
        elif school and (school in text or (len(school) >= 4 and school[:4] in text)):
            matched_name = True
            score += 12

    if not matched_name:
        return 0

    score += time_proximity_score(text, chat_initiated_at)

    if age and (f"{age}岁" in text or f" {age} " in f" {text} "):
        score += 12
    if school:
        if school in text:
            score += 10
        elif len(school) >= 4 and school[:4] in text:
            score += 6
    if edu and edu in text:
        score += 4
    return score


def match_contact_index(
    contacts: list[tuple[int, str]],
    fields: IMContactMatchFields,
) -> tuple[int | None, int, str]:
    """返回 (index, score, matched_text)。脱敏名按姓氏匹配，可用开聊时间消歧。"""
    raw_name = (fields.display_name or "").strip()
    if is_likely_company_name(raw_name) or raw_name in _NON_PERSON_SHORT_TERMS:
        raw_name = ""
    age = _normalize_age(fields.age)
    school = (fields.school or "").strip()
    edu = (fields.education or "").strip()
    surname = im_match_surname(raw_name)
    use_surname_only = is_masked_person_name(raw_name)
    match_name = surname if use_surname_only else raw_name

    if not match_name and not surname:
        return None, 0, ""

    best_idx: int | None = None
    best_score = 0
    best_text = ""

    for idx, text in contacts:
        score = _score_contact_match(
            text,
            name=match_name,
            surname=surname,
            age=age,
            school=school,
            edu=edu,
            chat_initiated_at=fields.chat_initiated_at,
            use_surname_only=use_surname_only,
        )
        if score > best_score:
            best_score = score
            best_idx = idx
            best_text = text

    min_score = 12
    if use_surname_only and fields.chat_initiated_at:
        min_score = 10
    if best_score >= min_score:
        return best_idx, best_score, best_text
    return None, best_score, best_text
