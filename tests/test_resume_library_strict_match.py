"""Tests for strict resume library row matching."""

import pytest

from services.fetch_worker.resume_library_row_match import (
    ResumeLibraryMatchProfile,
    ResumeLibraryRow,
    age_matches_strict,
    company_matches_strict,
    education_matches_strict,
    find_strict_resume_library_row,
    pick_best_resume_library_row,
    row_matches_profile_strict,
    surname_matches_strict,
    validate_profile_for_library_match,
)


def _profile(**kwargs) -> ResumeLibraryMatchProfile:
    defaults = dict(
        display_name="陈**",
        surname="陈",
        age=29,
        education="本科",
        current_company="深圳某生物科技股份有限公司",
        folder="追问",
    )
    defaults.update(kwargs)
    return ResumeLibraryMatchProfile(**defaults)


def _row(**kwargs) -> ResumeLibraryRow:
    defaults = dict(
        name="陈**",
        gender="男",
        age=29,
        education="本科",
        title=None,
        company="深圳某生物科技股份有限公司",
        collect_time=None,
        raw_text="陈** 男 29岁 本科 深圳某生物科技股份有限公司",
        index=0,
    )
    defaults.update(kwargs)
    return ResumeLibraryRow(**defaults)


def test_strict_all_four_required():
    p = _profile()
    assert row_matches_profile_strict(p, _row())
    assert not row_matches_profile_strict(p, _row(age=28))
    assert not row_matches_profile_strict(p, _row(education="硕士"))
    assert not row_matches_profile_strict(p, _row(company="其他公司"))
    assert not row_matches_profile_strict(p, _row(name="李**"))


def test_validate_profile_missing_fields():
    with pytest.raises(ValueError, match="年龄"):
        validate_profile_for_library_match(_profile(age=None))


def test_find_strict_rejects_partial():
    p = _profile()
    rows = [_row(age=26), _row(name="李**")]
    assert find_strict_resume_library_row(p, rows) is None


def test_find_strict_unique_hit():
    p = _profile()
    hit = find_strict_resume_library_row(p, [_row(), _row(name="李**")])
    assert hit is not None
    assert hit.age == 29


def test_pick_best_strict():
    p = _profile()
    best, score = pick_best_resume_library_row(p, [_row(), _row(age=30)])
    assert best is not None
    assert score == 1.0
    assert best.age == 29


def test_surname_age_edu_company_helpers():
    p = _profile()
    r = _row()
    assert surname_matches_strict(p, r)
    assert age_matches_strict(p, r)
    assert education_matches_strict(p, r)
    assert company_matches_strict(p.current_company, r)
