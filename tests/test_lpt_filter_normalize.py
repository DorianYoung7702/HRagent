"""Tests for LPT filter option normalization."""

from packages.schemas.workflow import LptEducationFilters, LptOtherFilters
from services.fetch_worker.lpt_filter_normalize import (
    extract_current_cities_from_text,
    extract_degree_from_text,
    extract_expected_cities_from_text,
    extract_school_tiers_from_text,
    normalize_education_filters,
    normalize_other_filters,
    normalize_school_tiers,
    resolve_lpt_option,
    split_city_lists_from_text,
)


def test_normalize_school_tiers_aliases():
    assert normalize_school_tiers(["985院校", "海归"]) == ["985", "海外留学"]


def test_normalize_degree():
    assert normalize_education_filters(LptEducationFilters(degree="硕士")).degree == "硕士"


def test_resolve_lpt_option_fuzzy():
    assert resolve_lpt_option(["今日活跃", "3日内活跃"], "3日内") == "3日内活跃"


def test_split_current_and_expected_cities():
    text = "目前base深圳，期望去北京，需要985本科"
    current, expected = split_city_lists_from_text(text)
    assert "深圳" in current
    assert "北京" in expected


def test_extract_current_cities_marker():
    assert extract_current_cities_from_text("现居上海，招聘销售") == ["上海"]


def test_extract_current_cities_equals_sign():
    assert extract_current_cities_from_text("目前=深圳，期望城市=北京") == ["深圳"]


def test_split_current_equals_in_parse_summary_style():
    text = "猎聘筛选 目前=深圳 期望=北京 经验3-5年"
    current, expected = split_city_lists_from_text(text)
    assert "深圳" in current
    assert "北京" in expected


def test_extract_expected_cities_marker():
    assert extract_expected_cities_from_text("期望去杭州") == ["杭州"]


def test_extract_school_tiers():
    assert extract_school_tiers_from_text("要求985或211") == ["985", "211"]


def test_extract_degree():
    assert extract_degree_from_text("统招本科以上") == "本科"


def test_normalize_other_filters_activity():
    other = normalize_other_filters(LptOtherFilters(activity="今日活跃"))
    assert other.activity == "今日活跃"
