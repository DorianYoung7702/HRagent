"""Tests for experience filter relaxation."""

from services.fetch_worker.experience_fallback import (
    experience_relaxation_sequence,
    experience_try_sequence,
    initial_experience_filter,
    ladder_options_intersecting,
    next_experience_fallback,
    normalize_experience,
    primary_ladder_options,
    resolve_ladder_experience,
)


def test_normalize_experience():
    assert normalize_experience("3-5年") == "3-5年"
    assert normalize_experience("3至5年") == "3-5年"
    assert normalize_experience("3-10年") == "3-10年"
    assert normalize_experience("经验不限") == "不限"


def test_ladder_options_intersecting_3_10():
    assert ladder_options_intersecting(3, 10) == ["3-5年", "5-10年"]


def test_primary_ladder_options_splits_custom_range():
    assert primary_ladder_options("3-10年") == ["3-5年", "5-10年"]
    assert primary_ladder_options("3~10年") == ["3-5年", "5-10年"]


def test_initial_experience_filter_uses_first_ladder_segment():
    assert initial_experience_filter("3-10年") == "3-5年"
    assert initial_experience_filter("5-10年") == "5-10年"


def test_experience_try_sequence_3_10():
    seq = experience_try_sequence("3-10年")
    assert seq == ["3-5年", "5-10年"]
    assert "1-3年" not in seq
    assert "不限" not in seq


def test_try_sequence_single_ladder_no_downgrade():
    assert experience_try_sequence("3-5年") == ["3-5年"]
    assert experience_try_sequence("5-10年") == ["5-10年"]


def test_next_fallback_for_custom_range():
    tried = {"3-5年"}
    nxt = next_experience_fallback("3-5年", tried, requested="3-10年")
    assert nxt == "5-10年"


def test_resolve_ladder_experience():
    assert resolve_ladder_experience("3-10年") == "3-5年"
    assert resolve_ladder_experience("3-5年") == "3-5年"


def test_relaxation_from_3_5():
    seq = experience_relaxation_sequence("3-5年")
    assert seq[0] == "5-10年"
    assert "1-3年" in seq
    assert seq[-1] == "不限"


def test_next_fallback_skips_tried():
    tried = {"3-5年", "5-10年"}
    nxt = next_experience_fallback("5-10年", tried, requested="3-10年")
    assert nxt is None

    tried_single = {"3-5年"}
    nxt_single = next_experience_fallback("3-5年", tried_single, requested="3-5年")
    assert nxt_single is None


def test_no_fallback_from_unlimited():
    assert experience_relaxation_sequence("不限") == []
    assert next_experience_fallback("不限", {"不限"}, requested="不限") is None
