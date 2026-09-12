from services.fetch_worker.job_select_match import (
    extract_chat_job_title,
    job_card_matches,
    pick_best_job_card_index,
    score_job_card,
)


def test_extract_chat_job_title_from_screening():
    text = "岗位：拉美中方销售（深圳）\n要求西班牙语流利"
    assert extract_chat_job_title(text) == "拉美中方销售"


def test_extract_chat_job_title_from_job_name_field():
    text = "岗位名称：薪酬绩效经理\n## 硬性条件\n1. 3年以上薪酬绩效经验"
    assert extract_chat_job_title(text) == "薪酬绩效经理"


def test_extract_chat_job_title_fallback():
    assert extract_chat_job_title("", fallback="海外销售经理") == "海外销售经理"


def test_score_job_card_exact_substring_only():
    assert score_job_card("拉美中方销售 | 深圳", "拉美中方销售") == 100
    assert score_job_card("深圳 拉美销售主管", "拉美中方销售") == 0


def test_job_card_matches_with_trailing_job_code():
    assert job_card_matches("嵌入式工程师 J2024001", "嵌入式工程师")
    assert not job_card_matches("嵌入式开发", "嵌入式工程师")


def test_pick_best_job_card_index():
    cards = [
        "ToB 大客户销售（深圳）",
        "拉美中方销售 | 深圳",
        "渠道经理",
    ]
    idx, score = pick_best_job_card_index(cards, "拉美中方销售")
    assert idx == 1
    assert score == 100


def test_pick_best_job_card_prefers_prefix_and_shorter_card():
    cards = [
        "职位名称\n拉美中方销售\n工作城市 深圳",
        "职位名称\n拉美中方销售 J001\n工作城市 深圳",
        "职位名称\n海外销售\n工作城市 广州",
    ]
    idx, score = pick_best_job_card_index(cards, "拉美中方销售")
    assert idx == 0
    assert score == 100


def test_pick_best_job_card_embedded_engineer_with_suffix():
    cards = [
        "嵌入式开发",
        "嵌入式工程师 J2024001",
    ]
    idx, score = pick_best_job_card_index(cards, "嵌入式工程师")
    assert idx == 1
    assert score == 100
