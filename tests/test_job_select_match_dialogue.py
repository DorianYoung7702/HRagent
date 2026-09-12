from services.fetch_worker.job_select_match import pick_best_job_card_index


def test_pick_job_card_compound_target_does_not_fuzzy_match():
    cards = [
        "海外销售经理 | 广州 | 机器人",
        "拉美中方销售 | 深圳 | 企业软件",
        "拉美中方销售 | 广州 | 企业软件",
    ]

    idx, score = pick_best_job_card_index(cards, "拉美中方销售 深圳 企业软件")

    assert idx == -1
    assert score == 0


def test_pick_job_card_matches_name_with_suffix_only():
    idx, score = pick_best_job_card_index(
        ["拉美中方销售 | 深圳 | 企业软件", "拉美中方销售-2024"],
        "拉美中方销售",
    )

    assert idx in (0, 1)
    assert score == 100


def test_pick_job_card_no_match_when_name_not_contained():
    idx, score = pick_best_job_card_index(
        ["财务主管 | 深圳", "行政专员 | 广州"],
        "拉美中方销售 深圳",
    )

    assert idx == -1
    assert score == 0
