"""Tests for fuzzy resume library row matching."""

from services.fetch_worker.resume_library_row_match import (
    FUZZY_FIELD_THRESHOLD,
    ResumeLibraryMatchProfile,
    ResumeLibraryRow,
    find_resume_library_row,
    parse_row_from_cells,
    parse_row_from_full_text,
    score_row_fields,
)


def test_fuzzy_full_name_zeng_qin():
    """简历库列表可能显示完整姓名「曾琴」而非「曾**」。"""
    profile = ResumeLibraryMatchProfile(
        display_name="曾",
        surname="曾",
        age=25,
        education="本科",
        current_company="湖南中联重科智能高空作业机械有限公司",
        folder="追问",
    )
    cells = [
        "曾琴",
        "女",
        "25",
        "本科",
        "国际营销经理",
        "湖南中联重科智能高空作业机械有限公司",
        "2026-06-10",
    ]
    row = parse_row_from_cells(cells)
    assert row is not None
    assert row.name == "曾琴"
    assert row.age == 25
    assert row.company and "中联重科" in row.company

    scores = score_row_fields(profile, row)
    assert scores.all_above(FUZZY_FIELD_THRESHOLD)
    hit, _ = find_resume_library_row(profile, [row])
    assert hit is row

    # 整行文本（无「岁」）也必须能解析年龄
    line = "曾琴 女 25 本科 国际营销经理 湖南中联重科智能高空作业机械有限公司 今天"
    row_text = parse_row_from_full_text(line)
    assert row_text is not None
    assert row_text.age == 25
    scores2 = score_row_fields(profile, row_text)
    assert scores2.all_above(FUZZY_FIELD_THRESHOLD)


def test_fuzzy_long_company_abbreviated():
    profile = ResumeLibraryMatchProfile(
        display_name="曾",
        surname="曾",
        age=25,
        education="本科",
        current_company="湖南中联重科智能高空作业机械有限公司",
        folder="追问",
    )
    row = ResumeLibraryRow(
        name="曾**",
        gender="男",
        age=25,
        education="本科",
        title="机械工程师",
        company="中联重科智能高空作业机械",
        collect_time="今天",
        raw_text="曾** | 男 | 25 | 本科 | 机械工程师 | 中联重科智能高空作业机械 | 今天",
        index=0,
    )
    scores = score_row_fields(profile, row)
    assert scores.all_above(FUZZY_FIELD_THRESHOLD)
    hit, hit_scores = find_resume_library_row(profile, [row])
    assert hit is row
    assert hit_scores is not None


def test_fuzzy_rejects_low_age_match():
    profile = ResumeLibraryMatchProfile(
        display_name="曾",
        surname="曾",
        age=25,
        education="本科",
        current_company="湖南中联重科智能高空作业机械有限公司",
        folder="追问",
    )
    row = ResumeLibraryRow(
        name="曾**",
        gender="男",
        age=32,
        education="本科",
        title=None,
        company="湖南中联重科智能高空作业机械有限公司",
        collect_time=None,
        raw_text="",
        index=0,
    )
    scores = score_row_fields(profile, row)
    assert scores.age < FUZZY_FIELD_THRESHOLD
    hit, _ = find_resume_library_row(profile, [row])
    assert hit is None
