"""Structured Markdown format for HR screening criteria (generate + merge)."""



from __future__ import annotations



import re

from dataclasses import dataclass, field



# 规范格式：必备 / 快速淘汰 / 加分 / 追问。

SECTION_MUST = "## 必备"

SECTION_QUICK_REJECT = "## 快速淘汰"

SECTION_NICE = "## 加分"

SECTION_FOLLOWUP = "## 追问"

SECTION_REJECT = "## 明确排除"  # 仅解析旧文档，输出时并入必备

SECTION_DECISION = "## 初筛结论规则"



_SECTION_ALIASES: dict[str, str] = {

    "必备": SECTION_MUST,

    "硬性要求": SECTION_MUST,

    "硬性条件": SECTION_MUST,

    "必须满足": SECTION_MUST,

    "快速淘汰": SECTION_QUICK_REJECT,

    "快速淘汰偏好": SECTION_QUICK_REJECT,

    "一票否决": SECTION_QUICK_REJECT,

    "加分": SECTION_NICE,

    "加分项": SECTION_NICE,

    "追问": SECTION_FOLLOWUP,

    "需要追问": SECTION_FOLLOWUP,

    "需要追问确认": SECTION_FOLLOWUP,

    "明确排除": SECTION_REJECT,

    "排除项": SECTION_REJECT,

    "排除": SECTION_REJECT,

    "初筛结论规则": SECTION_DECISION,

    "初筛结论": SECTION_DECISION,

}



_DECISION_RULES = """- 必备条件大部分明确满足 → 观察

- 必备条件缺失但可通过沟通确认 → 追问

- 命中快速淘汰偏好且简历证据明确 → 排除

- 明确违反必备（含排除性说法）或岗位方向不匹配 → 排除"""





@dataclass

class ScreeningCriteriaDoc:

    job_title: str = ""

    job_type: str = ""

    preference_summary: str = ""

    must_have: list[str] = field(default_factory=list)

    quick_reject_rules: list[str] = field(default_factory=list)

    nice_to_have: list[str] = field(default_factory=list)

    followup_questions: list[str] = field(default_factory=list)

    reject_rules: list[str] = field(default_factory=list)  # 解析遗留字段，输出前并入 must_have

    decision_rules: str = _DECISION_RULES





def _clean_item(raw: str) -> str:

    text = str(raw or "").strip()

    text = re.sub(r"^[\-\*•\d]+[\.\)、]\s*", "", text)

    text = text.strip(" \t\r\n-、，,.;；")

    return text





def _clean_items(items: list[str] | None) -> list[str]:

    seen: set[str] = set()

    cleaned: list[str] = []

    for raw in items or []:

        item = _clean_item(raw)

        if not item or item in seen:

            continue

        seen.add(item)

        cleaned.append(item)

    return cleaned





def _merge_reject_into_must(doc: ScreeningCriteriaDoc) -> ScreeningCriteriaDoc:

    if doc.reject_rules:

        doc.must_have = _clean_items([*doc.must_have, *doc.reject_rules])

        doc.reject_rules = []

    return doc





def _normalize_heading(line: str) -> str | None:

    m = re.match(r"^#{1,3}\s*(.+?)\s*$", line.strip())

    if not m:

        return None

    title = m.group(1).strip("：: ")

    for key, canonical in _SECTION_ALIASES.items():

        if key in title:

            return canonical

    return None





def _classify_legacy_line(line: str) -> tuple[str, str]:

    """Guess section for unstructured numbered lines."""

    text = line.lower()

    if any(k in text for k in ("追问", "确认", "沟通确认", "未体现", "可沟通")):

        return "followup", line

    if any(k in text for k in ("加分", "优先", "更佳", "更好", "少量加分", "可加分")):

        return "nice", line

    if any(k in text for k in ("快速淘汰", "一票否决", "直接淘汰")):

        return "quick_reject", line

    # 旧的排除性说法归入必备，保持历史标准兼容。

    return "must", line





def parse_screening_criteria_md(text: str) -> ScreeningCriteriaDoc:

    doc = ScreeningCriteriaDoc()

    raw = (text or "").strip()

    if not raw:

        return doc



    current_section: str | None = None

    decision_lines: list[str] = []

    preamble: list[str] = []



    for line in raw.splitlines():

        stripped = line.strip()

        if not stripped:

            continue



        if stripped.startswith("岗位：") or stripped.startswith("岗位:"):

            doc.job_title = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()

            continue

        if stripped.startswith("岗位类型：") or stripped.startswith("岗位类型:"):

            doc.job_type = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()

            continue

        if stripped.startswith("岗位筛选偏好摘要：") or stripped.startswith("岗位筛选偏好摘要:"):

            doc.preference_summary = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()

            continue

        if stripped.startswith("岗位筛选偏好摘要"):

            continue



        heading = _normalize_heading(stripped)

        if heading:

            current_section = heading

            continue



        if stripped.startswith("简历筛选喜好"):

            current_section = "legacy_mixed"

            continue



        item = _clean_item(stripped)

        if not item:

            continue



        if current_section == "legacy_mixed":

            section_key, value = _classify_legacy_line(item)

            if section_key == "must":

                doc.must_have.append(value)

            elif section_key == "nice":

                doc.nice_to_have.append(value)

            elif section_key == "followup":

                doc.followup_questions.append(value)

            elif section_key == "quick_reject":

                doc.quick_reject_rules.append(value)

            continue



        if current_section == SECTION_MUST:

            doc.must_have.append(item)

        elif current_section == SECTION_QUICK_REJECT:

            doc.quick_reject_rules.append(item)

        elif current_section == SECTION_NICE:

            doc.nice_to_have.append(item)

        elif current_section == SECTION_FOLLOWUP:

            doc.followup_questions.append(item)

        elif current_section == SECTION_REJECT:

            doc.must_have.append(item)

        elif current_section == SECTION_DECISION:

            decision_lines.append(stripped if stripped.startswith("-") else f"- {item}")

        elif current_section is None:

            if re.match(r"^[\-\*•\d]", stripped):

                section_key, value = _classify_legacy_line(item)

                if section_key == "must":

                    doc.must_have.append(value)

                elif section_key == "nice":

                    doc.nice_to_have.append(value)

                elif section_key == "followup":

                    doc.followup_questions.append(value)

                elif section_key == "quick_reject":

                    doc.quick_reject_rules.append(value)

            else:

                preamble.append(stripped)



    if preamble and not doc.preference_summary:

        doc.preference_summary = " ".join(preamble)



    if decision_lines:

        doc.decision_rules = "\n".join(decision_lines)



    doc.must_have = _clean_items(doc.must_have)

    doc.quick_reject_rules = _clean_items(doc.quick_reject_rules)

    doc.nice_to_have = _clean_items(doc.nice_to_have)

    doc.followup_questions = _clean_items(doc.followup_questions)

    doc.reject_rules = _clean_items(doc.reject_rules)

    return _merge_reject_into_must(doc)





def is_structured_criteria_md(text: str) -> bool:

    raw = (text or "").strip()

    if not raw:

        return False

    markers = (

        SECTION_MUST,

        SECTION_QUICK_REJECT,

        SECTION_NICE,

        SECTION_FOLLOWUP,

        "## 硬性要求",

        "## 加分项",

        "## 需要追问",

        SECTION_REJECT,

    )

    return any(marker in raw for marker in markers)





def _numbered(items: list[str], fallback: str) -> str:

    rows = items if items else [fallback]

    return "\n".join(f"{idx + 1}. {item}" for idx, item in enumerate(rows))





def build_screening_criteria_md(

    doc: ScreeningCriteriaDoc,

    *,

    include_decision_rules: bool = True,

) -> str:

    doc = _merge_reject_into_must(

        ScreeningCriteriaDoc(

            job_title=doc.job_title,

            job_type=doc.job_type,

            preference_summary=doc.preference_summary,

            must_have=list(doc.must_have),

            quick_reject_rules=list(doc.quick_reject_rules),

            nice_to_have=list(doc.nice_to_have),

            followup_questions=list(doc.followup_questions),

            reject_rules=list(doc.reject_rules),

            decision_rules=doc.decision_rules,

        )

    )

    title = (doc.job_title or "未命名岗位").strip()

    job_type = (doc.job_type or "通用岗位").strip()

    parts = [f"岗位：{title}", f"岗位类型：{job_type}", ""]



    if doc.preference_summary.strip():

        parts.extend([f"岗位筛选偏好摘要：{doc.preference_summary.strip()}", ""])



    parts.extend(

        [

            SECTION_MUST,

            _numbered(

                doc.must_have,

                "请根据岗位描述判断核心能力是否匹配；排除性要求（不要/不得/不考虑）也写在本节。",

            ),

            "",

            SECTION_QUICK_REJECT,

            _numbered(

                doc.quick_reject_rules,

                "命中以下任一明确情形可直接排除；信息不足时不要凭空淘汰，应转入追问。",

            ),

            "",

            SECTION_NICE,

            _numbered(doc.nice_to_have, "有同类业务经验、稳定履历或更强业务结果可加分，用于简历排序。"),

            "",

            SECTION_FOLLOWUP,

            _numbered(doc.followup_questions, "简历未明确但可能满足必备条件时，生成追问问题确认。"),

        ]

    )



    if include_decision_rules:

        rules = (doc.decision_rules or _DECISION_RULES).strip()

        parts.extend(["", SECTION_DECISION, rules])



    return "\n".join(parts).strip()





def format_unstructured_criteria(

    text: str,

    *,

    job_title: str = "",

    job_type: str = "",

    preference_summary: str = "",

) -> str:

    """Convert plain / legacy text into structured Markdown."""

    parsed = parse_screening_criteria_md(text)

    if job_title.strip():

        parsed.job_title = job_title.strip()

    if job_type.strip():

        parsed.job_type = job_type.strip()

    if preference_summary.strip() and not parsed.preference_summary:

        parsed.preference_summary = preference_summary.strip()

    if not parsed.must_have and not parsed.nice_to_have and text.strip():

        for line in _lines_from_plain(text):

            section_key, value = _classify_legacy_line(line)

            if section_key == "must":

                parsed.must_have.append(value)

            elif section_key == "nice":

                parsed.nice_to_have.append(value)

            elif section_key == "followup":

                parsed.followup_questions.append(value)

            elif section_key == "quick_reject":

                parsed.quick_reject_rules.append(value)

    parsed.must_have = _clean_items(parsed.must_have)

    parsed.quick_reject_rules = _clean_items(parsed.quick_reject_rules)

    parsed.nice_to_have = _clean_items(parsed.nice_to_have)

    parsed.followup_questions = _clean_items(parsed.followup_questions)

    parsed.reject_rules = _clean_items(parsed.reject_rules)

    return build_screening_criteria_md(_merge_reject_into_must(parsed))





def _lines_from_plain(text: str) -> list[str]:

    rows: list[str] = []

    for raw in re.split(r"[\r\n；;]+", text or ""):

        row = _clean_item(raw)

        if row:

            rows.append(row)

    return rows





def merge_screening_criteria_md(

    existing: str,

    *,

    must_have: list[str] | None = None,

    quick_reject_rules: list[str] | None = None,

    nice_to_have: list[str] | None = None,

    followup_questions: list[str] | None = None,

    reject_rules: list[str] | None = None,

    preference_summary: str = "",

    job_title: str = "",

    job_type: str = "",

) -> str:

    """Merge list updates into existing Markdown instead of appending raw text."""

    base = parse_screening_criteria_md(existing)

    if job_title.strip():

        base.job_title = job_title.strip()

    if job_type.strip():

        base.job_type = job_type.strip()

    if preference_summary.strip():

        base.preference_summary = preference_summary.strip()



    merged_must = [*(must_have or []), *(reject_rules or [])]

    base.must_have = _clean_items([*(base.must_have or []), *merged_must])

    base.quick_reject_rules = _clean_items(

        [*(base.quick_reject_rules or []), *(quick_reject_rules or [])]

    )

    base.nice_to_have = _clean_items([*(base.nice_to_have or []), *(nice_to_have or [])])

    base.followup_questions = _clean_items(

        [*(base.followup_questions or []), *(followup_questions or [])]

    )

    base.reject_rules = []

    return build_screening_criteria_md(base)





def normalize_screening_criteria_md(

    text: str,

    *,

    job_title: str = "",

    job_type: str = "",

    force_job_title: bool = False,

) -> str:

    raw = (text or "").strip()

    if not raw:

        return ""

    if is_structured_criteria_md(raw):

        doc = parse_screening_criteria_md(raw)

        if job_title.strip() and (force_job_title or not doc.job_title):

            doc.job_title = job_title.strip()

        if job_type.strip() and not doc.job_type:

            doc.job_type = job_type.strip()

        return build_screening_criteria_md(doc)

    return format_unstructured_criteria(

        raw,

        job_title=job_title,

        job_type=job_type,

    )


