from services.fetch_worker.lpt_city_picker import (
    _allow_generic_city_chip_fallback,
    _is_current_city_row,
    _labels_for_city_row,
    extract_cities_from_text,
    normalize_city_list,
    pick_other_on_city_row,
    pick_other_on_expect_city_row,
    resolve_city_row_label,
)
from services.fetch_worker.lpt_adapter import (
    LPT_FILTER_CITY,
    LPT_FILTER_CITY_WRONG,
    LPT_FILTER_CURRENT_CITY,
    LPT_FILTER_EXPECT_CITY,
    LptSearchParams,
)


def test_normalize_single_city():
    assert normalize_city_list("深圳") == ["深圳"]


def test_normalize_multiple_cities():
    assert normalize_city_list("深圳、北京 上海") == ["深圳", "北京", "上海"]


def test_normalize_max_five():
    cities = ["深圳", "北京", "上海", "广州", "杭州", "成都"]
    assert normalize_city_list(cities=cities) == ["深圳", "北京", "上海", "广州", "杭州"]


def test_extract_cities_from_text():
    text = "需要深圳或北京、上海的西班牙语销售"
    assert extract_cities_from_text(text) == ["深圳", "北京", "上海"]


def test_lpt_search_params_resolved_cities():
    params = LptSearchParams(city="深圳", cities=["北京"])
    assert params.resolved_cities() == ["深圳", "北京"]


def test_city_filter_label_constants():
    assert LPT_FILTER_CITY == "期望城市"
    assert "目标城市" in LPT_FILTER_CITY_WRONG
    assert "目前城市" in LPT_FILTER_CITY_WRONG


def test_city_row_helpers_resolve_current_and_expect_rows():
    current_label = LPT_FILTER_CURRENT_CITY[0]

    assert resolve_city_row_label(current_label) == current_label
    assert resolve_city_row_label("目标城市") == LPT_FILTER_EXPECT_CITY
    assert _is_current_city_row(current_label) is True
    assert _is_current_city_row(LPT_FILTER_EXPECT_CITY) is False
    assert _labels_for_city_row(current_label) == list(LPT_FILTER_CURRENT_CITY)
    assert _labels_for_city_row(LPT_FILTER_EXPECT_CITY) == [LPT_FILTER_EXPECT_CITY]


def test_pick_other_on_current_city_row():
    # 第一行 目前城市: 其他 y=100；第二行 期望城市: 其他 y=160
    current_y, current_x = 100.0, 80.0
    others = [
        (100.0, 520.0, 300.0),  # 目前城市行 — 应选中
        (158.0, 520.0, 300.0),  # 期望城市行 — 应排除
    ]
    assert pick_other_on_city_row(current_y, current_x, others) == 0


def test_pick_other_prefers_nearest_row_before_rightmost():
    current_y, current_x = 100.0, 80.0
    others = [
        (100.0, 360.0, 300.0),  # 目前城市行：正确目标
        (145.0, 980.0, 300.0),  # 期望城市行：更靠右，但不是同一行
    ]

    assert pick_other_on_city_row(current_y, current_x, others) == 0


def test_current_city_does_not_use_generic_chip_fallback():
    assert _allow_generic_city_chip_fallback(LPT_FILTER_CURRENT_CITY[0]) is False
    assert _allow_generic_city_chip_fallback(LPT_FILTER_EXPECT_CITY) is True


def test_pick_other_on_expect_city_row():
    # 第一行 目前城市: 其他 y=100；第二行 期望城市: 其他 y=160
    expect_y, expect_x = 160.0, 80.0
    others = [
        (100.0, 200.0, 400.0),  # 目前城市行 — 应排除
        (158.0, 520.0, 300.0),  # 期望城市行 — 应选中
        (159.0, 300.0, 300.0),
    ]
    assert pick_other_on_expect_city_row(expect_y, expect_x, others) == 1


def test_pick_other_skips_left_of_expect_label():
    expect_y, expect_x = 160.0, 200.0
    others = [(160.0, 120.0, 100.0), (160.0, 400.0, 100.0)]
    assert pick_other_on_expect_city_row(expect_y, expect_x, others) == 1
