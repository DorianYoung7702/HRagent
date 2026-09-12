"""初筛判定展示：从标准对照/解析结果动态生成模式字段，不写死美签/西语等。"""

from __future__ import annotations

import re

from packages.schemas.screening import ResumeParseOutput, ScreeningDecisionOutput, VisaScreeningOutput

_CRITERIA_KV_RE = re.compile(
    r"([^：:；;，,\n]+?)[：:]\s*"
    r"(有|无|未提及|满足|不满足|是|否|符合|不符合|部分满足|已体现|未体现|缺少|不明确)"
)
_LEGACY_BOOL_FIELDS = (
    ("has_us_visa", "美签"),
    ("has_spanish", "西班牙语"),
    ("has_sales", "销售"),
    ("has_study_abroad", "留学"),
)


def _normalize_flag_value(val: str) -> str:
    v = (val or "").strip()
    if v in ("有", "是", "满足", "符合", "已体现"):
        return "有"
    if v in ("无", "否", "不满足", "不符合", "缺少"):
        return "无"
    if "未提及" in v or "未体现" in v or "不明确" in v:
        return "未提及"
    if "部分" in v:
        return "部分"
    return v


def parse_criteria_analysis_flags(criteria_analysis: str) -> dict[str, str]:
    """从判定 Agent 的 criteria_analysis 提取「维度：状态」。"""
    text = (criteria_analysis or "").strip()
    if not text:
        return {}

    flags: dict[str, str] = {}
    for m in _CRITERIA_KV_RE.finditer(text):
        key = m.group(1).strip().strip("·-—")
        if not key or len(key) > 24:
            continue
        flags[key] = _normalize_flag_value(m.group(2))

    if flags:
        return flags

    for part in re.split(r"[；;]\s*", text):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.+?)[：:]\s*(.+)$", part)
        if not m:
            continue
        key = m.group(1).strip()
        val = _normalize_flag_value(m.group(2).strip())
        if key and len(key) <= 24:
            flags[key] = val
    return flags


def _classify_parse_info(text: str | None) -> str | None:
    t = (text or "").strip()
    if not t or t in ("—", "-", "N/A"):
        return None
    if t in ("未提及", "暂无", "未知"):
        return "未提及"
    if re.search(r"持|具备|拥有|有.{0,6}签|经验|年|销售|留学|海外", t):
        return "有"
    if re.search(r"^(无|没有)|未具备|不具备|不含", t):
        return "无"
    if re.search(r"未提及|暂无|未知", t):
        return "未提及"
    return "有"


def flags_from_parse_output(parse: ResumeParseOutput | None) -> dict[str, str]:
    """从解析 Agent 结果生成展示字段。"""
    if not parse:
        return {}
    flags: dict[str, str] = {}

    for lang in (parse.languages or [])[:8]:
        label = (lang or "").strip()
        if label and label not in flags:
            flags[label] = "有"

    for label, info in (
        ("签证", parse.visa_info),
        ("销售", parse.sales_info),
        ("留学", parse.education_abroad),
    ):
        state = _classify_parse_info(info)
        if state:
            flags[label] = state

    for h in (parse.highlights or [])[:6]:
        item = (h or "").strip()
        if not item or len(item) > 20:
            continue
        if item not in flags:
            flags[item] = "有"

    return flags


def _criteria_mentions_label(screening_criteria: str, label: str) -> bool:
    return label in (screening_criteria or "")


def flags_from_legacy_booleans(
    obj: ScreeningDecisionOutput | VisaScreeningOutput | None,
    *,
    screening_criteria: str = "",
) -> dict[str, str]:
    """仅当 HR 标准中含对应维度时，才用旧布尔字段兜底。"""
    if obj is None:
        return {}
    criteria = screening_criteria or ""
    use_all = not criteria.strip()
    flags: dict[str, str] = {}
    for attr, label in _LEGACY_BOOL_FIELDS:
        if use_all or _criteria_mentions_label(criteria, label):
            val = getattr(obj, attr, False)
            flags[label] = "有" if val else "无"
    return flags


def build_screening_flag_map(
    *,
    criteria_analysis: str = "",
    parse: ResumeParseOutput | None = None,
    legacy: ScreeningDecisionOutput | VisaScreeningOutput | None = None,
    screening_criteria: str = "",
) -> dict[str, str]:
    flags = parse_criteria_analysis_flags(criteria_analysis)
    if flags:
        return flags
    flags = flags_from_parse_output(parse)
    if flags:
        return flags
    return flags_from_legacy_booleans(legacy, screening_criteria=screening_criteria)


def format_screening_flag_text(
    *,
    criteria_analysis: str = "",
    parse: ResumeParseOutput | None = None,
    legacy: ScreeningDecisionOutput | VisaScreeningOutput | None = None,
    screening_criteria: str = "",
) -> str:
    flags = build_screening_flag_map(
        criteria_analysis=criteria_analysis,
        parse=parse,
        legacy=legacy,
        screening_criteria=screening_criteria,
    )
    if not flags:
        return ""
    return "  ".join(f"{k}:{v}" for k, v in flags.items())
