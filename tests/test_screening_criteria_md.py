"""Tests for structured Markdown HR screening criteria."""

from packages.screening_criteria_md import (
    build_screening_criteria_md,
    format_unstructured_criteria,
    merge_screening_criteria_md,
    normalize_screening_criteria_md,
    parse_screening_criteria_md,
    ScreeningCriteriaDoc,
)


def test_build_and_parse_roundtrip():
    doc = ScreeningCriteriaDoc(
        job_title="拉美中方销售",
        job_type="销售岗",
        preference_summary="优先拉美一线销售",
        must_have=["必须有美签", "西班牙语可作为工作语言", "不要纯 C 端销售"],
        quick_reject_rules=["近一年内有两次及以上主动跳槽"],
        nice_to_have=["有渠道管理经验"],
        followup_questions=["简历未写美签时需确认"],
    )
    md = build_screening_criteria_md(doc)
    parsed = parse_screening_criteria_md(md)

    assert parsed.job_title == "拉美中方销售"
    assert parsed.must_have == doc.must_have
    assert parsed.quick_reject_rules == doc.quick_reject_rules
    assert parsed.nice_to_have == doc.nice_to_have
    assert parsed.followup_questions == doc.followup_questions
    assert parsed.reject_rules == []
    assert "## 必备" in md
    assert "## 快速淘汰" in md
    assert "## 明确排除" not in md
    assert "## 初筛结论规则" in md


def test_legacy_reject_section_merges_into_must():
    md = """岗位：测试岗

## 必备
1. 必须有美签

## 加分
1. 有渠道经验

## 追问
1. 确认签证

## 明确排除
1. 不要频繁跳槽
"""
    parsed = parse_screening_criteria_md(md)
    assert "不要频繁跳槽" in parsed.must_have
    assert parsed.reject_rules == []


def test_format_unstructured_legacy_numbered_lines():
    text = """简历筛选喜好：
1、西班牙语必须能作为工作语言。
2、必须要有美签（简历中未体现，可沟通确认）。
3、有ToB端销售经验可加分。"""
    md = format_unstructured_criteria(text, job_title="拉美中方销售")
    parsed = parse_screening_criteria_md(md)

    assert "西班牙语" in " ".join(parsed.must_have)
    assert any("美签" in item for item in parsed.must_have + parsed.followup_questions)
    assert any("ToB" in item for item in parsed.nice_to_have)


def test_merge_appends_into_sections_not_raw_concat():
    base = build_screening_criteria_md(
        ScreeningCriteriaDoc(
            job_title="薪酬绩效经理",
            must_have=["至少3年薪酬绩效经验"],
            nice_to_have=["985/211院校"],
        )
    )
    merged = merge_screening_criteria_md(
        base,
        must_have=["通过大学英语四级"],
        quick_reject_rules=["近一年内两次及以上主动跳槽"],
        reject_rules=["不要频繁跳槽"],
        nice_to_have=["有科技行业背景"],
    )

    assert "至少3年薪酬绩效经验" in merged
    assert "通过大学英语四级" in merged
    assert "不要频繁跳槽" in merged
    assert "近一年内两次及以上主动跳槽" in merged
    assert "## 必备" in merged
    assert "## 快速淘汰" in merged
    assert merged.count("## 必备") == 1
    assert "## 明确排除" not in merged
    assert "985/211院校" in merged
    assert "有科技行业背景" in merged


def test_quick_reject_section_is_preserved_separately():
    md = """岗位：测试岗

## 必备
1. 3 年以上同岗位经验

## 快速淘汰
1. 明确只接受异地且拒绝来深圳
"""
    parsed = parse_screening_criteria_md(md)

    assert parsed.must_have == ["3 年以上同岗位经验"]
    assert parsed.quick_reject_rules == ["明确只接受异地且拒绝来深圳"]


def test_normalize_preserves_existing_markdown():
    raw = """岗位：测试岗

## 必备
1. A

## 加分
1. B"""
    normalized = normalize_screening_criteria_md(raw, job_title="测试岗")
    assert normalized.startswith("岗位：测试岗")
    assert "1. A" in normalized
    assert "1. B" in normalized
    assert "## 必备" in normalized
