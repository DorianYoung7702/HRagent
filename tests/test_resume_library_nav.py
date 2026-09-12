"""Tests for resume library sidebar folder matching."""

import re

from services.fetch_worker.resume_library_nav import (
    _MAIN_PANEL_MIN_X_RATIO,
    _folder_tab_labels,
    _row_text_matches_hint,
)
from services.fetch_worker.resume_library_row_match import ResumeLibraryRow


def _matches_any(text: str, patterns: list[str]) -> bool:
    if "未分组" in text:
        return False
    return any(re.fullmatch(p, text) for p in patterns)


def test_folder_tab_labels_reject_decision_tags():
    assert _folder_tab_labels("观察") == []
    assert _folder_tab_labels("追问") == []
    assert _folder_tab_labels("observe") == []


def test_row_text_matches_hint_honorific_vs_masked():
    row = ResumeLibraryRow(
        name="潘女士",
        gender="女",
        age=35,
        education="本科",
        title=None,
        company="某科技",
        collect_time=None,
        raw_text="潘** 女 35 本科 销售 某科技股份有限公司",
    )
    assert _row_text_matches_hint(row, "潘** 女 35 本科 销售 某科技股份有限公司")
    assert not _row_text_matches_hint(row, "李** 女 35 本科 销售 某公司")


def test_main_panel_min_x_ratio():
    assert _MAIN_PANEL_MIN_X_RATIO >= 0.20


def test_folder_tab_labels_custom_job_folder():
    patterns = _folder_tab_labels("Latam Sales Shenzhen")

    assert _matches_any("Latam Sales Shenzhen", patterns)
    assert _matches_any("Latam Sales Shenzhen(7)", patterns)
    assert not _matches_any("observe(1)", patterns)
    assert not _matches_any("followup(2)", patterns)
    assert not _matches_any("观察(9)", patterns)
    assert not _matches_any("候选(20)", patterns)
