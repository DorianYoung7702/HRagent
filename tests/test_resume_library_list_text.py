"""Tests for resume library name-link row parsing."""

from services.fetch_worker.resume_library_row_match import (
    ResumeLibraryMatchProfile,
    ResumeLibraryRow,
    extract_name_from_row_text,
    is_resume_library_name,
    looks_like_candidate_row_text,
    parse_row_from_full_text,
    parse_row_from_list_text,
    pick_best_resume_library_row,
)


def test_is_resume_library_name():
    assert is_resume_library_name("陈**")
    assert is_resume_library_name("梁先生")
    assert is_resume_library_name("陈")
    assert is_resume_library_name("曾琴")
    assert not is_resume_library_name("未分组")
    assert not is_resume_library_name("本科")
    assert not is_resume_library_name("更多")


def test_parse_row_from_structured_cells_single_surname():
    from services.fetch_worker.resume_library_row_match import parse_row_from_cells

    row = parse_row_from_cells(
        ["陈", "男", "29", "本科", "销售经理", "深圳某生物科技股份有限公司", "今天 14:30"],
        index=0,
    )
    assert row is not None
    assert row.name == "陈"
    assert row.age == 29
    assert row.education == "本科"
    assert row.company and "生物" in row.company


def test_zhao_wrong_company_field_still_matches():
    """公司列误解析为职位时，应从 raw_text 中识别示例影像并命中。"""
    from services.fetch_worker.resume_library_row_match import (
        FUZZY_FIELD_THRESHOLD,
        ResumeLibraryRow,
        find_resume_library_row,
        score_row_fields,
    )

    profile = ResumeLibraryMatchProfile(
        display_name="赵",
        surname="赵",
        age=27,
        education="本科",
        current_company="示例影像科技股份有限公司",
        folder="拉美中方销售",
    )
    raw = (
        "赵先生 | 男 | 27 | 本科 | 墨西哥国家经理（墨西哥+秘鲁部分市场） | "
        "示例影像科技股份有限公司 | 2026-06-10"
    )
    row = ResumeLibraryRow(
        name="赵先生",
        gender="男",
        age=27,
        education="本科",
        title="墨西哥国家经理（墨西哥+秘鲁部分市场）",
        company="墨西哥国家经理（墨西哥+秘鲁部分市场）",
        collect_time="2026-06-10",
        raw_text=raw,
        index=0,
    )
    scores = score_row_fields(profile, row)
    assert scores.company >= FUZZY_FIELD_THRESHOLD
    assert scores.all_above(FUZZY_FIELD_THRESHOLD)
    hit, _ = find_resume_library_row(profile, [row])
    assert hit is row


def test_parse_row_with_leading_action_column():
    """首行常有「查看」操作列，不能当成姓名。"""
    from services.fetch_worker.resume_library_row_match import (
        parse_row_from_cells,
        score_row_fields,
        ResumeLibraryMatchProfile,
        find_resume_library_row,
        FUZZY_FIELD_THRESHOLD,
        is_resume_library_name,
    )

    assert not is_resume_library_name("查看")

    headers = ["姓名", "性别", "年龄", "学历", "目前职位", "目前公司", "收藏时间"]
    cells = [
        "查看",
        "曾琴",
        "女",
        "25",
        "本科",
        "国际营销经理",
        "湖南中联重科智能高空作业机械有限公司",
        "2026-06-10",
    ]
    row = parse_row_from_cells(cells, headers=headers)
    assert row is not None
    assert row.name == "曾琴"
    assert row.age == 25
    assert row.company and "中联重科" in row.company

    profile = ResumeLibraryMatchProfile(
        display_name="曾",
        surname="曾",
        age=25,
        education="本科",
        current_company="湖南中联重科智能高空作业机械有限公司",
        folder="追问",
    )
    scores = score_row_fields(profile, row)
    assert scores.all_above(FUZZY_FIELD_THRESHOLD)
    hit, _ = find_resume_library_row(profile, [row])
    assert hit is row


def test_parse_row_with_leading_checkbox_column():
    """全宽表格前置勾选列时，不能再用 cells[5] 当公司。"""
    from services.fetch_worker.resume_library_row_match import (
        parse_row_from_cells,
        parse_row_from_header_cells,
        row_matches_profile_strict,
        ResumeLibraryMatchProfile,
    )

    headers = ["姓名", "性别", "年龄", "学历", "目前职位", "目前公司", "收藏时间"]
    cells = ["赵**", "男", "27", "本科", "海外销售", "示例影像科技股份有限公司", "今天"]
    row = parse_row_from_header_cells(headers, cells)
    assert row is not None
    assert row.company and "示例影像" in row.company
    assert row.age == 27

    misaligned = ["☑", "赵**", "男", "27", "本科", "海外销售", "示例影像科技股份有限公司", "今天"]
    row2 = parse_row_from_cells(misaligned)
    assert row2 is not None
    assert row2.company and "示例影像" in row2.company
    assert row2.age == 27

    profile = ResumeLibraryMatchProfile(
        display_name="赵",
        surname="赵",
        age=27,
        education="本科",
        current_company="示例影像科技股份有限公司",
        folder="追问",
    )
    assert row_matches_profile_strict(profile, row2)


def test_extract_name_single_surname_line():
    line = "陈 男 29 本科 销售 深圳某生物科技股份有限公司"
    assert extract_name_from_row_text(line) == "陈"


def test_extract_name_from_full_row():
    line = "陈** 男 29岁 本科 海外渠道销售 深圳某生物科技股份有限公司 今天 14:30"
    assert extract_name_from_row_text(line) == "陈**"
    assert looks_like_candidate_row_text(line)


def test_parse_row_from_full_text():
    line = "陈** 男 29岁 本科 海外渠道销售 深圳某生物科技股份有限公司"
    row = parse_row_from_full_text(line, index=0)
    assert row is not None
    assert row.name == "陈**"
    assert row.age == 29
    assert row.education == "本科"
    assert row.company and "生物" in row.company


def test_parse_row_from_list_text():
    row = parse_row_from_list_text(
        "陈**",
        "陈** 男 29岁 本科 海外渠道销售 深圳某生物科技股份有限公司",
        index=0,
    )
    assert row is not None
    assert row.name == "陈**"
    assert row.age == 29
    assert row.education == "本科"
    assert row.company and "生物" in row.company


def test_pick_best_by_surname_age_edu_company():
    profile = ResumeLibraryMatchProfile(
        display_name="陈**",
        surname="陈",
        age=29,
        education="本科",
        current_company="深圳某生物科技股份有限公司",
        folder="追问",
    )
    rows = [
        ResumeLibraryRow("李**", None, 30, "硕士", None, "A公司", None, "李** 30岁", 0),
        ResumeLibraryRow(
            "陈",
            "男",
            29,
            "本科",
            None,
            "深圳某生物科技股份有限公司",
            None,
            "陈 | 男 | 29 | 本科 | 深圳某生物科技股份有限公司",
            1,
        ),
        ResumeLibraryRow("陈**", "男", 26, "本科", None, "B公司", None, "陈** 26岁", 2),
    ]
    best, score = pick_best_resume_library_row(profile, rows)
    assert best is not None
    assert best.age == 29
    assert best.company and "生物" in best.company
    assert score == 1.0
