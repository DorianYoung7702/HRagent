from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic_ai import Agent

from packages.schemas.workflow import (
    HRPreferenceChatRequest,
    HRPreferenceMemory,
    HRPreferenceMemoryRequest,
)
from packages.screening_criteria_md import (
    ScreeningCriteriaDoc,
    build_screening_criteria_md,
    parse_screening_criteria_md,
)
from services.agent_service.llm import get_deepseek_model


HR_PREFERENCE_PROMPT = """你是招聘筛选偏好整理 Agent。

你的任务是把 HR 的自然语言补充，整理成可直接给筛选 Agent 使用的标准。

规则：
1. 当前岗位需求优先级最高，历史岗位预设只能作为参考，不能覆盖当前需求。
2. 输出四类列表：must_have（必备）、quick_reject_rules（快速淘汰）、nice_to_have（加分）、followup_questions（追问）。
3. quick_reject_rules 仅放“简历中有明确证据即可直接排除”的偏好，例如频繁跳槽、明确行业不符。信息缺失或不确定时必须进入追问，不能快速淘汰。
4. 必备与快速淘汰不得表达同一主题的正反两面；同一主题只保留更自然、可执行的一条规则。
5. reject_rules 是旧字段，请保持空列表 []。
6. screening_criteria 可留空，系统会按 Markdown 模板（## 必备 / ## 快速淘汰 / ## 加分 / ## 追问）自动生成。
7. 不要把城市、年限、学历等搜索筛选项改写回搜索关键词，只整理 HR 对简历的判断偏好。
8. 同一主题的新补充要替换旧表述，不要把相同意思的句子追加到列表末尾。

最终 Markdown 结构（由系统生成，供参考）：
- 岗位 / 岗位类型
- ## 必备
- ## 快速淘汰
- ## 加分
- ## 追问
- ## 初筛结论规则
"""


def _clean_items(items: list[str] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in items or []:
        item = str(raw or "").strip(" \t\r\n-、，,.;；")
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _compact_text(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，,。.;；：:、（）()\[\]【】<>《》\"'“”‘’\-—_`*#]", "", text)
    return text


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token.lower() in text for token in tokens)


def _semantic_key(item: str) -> str:
    text = _compact_text(item)
    if not text:
        return ""
    if _has_any(text, ("985", "211", "双一流")):
        return "school_tier"
    if _has_any(text, ("托福", "雅思", "cet6", "cet-6", "六级")):
        return "english_advanced"
    if _has_any(text, ("cet4", "cet-4", "四级", "英语能力", "英文能力")):
        return "english_basic"
    if _has_any(text, ("base深圳", "深圳", "工作地点")):
        return "work_location"
    if _has_any(text, ("人力资源", "心理学", "企业管理", "专业")):
        return "major"
    if _has_any(text, ("薪酬绩效", "薪资绩效")) and _has_any(
        text, ("经验", "年", "同岗位", "模块", "薪酬或绩效")
    ):
        return "comp_perf_experience"
    if _has_any(text, ("薪酬绩效", "薪资绩效")) and _has_any(
        text, ("方案", "设计", "优化", "落地", "实施", "项目", "成果")
    ):
        return "comp_perf_design"
    if _has_any(text, ("沟通", "协调", "同理心", "hrbp", "跨部门", "员工沟通")):
        return "communication"
    if _has_any(text, ("科技", "互联网", "智能硬件", "行业背景", "行业工作经验")):
        return "industry"
    if _has_any(text, ("稳定", "跳槽", "工作经历", "段工作")):
        return "stability"
    return text[:80]


def _item_quality(item: str) -> int:
    text = str(item or "")
    compact = _compact_text(text)
    score = len(compact)
    for token in ("或", "且", "非", "两者", "同等", "具体", "成果", "落地", "优化", "明确", "目前"):
        if token in text:
            score += 8
    if "、" not in text and _semantic_key(text) == "school_tier":
        score += 4
    return score


def _pick_better_item(existing: str, incoming: str) -> str:
    if not existing:
        return incoming
    if not incoming:
        return existing
    if _item_quality(incoming) >= _item_quality(existing) - 4:
        return incoming
    return existing


def _merge_by_topic(items: list[str], *, section: str) -> list[str]:
    preferred_order = {
        "must": [
            "major",
            "comp_perf_experience",
            "comp_perf_design",
            "english_basic",
            "work_location",
        ],
        "quick_reject": ["stability", "industry", "work_location", "major"],
        "nice": [
            "school_tier",
            "communication",
            "english_advanced",
            "industry",
            "stability",
        ],
        "followup": ["comp_perf_design", "communication"],
        "reject": [],
    }
    merged: dict[str, str] = {}
    order: list[str] = []
    for item in _clean_items(items):
        key = _semantic_key(item)
        if not key:
            continue
        if key not in merged:
            order.append(key)
            merged[key] = item
        else:
            merged[key] = _pick_better_item(merged[key], item)

    sorted_keys = [key for key in preferred_order.get(section, []) if key in merged]
    sorted_keys.extend(key for key in order if key not in sorted_keys)
    return [merged[key] for key in sorted_keys]


def _drop_rejects_mirrored_by_must(reject_rules: list[str], must_have: list[str]) -> list[str]:
    must_keys = {_semantic_key(item) for item in must_have}
    must_keys.discard("")
    return [item for item in reject_rules if _semantic_key(item) not in must_keys]


def _normalize_memory_lists(memory: HRPreferenceMemory) -> HRPreferenceMemory:
    reject_merged = _merge_by_topic(memory.reject_rules, section="reject")
    memory.must_have = _merge_by_topic([*memory.must_have, *reject_merged], section="must")
    memory.quick_reject_rules = _merge_by_topic(
        memory.quick_reject_rules,
        section="quick_reject",
    )
    memory.nice_to_have = _merge_by_topic(memory.nice_to_have, section="nice")
    memory.followup_questions = _merge_by_topic(memory.followup_questions, section="followup")
    memory.reject_rules = []
    return memory


def _lines_from_text(text: str) -> list[str]:
    rows: list[str] = []
    for raw in (text or "").replace("；", "\n").replace(";", "\n").splitlines():
        row = raw.strip(" \t\r\n-、0123456789.）)•")
        if row:
            rows.append(row)
    return rows


def _message_text(messages: list[dict[str, str]]) -> str:
    return "\n".join(
        str(m.get("content") or "").strip()
        for m in messages
        if str(m.get("content") or "").strip()
    )


def _memory_from_criteria_text(text: str) -> HRPreferenceMemory:
    doc = parse_screening_criteria_md(text)
    return HRPreferenceMemory(
        must_have=doc.must_have,
        quick_reject_rules=doc.quick_reject_rules,
        nice_to_have=doc.nice_to_have,
        followup_questions=doc.followup_questions,
        reject_rules=doc.reject_rules,
        preference_summary=doc.preference_summary,
    )


def _build_screening_criteria(memory: HRPreferenceMemory, fallback: str = "") -> str:
    existing = parse_screening_criteria_md(fallback)
    doc = ScreeningCriteriaDoc(
        job_title=existing.job_title,
        job_type=existing.job_type or "通用岗位",
        preference_summary=memory.preference_summary.strip() or existing.preference_summary,
        must_have=_clean_items(memory.must_have),
        quick_reject_rules=_clean_items(memory.quick_reject_rules),
        nice_to_have=_clean_items(memory.nice_to_have),
        followup_questions=_clean_items(memory.followup_questions),
        reject_rules=_clean_items(memory.reject_rules),
        decision_rules=existing.decision_rules,
    )
    if not any(
        [
            doc.must_have,
            doc.quick_reject_rules,
            doc.nice_to_have,
            doc.followup_questions,
            doc.reject_rules,
        ]
    ):
        if fallback.strip():
            return build_screening_criteria_md(parse_screening_criteria_md(fallback))
        return ""
    return build_screening_criteria_md(doc)


def _normalize_memory(output: HRPreferenceMemory, request: HRPreferenceChatRequest) -> HRPreferenceMemory:
    preset = request.preset_memory or HRPreferenceMemory()
    existing = _memory_from_criteria_text(request.screening_criteria)

    output.must_have = _merge_by_topic(
        [
            *preset.must_have,
            *existing.must_have,
            *preset.reject_rules,
            *existing.reject_rules,
            *output.must_have,
            *output.reject_rules,
        ],
        section="must",
    )
    output.quick_reject_rules = _merge_by_topic(
        [
            *preset.quick_reject_rules,
            *existing.quick_reject_rules,
            *output.quick_reject_rules,
        ],
        section="quick_reject",
    )
    output.nice_to_have = _merge_by_topic(
        [*preset.nice_to_have, *existing.nice_to_have, *output.nice_to_have],
        section="nice",
    )
    output.reject_rules = []
    output.followup_questions = _merge_by_topic(
        [*preset.followup_questions, *existing.followup_questions, *output.followup_questions],
        section="followup",
    )
    output = _normalize_memory_lists(output)

    if not output.preference_summary.strip():
        output.preference_summary = (
            request.current_requirement.strip()
            or preset.preference_summary.strip()
            or existing.preference_summary.strip()
            or "已根据当前岗位需求整理筛选偏好。"
        )
    rebuilt_criteria = _build_screening_criteria(output, request.screening_criteria)
    if rebuilt_criteria:
        output.screening_criteria = rebuilt_criteria
    if not output.assistant_message.strip():
        output.assistant_message = "已更新筛选偏好，可应用到本次任务。"
    output.ready = bool(output.screening_criteria.strip()) if output.ready is False else output.ready
    output.criteria_version = max(int(output.criteria_version or 1), int(preset.criteria_version or 1))
    return output


def _fallback_memory(request: HRPreferenceChatRequest) -> HRPreferenceMemory:
    preset = request.preset_memory or HRPreferenceMemory()
    hr_text = _message_text(request.messages)
    combined = "\n".join(
        part
        for part in [
            request.current_requirement.strip(),
            request.screening_criteria.strip(),
            hr_text.strip(),
        ]
        if part
    )
    lines = _lines_from_text(combined)

    quick_reject = [
        line
        for line in lines
        if any(k in line.lower() for k in ("快速淘汰", "一票否决", "直接淘汰"))
    ]
    reject = [
        line
        for line in lines
        if line not in quick_reject
        and any(k in line.lower() for k in ("reject", "exclude", "不要", "排除", "不得", "不考虑"))
    ]
    followup = [line for line in lines if any(k in line.lower() for k in ("confirm", "ask", "追问", "确认"))]
    nice = [line for line in lines if any(k in line.lower() for k in ("加分", "优先", "更佳"))]
    must = [line for line in lines if line not in followup and line not in nice and line not in quick_reject]
    must.extend(reject)

    memory = HRPreferenceMemory(
        must_have=must,
        quick_reject_rules=quick_reject,
        nice_to_have=nice,
        reject_rules=[],
        followup_questions=followup,
        preference_summary=request.current_requirement.strip()
        or preset.preference_summary
        or "已根据 HR 补充整理筛选偏好。",
        assistant_message="已根据补充内容更新筛选偏好。",
        ready=True,
        criteria_version=max(int(preset.criteria_version or 1), 1),
    )
    return _normalize_memory(memory, request)


def create_hr_preference_agent() -> Agent[None, HRPreferenceMemory]:
    return Agent(
        get_deepseek_model(),
        output_type=HRPreferenceMemory,
        system_prompt=HR_PREFERENCE_PROMPT,
    )


async def _run_preference_agent(request: HRPreferenceChatRequest) -> HRPreferenceMemory:
    agent = create_hr_preference_agent()
    prompt = f"""## 当前岗位需求
{request.current_requirement or "（无）"}

## 已解析搜索条件
{request.parsed_intent}

## 当前筛选标准
{request.screening_criteria or "（无）"}

## 岗位预设中的历史偏好记忆
{request.preset_memory.model_dump() if request.preset_memory else {}}

## HR 偏好窗口对话
{request.messages}

请输出更新后的 HRPreferenceMemory。"""
    result = await agent.run(prompt)
    return result.output


async def update_preference_memory(request: HRPreferenceChatRequest) -> HRPreferenceMemory:
    try:
        output = await _run_preference_agent(request)
    except Exception:
        output = _fallback_memory(request)
    return _normalize_memory(output, request)


async def initialize_preference_memory(request: HRPreferenceMemoryRequest) -> HRPreferenceMemory:
    chat_request = HRPreferenceChatRequest(**request.model_dump())
    memory = await update_preference_memory(chat_request)
    memory.assistant_message = memory.assistant_message or "已根据当前需求初始化筛选偏好。"
    memory.ready = bool(memory.screening_criteria.strip())
    return memory


def memory_with_version(memory: HRPreferenceMemory, version: int) -> HRPreferenceMemory:
    data = memory.model_dump()
    data["criteria_version"] = max(1, int(version or 1))
    if not data.get("assistant_message"):
        data["assistant_message"] = "筛选偏好已保存，后续新候选将使用新标准。"
    if not data.get("preference_summary"):
        data["preference_summary"] = f"更新于 {datetime.now(timezone.utc).isoformat()}"
    return HRPreferenceMemory(**data)
