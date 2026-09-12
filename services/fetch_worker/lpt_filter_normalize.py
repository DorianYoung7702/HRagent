"""Normalize parsed filter values to Liepin LPT option labels."""

from __future__ import annotations

import re

from packages.schemas.workflow import LptEducationFilters, LptOtherFilters
from services.fetch_worker.lpt_adapter import (
    LPT_DEGREE_OPTIONS,
    LPT_OTHER_FILTER_OPTIONS,
    LPT_SCHOOL_TIER_OPTIONS,
    LPT_KNOWN_CITIES,
    MAX_LPT_CITIES,
)

_SCHOOL_TIER_ALIASES: dict[str, str] = {
    "985": "985",
    "985院校": "985",
    "985大学": "985",
    "211": "211",
    "211院校": "211",
    "211大学": "211",
    "双一流": "双一流",
    "双一流院校": "双一流",
    "海外留学": "海外留学",
    "海外院校": "海外留学",
    "留学": "海外留学",
    "留学背景": "海外留学",
    "海归": "海外留学",
}

_DEGREE_ALIASES: dict[str, str] = {
    "大专": "大专",
    "专科": "大专",
    "本科": "本科",
    "学士": "本科",
    "统招本科": "本科",
    "硕士": "硕士",
    "研究生": "硕士",
    "mba": "MBA/EMBA",
    "emba": "MBA/EMBA",
    "博士": "博士",
    "phd": "博士",
}

_CURRENT_CITY_MARKERS = re.compile(
    r"(?:目前(?:在|于|base|Base|BASE)?|现居(?:在|于)?|base(?:在|于)?|Base(?:在|于)?)"
    r"[\s:：=＝,，、]*([\u4e00-\u9fff]{2,8})"
)
_EXPECT_CITY_MARKERS = re.compile(
    r"(?:期望(?:在|于|去)?|愿意(?:去|到)?|目标城市(?:为|是)?|想去)"
    r"[\s:：=＝,，、]*([\u4e00-\u9fff]{2,8})"
)


def resolve_lpt_option(candidates: list[str], parsed: str) -> str:
    """Pick the closest official option; return empty if no match."""
    text = (parsed or "").strip()
    if not text or text in ("不限", "无", "任意"):
        return ""
    if text in candidates:
        return text
    lower = text.lower()
    for opt in candidates:
        if opt.lower() == lower:
            return opt
    for opt in candidates:
        if text in opt or opt in text:
            return opt
    return text if not candidates else ""


def normalize_school_tiers(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        key = (item or "").strip()
        if not key:
            continue
        mapped = _SCHOOL_TIER_ALIASES.get(key, key)
        if mapped in LPT_SCHOOL_TIER_OPTIONS and mapped not in out:
            out.append(mapped)
    return out


def normalize_degree(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    mapped = _DEGREE_ALIASES.get(text.lower(), text)
    return resolve_lpt_option(LPT_DEGREE_OPTIONS, mapped)


def normalize_education_filters(edu: LptEducationFilters | None) -> LptEducationFilters:
    if edu is None:
        return LptEducationFilters()
    return LptEducationFilters(
        degree=normalize_degree(edu.degree),
        school_tiers=normalize_school_tiers(edu.school_tiers),
    )


def normalize_other_filters(other: LptOtherFilters | None) -> LptOtherFilters:
    if other is None:
        return LptOtherFilters()
    data = other.model_dump()
    normalized: dict[str, str] = {}
    for field, value in data.items():
        text = (value or "").strip()
        if not text:
            normalized[field] = ""
            continue
        options = LPT_OTHER_FILTER_OPTIONS.get(field, [])
        if options:
            normalized[field] = resolve_lpt_option(options, text)
        else:
            normalized[field] = text
    return LptOtherFilters(**normalized)


def _city_in_known(name: str) -> bool:
    n = name.strip()
    return n in LPT_KNOWN_CITIES or len(n) >= 2


def extract_current_cities_from_text(text: str) -> list[str]:
    found: list[str] = []
    for m in _CURRENT_CITY_MARKERS.finditer(text or ""):
        name = m.group(1).strip()
        if _city_in_known(name) and name not in found:
            found.append(name)
        if len(found) >= MAX_LPT_CITIES:
            break
    return found


def extract_expected_cities_from_text(text: str) -> list[str]:
    found: list[str] = []
    for m in _EXPECT_CITY_MARKERS.finditer(text or ""):
        name = m.group(1).strip()
        if _city_in_known(name) and name not in found:
            found.append(name)
        if len(found) >= MAX_LPT_CITIES:
            break
    return found


def split_city_lists_from_text(
    text: str,
    *,
    cities: list[str] | None = None,
    current_cities: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Merge LLM + regex city hints into (current, expected) lists."""
    current = list(current_cities or [])
    expected = list(cities or [])

    for name in extract_current_cities_from_text(text):
        if name not in current:
            current.append(name)
    for name in extract_expected_cities_from_text(text):
        if name not in expected:
            expected.append(name)

    # 未标注时：从全文提取的城市默认进期望城市
    from services.fetch_worker.lpt_city_picker import extract_cities_from_text

    for name in extract_cities_from_text(text):
        if name in current or name in expected:
            continue
        expected.append(name)

    return current[:MAX_LPT_CITIES], expected[:MAX_LPT_CITIES]


def extract_school_tiers_from_text(text: str) -> list[str]:
    raw: list[str] = []
    for token in ("985", "211", "双一流", "海外留学", "留学", "海归"):
        if token in (text or "") and token not in raw:
            raw.append(token)
    return normalize_school_tiers(raw)


def extract_degree_from_text(text: str) -> str:
    for token in ("博士", "硕士", "MBA", "EMBA", "本科", "大专", "专科"):
        if token in (text or ""):
            return normalize_degree(token)
    return ""


def extract_other_filters_from_text(text: str) -> LptOtherFilters:
    t = text or ""
    activity = ""
    for opt in LPT_OTHER_FILTER_OPTIONS["activity"]:
        if opt != "不限" and opt in t:
            activity = opt
            break
    if "今日活跃" in t or "今天活跃" in t:
        activity = "今日活跃"

    job_seeking = ""
    for opt in LPT_OTHER_FILTER_OPTIONS["job_seeking"]:
        if opt != "不限" and opt in t:
            job_seeking = opt
            break

    job_hop = ""
    for opt in LPT_OTHER_FILTER_OPTIONS["job_hop"]:
        if opt != "不限" and opt in t:
            job_hop = opt
            break

    age = ""
    age_m = re.search(r"(\d{2})\s*[-~至到]\s*(\d{2})\s*岁?", t)
    if age_m:
        age = f"{age_m.group(1)}-{age_m.group(2)}"
    else:
        for opt in LPT_OTHER_FILTER_OPTIONS["age"]:
            if opt != "不限" and opt in t:
                age = opt
                break

    gender = ""
    if "男" in t and "女" not in t:
        gender = "男"
    elif "女" in t and "男" not in t:
        gender = "女"

    language = ""
    for opt in LPT_OTHER_FILTER_OPTIONS["language"]:
        if opt != "不限" and opt in t:
            language = opt
            break
    if "西语" in t and not language:
        language = "西班牙语"

    return normalize_other_filters(
        LptOtherFilters(
            activity=activity,
            job_seeking=job_seeking,
            job_hop=job_hop,
            age=age,
            gender=gender,
            language=language,
        )
    )
