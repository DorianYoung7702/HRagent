from services.fetch_worker.keyword_fallback import (
    dedupe_search_keyword_tokens,
    ensure_required_search_keywords,
    filter_keywords_for_search,
    is_filter_only_term,
    is_protected_search_term,
    is_screening_only_term,
    keyword_relaxation_exhausted,
    next_keyword_fallback,
    split_keywords,
)


def test_split_keywords_space_separated():
    assert split_keywords("西班牙语 电子类 海外销售") == ["西班牙语", "电子类", "海外销售"]


def test_screening_only_term():
    assert is_screening_only_term("电子类")
    assert not is_screening_only_term("西班牙语")


def test_protected_search_terms():
    assert is_protected_search_term("西班牙语")
    assert is_protected_search_term("西语")
    assert is_protected_search_term("销售")
    assert is_protected_search_term("海外销售")
    assert not is_protected_search_term("美签")


def test_next_keyword_drops_screening_term_first():
    current = "西班牙语 电子类 海外销售"
    nxt = next_keyword_fallback(current, {current})
    assert nxt == "西班牙语 海外销售"
    assert "西班牙语" in nxt
    assert "销售" in nxt


def test_next_keyword_never_drops_spanish_or_sales():
    current = "西班牙语 美签 销售"
    tried = {current}
    nxt = next_keyword_fallback(current, tried)
    assert nxt == "西班牙语 销售"
    assert next_keyword_fallback("西班牙语 销售", {"西班牙语 销售", nxt}) is None


def test_keyword_relaxation_exhausted_at_minimum():
    assert keyword_relaxation_exhausted("西班牙语 销售")
    assert not keyword_relaxation_exhausted("西班牙语 美签 销售")


def test_filter_keywords_for_search():
    assert filter_keywords_for_search("西班牙语 电子类 美签 销售") == "西班牙语 美签 销售"


def test_filter_keywords_removes_structured_filter_terms():
    assert filter_keywords_for_search("开发工程师 架构师 深圳 年经验") == "开发工程师 架构师"
    assert filter_keywords_for_search("开发工程师 深圳 1-5年 20份") == "开发工程师"
    assert filter_keywords_for_search("西班牙语 销售 深圳 3-5年") == "西班牙语 销售"


def test_filter_only_terms():
    assert is_filter_only_term("深圳")
    assert is_filter_only_term("1-5年")
    assert is_filter_only_term("3年以上")
    assert is_filter_only_term("20份")
    assert is_filter_only_term("目前=深圳")
    assert not is_filter_only_term("开发工程师")


def test_dedupe_sales_when_compound_present():
    assert dedupe_search_keyword_tokens(["西班牙语", "美签", "海外销售", "销售"]) == [
        "西班牙语",
        "美签",
        "海外销售",
    ]
    assert filter_keywords_for_search("西班牙语 美签 海外销售 销售") == "西班牙语 美签 海外销售"


def test_ensure_required_search_keywords_from_source():
    out = ensure_required_search_keywords(
        "美签 海外",
        "拉美中方销售，西班牙语流利",
    )
    assert "西班牙语" in out
    assert "销售" in out


def test_no_fallback_when_single_keyword():
    assert next_keyword_fallback("海外销售", {"海外销售"}) is None
