"""Tests for search intent parsing."""

import pytest

from packages.screening_defaults import DEFAULT_SCREENING_CRITERIA
from packages.schemas.workflow import LptOtherFilters, SearchIntentOutput
from services.agent_service.search_intent_agent import (
    _search_intent_partial_delta,
    _search_intent_stream_result_delta,
    build_search_intent_prompt,
    finalize_search_intent_output,
    resolve_parse_inputs,
    rule_based_parse,
)
from services.fetch_worker.lpt_filter_normalize import split_city_lists_from_text


def test_rule_based_search_from_requirement_only():
    req = "需要西班牙语流利、有海外销售经验，深圳3-5年，处理20份简历"
    out = rule_based_parse(
        req,
        "美签+西班牙语+销售都有则观察；无美签有留学则追问",
    )
    assert out.search_requirement == req
    assert "西班牙语" in out.keywords
    assert out.city == "深圳"
    assert out.experience == "3-5年"
    assert out.target_count == 20
    assert "美签" in out.screening_criteria or "拉美" in out.screening_criteria
    assert out.parse_summary


def test_rule_based_no_duplicate_sales_token():
    out = rule_based_parse(
        "需要西班牙语流利、有海外销售经验，深圳3-5年，处理20份简历",
        "",
    )
    parts = out.keywords.split()
    assert parts.count("销售") <= 1
    assert "海外销售" in out.keywords or "销售" in out.keywords


def test_rule_based_extracts_chat_job_title():
    out = rule_based_parse(
        "需要西班牙语流利、有海外销售经验，深圳3-5年，处理20份简历",
        "岗位：拉美中方销售\n美签+西班牙语+销售都有则观察",
    )
    assert out.chat_job_title == "拉美中方销售"


def test_rule_based_uses_position_name_when_provided():
    out = rule_based_parse(
        "需要嵌入式开发经验，深圳3-5年",
        "岗位：嵌入式开发\n## 必备\n1. C语言",
        position_name="嵌入式工程师",
    )
    assert out.chat_job_title == "嵌入式工程师"
    assert "岗位：嵌入式工程师" in out.screening_criteria


def test_finalize_locks_position_name_over_llm_chat_job_title():
    inputs = resolve_parse_inputs(
        unified_requirement="深圳招嵌入式开发，3-5年，20份",
        position_name="嵌入式工程师",
    )
    output = SearchIntentOutput(
        keywords="嵌入式 开发",
        city="深圳",
        cities=["深圳"],
        experience="3-5年",
        target_count=20,
        screening_criteria="岗位：嵌入式开发\n## 必备\n1. 熟悉 C",
        chat_job_title="嵌入式开发",
        name="深圳 嵌入式",
    )
    final = finalize_search_intent_output(output, inputs)
    assert final.chat_job_title == "嵌入式工程师"
    assert "岗位：嵌入式工程师" in final.screening_criteria
    assert "岗位：嵌入式开发" not in final.screening_criteria


def test_rule_based_extracts_filters():
    out = rule_based_parse(
        "目前base深圳，期望北京，985本科，今日活跃，25-30岁，处理20份简历",
        "",
    )
    assert "深圳" in out.current_cities
    assert "北京" in out.cities
    assert "985" in out.education.school_tiers
    assert out.education.degree == "本科"
    assert out.other_filters.activity == "今日活跃"
    assert out.other_filters.age == "25-30"


def test_split_city_lists_from_text():
    current, expected = split_city_lists_from_text("目前在深圳，期望上海")
    assert "深圳" in current
    assert "上海" in expected


def test_screening_criteria_not_used_for_city():
    out = rule_based_parse(
        "招聘海外销售",
        "候选人必须有10年以上管理经验，base北京",
    )
    assert out.city == "深圳"
    assert "10年" in out.screening_criteria or "管理" in out.screening_criteria


def test_default_screening_criteria():
    out = rule_based_parse("海外销售", "")
    assert "## 必备" in out.screening_criteria
    assert "Python" in out.screening_criteria
    assert "## 初筛结论规则" in out.screening_criteria
    assert DEFAULT_SCREENING_CRITERIA.splitlines()[0] in out.screening_criteria or "深圳 ToB" in out.screening_criteria


def test_resolve_unified_parse_inputs():
    inputs = resolve_parse_inputs(
        unified_requirement="深圳招西语销售，3-5年，20份，美签优先",
    )
    assert inputs.unified_mode
    assert "西语" in inputs.requirement_text


def test_finalize_trusts_llm_current_cities():
    """LLM JSON 已填 current_cities 时，finalize 只做归一化，不从 parse_summary 正则补。"""
    inputs = resolve_parse_inputs(unified_requirement="深圳招西语销售，3-5年，20份")
    output = SearchIntentOutput(
        keywords="西班牙语 销售",
        city="深圳",
        cities=["深圳"],
        current_cities=["深圳"],
        experience="3-5年",
        target_count=20,
        screening_criteria="美签优先",
        parse_summary="猎聘筛选 目前=深圳 期望=深圳 / 3-5年 / 20 份",
    )
    final = finalize_search_intent_output(output, inputs)
    assert final.current_cities == ["深圳"]


def test_finalize_cleans_filter_terms_from_llm_keywords():
    inputs = resolve_parse_inputs(unified_requirement="深圳招开发工程师架构师，1-5年，20份")
    output = SearchIntentOutput(
        keywords="开发工程师 架构师 深圳 年经验",
        city="深圳",
        cities=["深圳"],
        current_cities=["深圳"],
        experience="1-5年",
        target_count=20,
        screening_criteria="开发工程能力强，有架构经验优先",
    )
    final = finalize_search_intent_output(output, inputs)
    assert final.keywords == "开发工程师 架构师"
    assert final.city == "深圳"
    assert final.current_cities == ["深圳"]
    assert final.experience == "1-5年"


def test_finalize_does_not_backfill_current_from_parse_summary():
    """仅 parse_summary 写 目前=深圳、字段为空时，不触发正则补全（依赖 LLM 填 JSON）。"""
    inputs = resolve_parse_inputs(unified_requirement="深圳招西语销售，3-5年，20份")
    output = SearchIntentOutput(
        keywords="西班牙语 销售",
        city="深圳",
        cities=["深圳"],
        current_cities=[],
        experience="3-5年",
        target_count=20,
        screening_criteria="美签优先",
        parse_summary="猎聘筛选 目前=深圳 期望=深圳 / 3-5年 / 20 份",
    )
    final = finalize_search_intent_output(output, inputs)
    assert final.current_cities == []


def test_finalize_regex_fallback_fills_current_from_requirement():
    """规则兜底路径仍可从原文正则补全 current_cities。"""
    inputs = resolve_parse_inputs(
        unified_requirement="目前base深圳，期望北京，985本科，今日活跃，25-30岁，处理20份简历",
    )
    output = rule_based_parse(inputs.requirement_text, "")
    final = finalize_search_intent_output(output, inputs, from_regex_fallback=True)
    assert "深圳" in final.current_cities
    assert "北京" in final.cities


def test_finalize_strips_language_filter():
    inputs = resolve_parse_inputs(unified_requirement="需要西班牙语流利销售，今日活跃")
    output = SearchIntentOutput(
        keywords="西班牙语 销售",
        city="深圳",
        experience="3-5年",
        target_count=20,
        screening_criteria="西班牙语必须能作为工作语言",
        other_filters=LptOtherFilters(language="西班牙语", activity="今日活跃"),
    )
    final = finalize_search_intent_output(output, inputs)
    assert final.other_filters.language == ""
    assert final.other_filters.activity == "今日活跃"


def test_build_unified_prompt():
    inputs = resolve_parse_inputs(unified_requirement="拉美销售 深圳 20份")
    prompt = build_search_intent_prompt(inputs)
    assert "一段话" in prompt
    assert "拉美销售" in prompt


def test_loading_delta_does_not_output_hr_preferences():
    partial = SearchIntentOutput(
        keywords="西班牙语 销售",
        city="深圳",
        cities=["深圳"],
        experience="3-5年",
        target_count=20,
        screening_criteria="HR偏好：必须有美签，西班牙语可作为工作语言",
        parse_summary="HR 偏好已写入评判标准",
    )

    lines = _search_intent_partial_delta(partial, set())
    final_text = _search_intent_stream_result_delta(partial)
    rendered = "\n".join([*lines, final_text])

    assert "HR" not in rendered
    assert "美签" not in rendered
    assert "西班牙语可作为工作语言" not in rendered
    assert "【搜索栏】西班牙语 销售" in rendered


@pytest.mark.asyncio
async def test_parse_search_intent_stream_awaits_async_get_output(monkeypatch):
    from services.agent_service import search_intent_agent as sia

    expected = SearchIntentOutput(
        keywords="西班牙语 销售",
        city="深圳",
        cities=["深圳"],
        experience="3-5年",
        target_count=20,
        screening_criteria="## 硬性要求\n1. 会西语",
    )

    class FakeStreamResult:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def stream_output(self, *, debounce_by=0.15):
            yield expected

        async def get_output(self):
            return expected

    class FakeAgent:
        def run_stream(self, prompt):
            return FakeStreamResult()

    monkeypatch.setattr(sia, "create_search_intent_agent", lambda model: FakeAgent())

    events = []
    async for item in sia.parse_search_intent_stream(unified_requirement="深圳西语销售 20份"):
        events.append(item)

    assert any(e["event"] == "result" for e in events)
    result = next(e for e in events if e["event"] == "result")
    assert "西班牙语" in result["data"]["keywords"]
