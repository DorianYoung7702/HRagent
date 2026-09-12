"""Tests for resume library row matching."""

from services.fetch_worker.resume_library_row_match import (
    ResumeLibraryMatchProfile,
    ResumeLibraryRow,
    names_match,
    pick_best_resume_library_row,
    score_resume_library_row,
)


def test_names_match_honorific_vs_masked():
    assert names_match("潘女士", "潘**")
    assert names_match("潘**", "潘女士")
    assert names_match("潘", "潘女士")
    assert not names_match("潘女士", "李**")


def test_score_name_required():
    profile = ResumeLibraryMatchProfile(display_name="张三", folder="追问")
    row = ResumeLibraryRow(
        name="李四",
        gender="男",
        age=28,
        education="本科",
        title=None,
        company=None,
        collect_time=None,
        raw_text="",
    )
    assert score_resume_library_row(profile, row) < 0


def test_pick_best_row_by_name_age_education():
    profile = ResumeLibraryMatchProfile(
        display_name="张**",
        surname="张",
        gender="男",
        age=28,
        education="本科",
        current_title="销售经理",
        current_company="某科技有限公司",
        folder="追问",
    )
    rows = [
        ResumeLibraryRow("李**", "女", 26, "硕士", "工程师", "A公司", "今天", raw_text="", index=0),
        ResumeLibraryRow("张**", "男", 28, "本科", "销售经理", "某科技有限公司", "今天", raw_text="", index=1),
        ResumeLibraryRow("张**", "男", 30, "本科", "销售", "B公司", "昨天", raw_text="", index=2),
    ]
    best, score = pick_best_resume_library_row(profile, rows)
    assert best is not None
    assert best.name == "张**"
    assert best.age == 28
    assert best.company == "某科技有限公司"
    assert score == 1.0


def test_folder_from_job_folder_not_screening_level():
    profile = ResumeLibraryMatchProfile.from_candidate(
        display_name="王**",
        current_title="经理",
        current_company=None,
        education="本科",
        screening_level="observe",
        metadata={"age": 25, "gender": "女", "resume_library_decision": "observe"},
        job_folder="薪酬绩效经理",
    )
    assert profile.folder == "薪酬绩效经理"

    without_folder = ResumeLibraryMatchProfile.from_candidate(
        display_name="王**",
        current_title="经理",
        current_company=None,
        education="本科",
        screening_level="observe",
        metadata={"age": 25, "gender": "女"},
    )
    assert without_folder.folder == ""
