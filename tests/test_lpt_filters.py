"""Tests for education/other filter apply orchestration."""

import pytest

from packages.schemas.workflow import LptEducationFilters, LptOtherFilters
from services.fetch_worker import lpt_education_filter
from services.fetch_worker.lpt_adapter import LPT_FILTER_EDU_ROW, LPT_FILTER_SCHOOL_TIER
from services.fetch_worker.lpt_education_filter import _apply_school_tiers, apply_education_filters
from services.fetch_worker.lpt_other_filters import apply_other_filters


class _FakePage:
    pass


@pytest.mark.asyncio
async def test_apply_education_filters_skips_empty():
    result = await apply_education_filters(_FakePage(), LptEducationFilters())
    assert result == {}


@pytest.mark.asyncio
async def test_school_tier_prefers_education_row_chip(monkeypatch):
    calls = []

    async def fake_chip(page, option_text, *, row_anchors=None, allow_global_fallback=True):
        calls.append(("chip", option_text, row_anchors, allow_global_fallback))
        return True

    async def fake_label(*args, **kwargs):
        calls.append(("label", args, kwargs))
        return True

    monkeypatch.setattr(lpt_education_filter, "click_chip_option", fake_chip)
    monkeypatch.setattr(lpt_education_filter, "click_filter_label", fake_label)

    result = await _apply_school_tiers(_FakePage(), ["985"])

    assert result is True
    assert calls == [("chip", "985", LPT_FILTER_EDU_ROW, False)]


@pytest.mark.asyncio
async def test_school_tier_opens_same_education_row_label_when_chip_missing(monkeypatch):
    calls = []

    async def fake_chip(page, option_text, *, row_anchors=None, allow_global_fallback=True):
        calls.append(("chip", option_text, row_anchors, allow_global_fallback))
        return False

    async def fake_label(page, label_texts, *, row_anchors=None):
        calls.append(("label", label_texts, row_anchors))
        return True

    async def fake_dropdown(page, option_text, *, allow_global_chip_fallback=True):
        calls.append(("dropdown", option_text, allow_global_chip_fallback))
        return True

    async def fake_confirm(page):
        calls.append(("confirm",))
        return True

    monkeypatch.setattr(lpt_education_filter, "click_chip_option", fake_chip)
    monkeypatch.setattr(lpt_education_filter, "click_filter_label", fake_label)
    monkeypatch.setattr(lpt_education_filter, "click_dropdown_option", fake_dropdown)
    monkeypatch.setattr(lpt_education_filter, "confirm_filter_panel", fake_confirm)

    result = await _apply_school_tiers(_FakePage(), ["985", "211"])

    assert result is True
    assert calls == [
        ("chip", "985", LPT_FILTER_EDU_ROW, False),
        ("chip", "211", LPT_FILTER_EDU_ROW, False),
        ("label", [LPT_FILTER_SCHOOL_TIER], LPT_FILTER_EDU_ROW),
        ("dropdown", "985", False),
        ("dropdown", "211", False),
        ("confirm",),
    ]


@pytest.mark.asyncio
async def test_school_tier_does_not_open_global_school_label(monkeypatch):
    calls = []

    async def fake_chip(page, option_text, *, row_anchors=None, allow_global_fallback=True):
        return False

    async def fake_label(page, label_texts, *, row_anchors=None):
        calls.append((label_texts, row_anchors))
        return False

    monkeypatch.setattr(lpt_education_filter, "click_chip_option", fake_chip)
    monkeypatch.setattr(lpt_education_filter, "click_filter_label", fake_label)

    result = await _apply_school_tiers(_FakePage(), ["985"])

    assert result is False
    assert calls == [([LPT_FILTER_SCHOOL_TIER], LPT_FILTER_EDU_ROW)]


@pytest.mark.asyncio
async def test_apply_other_filters_skips_empty():
    result = await apply_other_filters(_FakePage(), LptOtherFilters())
    assert result == {}
