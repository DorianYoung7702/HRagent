"""Tests for LPT filter constants completeness."""

from services.fetch_worker.lpt_adapter import (
    LPT_DEGREE_OPTIONS,
    LPT_OTHER_FILTER_LABELS,
    LPT_OTHER_FILTER_OPTIONS,
    LPT_SCHOOL_TIER_OPTIONS,
)


def test_school_tier_options_nonempty():
    assert "985" in LPT_SCHOOL_TIER_OPTIONS
    assert "海外留学" in LPT_SCHOOL_TIER_OPTIONS


def test_degree_options_nonempty():
    assert "本科" in LPT_DEGREE_OPTIONS


def test_other_filter_labels_match_fields():
    for field in (
        "activity",
        "job_seeking",
        "job_hop",
        "age",
        "gender",
        "language",
        "grad_industry",
        "current_industry",
        "expected_industry",
    ):
        assert field in LPT_OTHER_FILTER_LABELS
        assert LPT_OTHER_FILTER_LABELS[field]


def test_other_filter_options_have_choices_for_non_industry():
    for field in ("activity", "job_seeking", "job_hop", "age", "gender", "language"):
        opts = LPT_OTHER_FILTER_OPTIONS[field]
        assert len(opts) >= 2
        assert opts[0] == "不限"
