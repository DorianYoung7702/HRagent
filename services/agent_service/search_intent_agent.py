"""Parse natural language search intent into LPT search parameters."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pydantic_ai import Agent

from packages.settings import get_settings
from packages.schemas.workflow import LptEducationFilters, LptOtherFilters, SearchIntentOutput
from packages.screening_defaults import resolve_screening_criteria
from packages.screening_criteria_md import normalize_screening_criteria_md
from services.agent_service.llm import get_deepseek_model
from services.fetch_worker.job_select_match import extract_chat_job_title
from services.fetch_worker.keyword_fallback import filter_keywords_for_search
from services.fetch_worker.lpt_adapter import (
    LPT_DEGREE_OPTIONS,
    LPT_OTHER_FILTER_OPTIONS,
    LPT_SCHOOL_TIER_OPTIONS,
    MAX_LPT_CITIES,
)
from services.fetch_worker.lpt_city_picker import normalize_city_list, normalize_city_list_optional
from services.fetch_worker.lpt_filter_normalize import (
    extract_degree_from_text,
    extract_other_filters_from_text,
    extract_school_tiers_from_text,
    normalize_education_filters,
    normalize_other_filters,
    split_city_lists_from_text,
)

logger = logging.getLogger(__name__)

SEARCH_INTENT_PROMPT = """你是猎聘 LPT 招聘搜索助手。把用户招聘需求拆成**三类**，并**直接写入结构化 JSON 字段**（下游 RPA 只读 JSON，不会从 parse_summary 或原文再做正则提取）。

## 输出要求（重要）
- 所有猎聘筛选项必须填在对应 JSON 字段里，不要只写在 parse_summary 文字里
- current_cities 必须是 string 数组，如 ["深圳"]；用户说「目前在/现居/base 深圳」→ 写入 current_cities，不能只写 parse_summary
- cities 必须是期望城市 string 数组；city 与 cities[0] 一致
- education / other_filters 各子字段未提及则留空字符串或空数组，不要猜

## 一、猎聘搜索栏 keywords（宽检索词）
- 仅适合填入猎聘「不限职位」旁搜索栏，空格分隔 2~5 个宽泛词
- 例：「西班牙语 销售」；不要写电子类、拉美市场、渠道、企业软件等细项
- 西语/拉美岗位必须保留「西班牙语」与「销售」；含销售岗至少保留「销售」

## 二、猎聘筛选条件（结构化，用于猎聘筛选项 RPA）
- city：主城市（与 cities 第一项一致），默认「深圳」
- cities：期望工作城市，最多 5 个；「期望在/愿意去 X」→ cities
- current_cities：目前/现居/base 城市，最多 5 个；「目前在/现居/base X」→ current_cities
- experience：年限如「3-5年」，默认「3-5年」
- education.degree：学历 chip，可选 {degree_opts}；未提及留空
- education.school_tiers：院校要求，可选 {tier_opts}；985/211/双一流/海外留学/海归等多选
- other_filters：其他筛选行（未提及则留空字符串）：
  - activity 活跃状态：{activity_opts}
  - job_seeking 求职状态：{job_seeking_opts}
  - job_hop 跳槽频率：{job_hop_opts}
  - age 年龄：{age_opts}
  - gender 性别：{gender_opts}
  - grad_industry / current_industry / expected_industry：行业关键词（原文或大类名）
  - **不要**填 other_filters.language（语言要求属于 HR 初筛，不进猎聘筛选项）
- target_count：处理简历份数 1~50，默认 20
- 以上猎聘筛选项只填结构化字段，**不要**写进 screening_criteria

## 三、HR 偏好 screening_criteria（在线简历 AI 初筛标准）
- 必须输出**结构化 Markdown**，按以下模板组织（不要输出一整段 unstructured 文本）：
  - 岗位：…（**由系统根据主页岗位名称注入，勿自行推断或改写岗位名**）
  - 岗位类型：…
  - ## 必备（编号列表，可含「不要/不得/不考虑」等排除性说法）
  - ## 加分
  - ## 追问
  - ## 初筛结论规则（观察/追问/排除三条）
- 从用户话术中提炼；未写清时根据岗位意向生成合理分条草案
- 行业/产品/美签/语言等细粒度要求放这里，不进 keywords

## 其它字段
- name：任务名（10 字内）
- parse_summary：2~3 句说明三类信息如何拆分
- job_description：岗位/搜索意图摘要
- **不要**输出或推断 chat_job_title / 开聊岗位名（由系统注入）"""

_LEGACY_SPLIT_HINT = """
若输入已分为「搜索需求」与「HR 评判标准」两段：仅从搜索需求段提取 keywords/city/experience/target_count；
screening_criteria 以 HR 评判标准段为准并适当补全结构。"""

_EXP_PATTERN = re.compile(r"(\d+)\s*[-~至到]\s*(\d+)\s*年?")
_COUNT_EXPLICIT = re.compile(r"(?:处理|抓取|筛选)?\s*(\d+)\s*(?:份|个|人|条)(?:简历|候选人|卡片)?")
_COUNT_LOOSE = re.compile(r"(\d+)\s*(?:份|个|人|条)?\s*(?:简历|候选人|卡片)")
_SKILL_WORDS = [
    "西班牙语", "西语", "美签", "海外销售", "销售", "英语", "法语",
    "德语", "日语", "韩语", "俄语", "阿拉伯语", "葡萄牙语",
    "B2B", "渠道", "商务", "客户经理", "市场拓展",
]


@dataclass(frozen=True)
class ParseInputs:
    requirement_text: str
    screening_fallback: str
    unified_mode: bool
    position_name: str = ""


def resolve_parse_inputs(
    unified_requirement: str = "",
    search_requirement: str = "",
    screening_criteria: str = "",
    *,
    position_name: str = "",
) -> ParseInputs:
    unified = (unified_requirement or "").strip()
    locked_name = (position_name or "").strip()
    if unified:
        return ParseInputs(
            requirement_text=unified,
            screening_fallback="",
            unified_mode=True,
            position_name=locked_name,
        )
    return ParseInputs(
        requirement_text=(search_requirement or "").strip(),
        screening_fallback=(screening_criteria or "").strip(),
        unified_mode=False,
        position_name=locked_name,
    )


def _locked_position_name(inputs: ParseInputs) -> str:
    return (inputs.position_name or "").strip()[:48]


def _resolve_screening_job_title(output: SearchIntentOutput, inputs: ParseInputs) -> str:
    locked = _locked_position_name(inputs)
    if locked:
        return locked
    return (output.chat_job_title or "").strip()[:48]


def _screening_title_kwargs(inputs: ParseInputs, job_title: str) -> dict[str, object]:
    locked = _locked_position_name(inputs)
    if not job_title:
        return {"job_title": "", "force_job_title": False}
    return {"job_title": job_title, "force_job_title": bool(locked)}


def _search_intent_system_prompt() -> str:
    return SEARCH_INTENT_PROMPT.format(
        degree_opts="、".join(LPT_DEGREE_OPTIONS),
        tier_opts="、".join(LPT_SCHOOL_TIER_OPTIONS),
        activity_opts="、".join(LPT_OTHER_FILTER_OPTIONS["activity"]),
        job_seeking_opts="、".join(LPT_OTHER_FILTER_OPTIONS["job_seeking"]),
        job_hop_opts="、".join(LPT_OTHER_FILTER_OPTIONS["job_hop"]),
        age_opts="、".join(LPT_OTHER_FILTER_OPTIONS["age"]),
        gender_opts="、".join(LPT_OTHER_FILTER_OPTIONS["gender"]),
    )


def create_search_intent_agent(model_name: str | None = None) -> Agent[None, SearchIntentOutput]:
    model = get_deepseek_model(model_name) if model_name else get_deepseek_model()
    return Agent(model, output_type=SearchIntentOutput, system_prompt=_search_intent_system_prompt())


def _extract_skill_words(text: str) -> list[str]:
    """从需求文本提取技能词；长词优先，避免「海外销售」再匹配「销售」。"""
    matched = [w for w in sorted(_SKILL_WORDS, key=len, reverse=True) if w in text]
    kept: list[str] = []
    for word in matched:
        if any(word != other and word in other for other in kept):
            continue
        kept.append(word)
    return kept


def rule_based_parse(
    search_requirement: str,
    screening_criteria: str,
    *,
    position_name: str = "",
) -> SearchIntentOutput:
    """AI/JSON 失败时的正则与规则兜底（唯一允许从原文抽字段的路径）。"""
    from services.fetch_worker.lpt_city_picker import extract_cities_from_text

    text = search_requirement or ""
    cities = extract_cities_from_text(text)
    current_cities, expected_cities = split_city_lists_from_text(text, cities=cities)
    city = expected_cities[0] if expected_cities else (cities[0] if cities else "深圳")
    cities = expected_cities or cities

    education = LptEducationFilters(
        degree=extract_degree_from_text(text),
        school_tiers=extract_school_tiers_from_text(text),
    )
    other_filters = extract_other_filters_from_text(text)

    experience = "3-5年"
    m = _EXP_PATTERN.search(text)
    if m:
        experience = f"{m.group(1)}-{m.group(2)}年"

    target_count = 20
    cm = _COUNT_EXPLICIT.search(text) or _COUNT_LOOSE.search(text)
    if cm:
        n = int(cm.group(1))
        if 1 <= n <= 50:
            target_count = n

    keywords_found = _extract_skill_words(text)
    if not keywords_found:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
        stop = {"需要", "寻找", "招聘", "候选人", "人才", "岗位", "要求", "经验", "工作"}
        keywords_found = [t for t in tokens if t not in stop][:5]
    keywords = filter_keywords_for_search(
        " ".join(keywords_found) if keywords_found else "海外销售",
        text,
    )

    job_description = f"搜索需求：{search_requirement.strip()}" if search_requirement.strip() else "猎聘人才搜索"
    name = f"{city} {keywords.split()[0] if keywords else '招聘'}"
    locked = (position_name or "").strip()[:48]
    if locked:
        chat_job_title = locked
    else:
        chat_job_title = extract_chat_job_title(
            f"{text}\n{screening_criteria}\n{job_description}",
            fallback="",
        )
    criteria = normalize_screening_criteria_md(
        resolve_screening_criteria(screening_criteria),
        job_title=chat_job_title or "",
        force_job_title=bool(locked),
    )

    return SearchIntentOutput(
        keywords=keywords,
        city=city,
        cities=cities,
        current_cities=current_cities,
        experience=experience,
        education=education,
        other_filters=other_filters,
        target_count=target_count,
        search_requirement=text,
        screening_criteria=criteria,
        job_description=job_description,
        chat_job_title=chat_job_title,
        name=name[:20],
        parse_summary=(
            f"搜索栏关键词「{keywords}」；猎聘筛选 目前={('、'.join(current_cities) or '—')} "
            f"期望={('、'.join(cities))} / {experience} / {target_count} 份。"
            f" 开聊岗位「{chat_job_title or '（未指定，开聊时选第一项）'}」。"
        ),
    )


def _normalize_cities_from_llm(output: SearchIntentOutput) -> SearchIntentOutput:
    """信任 LLM JSON 的城市字段，仅做列表归一与截断。"""
    if output.cities:
        output.cities = normalize_city_list(output.city, output.cities)[:MAX_LPT_CITIES]
    elif (output.city or "").strip():
        output.cities = normalize_city_list(city=output.city)[:MAX_LPT_CITIES]
    else:
        output.cities = []
    output.current_cities = normalize_city_list_optional(cities=output.current_cities)[:MAX_LPT_CITIES]
    if output.cities:
        output.city = output.cities[0]
    elif not (output.city or "").strip() and output.current_cities:
        output.city = output.current_cities[0]
    elif not (output.city or "").strip():
        output.city = "深圳"
        if not output.cities:
            output.cities = ["深圳"]
    return output


def _strip_language_from_output(output: SearchIntentOutput) -> SearchIntentOutput:
    """语言要求只进 screening_criteria，不进猎聘 other_filters。"""
    merged = output.other_filters.model_dump()
    merged["language"] = ""
    output.other_filters = normalize_other_filters(LptOtherFilters(**merged))
    return output


def _normalize_filters_from_llm(output: SearchIntentOutput) -> SearchIntentOutput:
    """信任 LLM JSON 的筛选项，仅映射到猎聘官方 option 文案。"""
    output.education = normalize_education_filters(output.education)
    output.other_filters = normalize_other_filters(output.other_filters)
    return _strip_language_from_output(output)


def _apply_cities_regex_fallback(output: SearchIntentOutput, requirement_text: str) -> SearchIntentOutput:
    """仅 rule_based 兜底：从原文正则合并城市。"""
    from services.fetch_worker.lpt_city_picker import extract_cities_from_text

    cities_hint = extract_cities_from_text(requirement_text)
    current, expected = split_city_lists_from_text(
        requirement_text,
        cities=output.cities or cities_hint,
        current_cities=output.current_cities,
    )
    merged = normalize_city_list(output.city, expected or output.cities)
    from_text = extract_cities_from_text(requirement_text)
    if from_text and not expected:
        merged = normalize_city_list(cities=from_text + [c for c in merged if c not in from_text])
    output.cities = merged[:MAX_LPT_CITIES]
    output.current_cities = current[:MAX_LPT_CITIES]
    output.city = output.cities[0] if output.cities else (output.city or "深圳")
    return output


def _apply_filters_regex_fallback(output: SearchIntentOutput, requirement_text: str) -> SearchIntentOutput:
    """仅 rule_based 兜底：从原文正则补全筛选项。"""
    output.education = normalize_education_filters(output.education)
    if not output.education.degree:
        output.education.degree = extract_degree_from_text(requirement_text)
    if not output.education.school_tiers:
        output.education.school_tiers = extract_school_tiers_from_text(requirement_text)
    output.education = normalize_education_filters(output.education)

    output.other_filters = normalize_other_filters(output.other_filters)
    fallback_other = extract_other_filters_from_text(requirement_text)
    merged_other = output.other_filters.model_dump()
    for key, value in fallback_other.model_dump().items():
        if key == "language":
            continue
        if not (merged_other.get(key) or "").strip() and (value or "").strip():
            merged_other[key] = value
    output.other_filters = normalize_other_filters(LptOtherFilters(**merged_other))
    return _strip_language_from_output(output)


def build_search_intent_prompt(inputs: ParseInputs) -> str:
    if inputs.unified_mode:
        return f"""## 用户招聘需求（一段话，请同时拆出：搜索栏关键词 + 猎聘筛选条件 + HR 偏好）
{inputs.requirement_text or "（未填写）"}
"""
    return f"""## 搜索需求（解析为猎聘搜索参数）
{inputs.requirement_text or "（未填写）"}

## HR 评判标准（写入 screening_criteria，不参与猎聘搜索栏解析）
{resolve_screening_criteria(inputs.screening_fallback)}
{_LEGACY_SPLIT_HINT}
"""


def finalize_search_intent_output(
    output: SearchIntentOutput,
    inputs: ParseInputs,
    *,
    from_regex_fallback: bool = False,
) -> SearchIntentOutput:
    from services.agent_service.agent_errors import AgentInferenceError

    if not output.keywords.strip():
        raise AgentInferenceError("搜索意图 Agent 未返回 keywords")
    job_title = _resolve_screening_job_title(output, inputs)
    if _locked_position_name(inputs):
        output.chat_job_title = job_title
    elif (output.chat_job_title or "").strip():
        output.chat_job_title = output.chat_job_title.strip()[:48]
    title_kwargs = _screening_title_kwargs(inputs, job_title)
    if not output.screening_criteria.strip():
        output.screening_criteria = normalize_screening_criteria_md(
            resolve_screening_criteria(inputs.screening_fallback),
            **title_kwargs,
        )
    elif inputs.screening_fallback.strip() and not inputs.unified_mode:
        from packages.screening_criteria_md import merge_screening_criteria_md, parse_screening_criteria_md

        base = normalize_screening_criteria_md(inputs.screening_fallback, **title_kwargs)
        parsed = parse_screening_criteria_md(output.screening_criteria)
        output.screening_criteria = merge_screening_criteria_md(
            base,
            must_have=parsed.must_have,
            quick_reject_rules=parsed.quick_reject_rules,
            nice_to_have=parsed.nice_to_have,
            followup_questions=parsed.followup_questions,
            reject_rules=parsed.reject_rules,
            preference_summary=parsed.preference_summary,
            job_title=job_title,
            job_type=parsed.job_type,
        )
    else:
        output.screening_criteria = normalize_screening_criteria_md(
            output.screening_criteria,
            **title_kwargs,
        )
    if not (output.search_requirement or "").strip():
        output.search_requirement = inputs.requirement_text
    if not output.job_description.strip():
        output.job_description = (
            f"搜索需求：{inputs.requirement_text}"
            if inputs.requirement_text
            else "猎聘人才搜索"
        )
    output.target_count = max(1, min(50, output.target_count))
    output.keywords = filter_keywords_for_search(
        output.keywords,
        inputs.requirement_text,
    )
    if from_regex_fallback:
        output = _apply_cities_regex_fallback(output, inputs.requirement_text)
        output = _apply_filters_regex_fallback(output, inputs.requirement_text)
    else:
        output = _normalize_cities_from_llm(output)
        output = _normalize_filters_from_llm(output)
    if inputs.unified_mode and not (output.parse_summary or "").strip():
        city_label = "、".join(output.cities) if output.cities else output.city
        current_label = "、".join(output.current_cities) if output.current_cities else "—"
        chat_hint = job_title or "（未指定）"
        edu_bits = []
        if output.education.degree:
            edu_bits.append(output.education.degree)
        if output.education.school_tiers:
            edu_bits.append("院校:" + "、".join(output.education.school_tiers))
        edu_label = " / ".join(edu_bits) if edu_bits else "—"
        output.parse_summary = (
            f"搜索栏关键词「{output.keywords}」；猎聘筛选 目前={current_label} 期望={city_label} / "
            f"{output.experience} / 学历={edu_label} / {output.target_count} 份；"
            f"开聊岗位「{chat_hint}」。"
        )
    return output


async def parse_search_intent(
    search_requirement: str = "",
    screening_criteria: str = "",
    *,
    unified_requirement: str = "",
    position_name: str = "",
) -> SearchIntentOutput:
    from services.agent_service.agent_errors import AgentInferenceError

    inputs = resolve_parse_inputs(
        unified_requirement,
        search_requirement,
        screening_criteria,
        position_name=position_name,
    )
    prompt = build_search_intent_prompt(inputs)
    model_name = get_settings().deepseek_model
    try:
        agent = create_search_intent_agent(model_name)
        result = await agent.run(prompt)
        return finalize_search_intent_output(result.output, inputs)
    except AgentInferenceError:
        raise
    except Exception as e:
        logger.warning("Search intent AI failed model=%s: %s", model_name, e)
        raise AgentInferenceError(f"搜索意图 Agent 失败 ({model_name}): {e}") from e


def _search_intent_partial_delta(partial: SearchIntentOutput, seen: set[str]) -> list[str]:
    """Emit human-readable lines as structured fields stream in."""
    lines: list[str] = []
    if partial.keywords and "keywords" not in seen:
        seen.add("keywords")
        lines.append(f"搜索词 → {partial.keywords}")
    if partial.current_cities and "current_cities" not in seen:
        seen.add("current_cities")
        lines.append(f"目前城市 → {'、'.join(partial.current_cities)}")
    cities = partial.cities or ([partial.city] if partial.city else [])
    if cities and "cities" not in seen:
        seen.add("cities")
        lines.append(f"期望城市 → {'、'.join(cities)}")
    if partial.experience and "experience" not in seen:
        seen.add("experience")
        lines.append(f"年限 → {partial.experience}")
    if partial.target_count and "target_count" not in seen:
        seen.add("target_count")
        lines.append(f"份数 → {partial.target_count}")
    return lines


def _search_intent_stream_result_delta(output: SearchIntentOutput) -> str:
    """Loading view only shows public search/LPT parameters, not HR screening criteria."""
    current_label = "、".join(output.current_cities) or "—"
    city_label = "、".join(output.cities or [output.city])
    return (
        "\n\n—— 解析结果 ——\n"
        f"【搜索栏】{output.keywords}\n"
        f"【猎聘筛选】目前={current_label} "
        f"期望={city_label} / {output.experience} / {output.target_count} 份\n"
    )


async def parse_search_intent_stream(
    search_requirement: str = "",
    screening_criteria: str = "",
    *,
    unified_requirement: str = "",
    position_name: str = "",
):
    """SSE 事件流：status / delta / result / error。"""
    from services.agent_service.agent_errors import AgentInferenceError

    inputs = resolve_parse_inputs(
        unified_requirement,
        search_requirement,
        screening_criteria,
        position_name=position_name,
    )
    prompt = build_search_intent_prompt(inputs)
    model_name = get_settings().deepseek_model
    start_msg = (
        "已连接模型，开始从一段话拆分解析（搜索词 / 猎聘筛选）…"
        if inputs.unified_mode
        else f"已连接模型 {model_name}，开始解析搜索需求…"
    )

    yield {"event": "status", "data": {"text": start_msg}}

    try:
        agent = create_search_intent_agent(model_name)
        seen_fields: set[str] = set()
        async with agent.run_stream(prompt) as result:
            async for partial in result.stream_output(debounce_by=0.15):
                for line in _search_intent_partial_delta(partial, seen_fields):
                    yield {"event": "status", "data": {"text": line}}
                    yield {"event": "delta", "data": {"text": f"{line}\n"}}
            output = finalize_search_intent_output(await result.get_output(), inputs)
        yield {"event": "status", "data": {"text": "解析完成，正在整理搜索与筛选参数…"}}
        yield {
            "event": "delta",
            "data": {"text": _search_intent_stream_result_delta(output)},
        }
        yield {"event": "result", "data": output.model_dump()}
    except AgentInferenceError as exc:
        yield {"event": "status", "data": {"text": f"AI 解析异常：{exc}，切换规则兜底…"}}
        output = rule_based_parse(
            inputs.requirement_text,
            inputs.screening_fallback,
            position_name=inputs.position_name,
        )
        output = finalize_search_intent_output(output, inputs, from_regex_fallback=True)
        yield {"event": "delta", "data": {"text": _search_intent_stream_result_delta(output)}}
        yield {"event": "result", "data": output.model_dump()}
    except Exception as exc:
        logger.warning("Search intent stream failed model=%s: %s", model_name, exc)
        yield {"event": "status", "data": {"text": "AI 解析失败，切换规则兜底…"}}
        output = rule_based_parse(
            inputs.requirement_text,
            inputs.screening_fallback,
            position_name=inputs.position_name,
        )
        output = finalize_search_intent_output(output, inputs, from_regex_fallback=True)
        yield {"event": "delta", "data": {"text": _search_intent_stream_result_delta(output)}}
        yield {"event": "result", "data": output.model_dump()}
