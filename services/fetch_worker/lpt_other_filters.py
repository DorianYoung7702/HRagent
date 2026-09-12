"""猎聘 LPT「其他筛选」行：活跃/求职/跳槽/年龄/性别/语言/行业。"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from packages.schemas.workflow import LptOtherFilters
from services.fetch_worker.lpt_adapter import LPT_FILTER_OTHER_ROW, LPT_OTHER_FILTER_LABELS
from services.fetch_worker.lpt_filter_normalize import normalize_other_filters
from services.fetch_worker.lpt_filter_ops import (
    click_dropdown_option,
    click_filter_label,
    click_industry_option,
    confirm_filter_panel,
)

logger = logging.getLogger(__name__)

_INDUSTRY_FIELDS = frozenset({"grad_industry", "current_industry", "expected_industry"})

_FIELD_ORDER = (
    "activity",
    "job_seeking",
    "job_hop",
    "age",
    "gender",
    "language",
    "grad_industry",
    "current_industry",
    "expected_industry",
)


async def apply_lpt_dropdown_filter(page: Page, filter_label: str | list[str], option_text: str) -> bool:
    labels = [filter_label] if isinstance(filter_label, str) else list(filter_label)
    if not (option_text or "").strip():
        return False
    if not await click_filter_label(page, labels, row_anchors=LPT_FILTER_OTHER_ROW):
        if not await click_filter_label(page, labels):
            logger.warning("Cannot open filter: %s", labels[0])
            return False
    if await click_dropdown_option(page, option_text):
        await confirm_filter_panel(page)
        return True
    logger.warning("Cannot select %s for %s", option_text, labels[0])
    return False


async def apply_other_filters(page: Page, other: LptOtherFilters | None) -> dict[str, bool]:
    """Apply non-empty other-filter fields in fixed order."""
    normalized = normalize_other_filters(other)
    data = normalized.model_dump()
    results: dict[str, bool] = {}

    for field in _FIELD_ORDER:
        value = (data.get(field) or "").strip()
        if not value or value == "不限":
            continue
        labels = LPT_OTHER_FILTER_LABELS.get(field, [])
        if not labels:
            continue

        if field in _INDUSTRY_FIELDS:
            opened = await click_filter_label(page, labels, row_anchors=LPT_FILTER_OTHER_ROW)
            if not opened:
                opened = await click_filter_label(page, labels)
            ok = False
            if opened:
                ok = await click_industry_option(page, value)
                await confirm_filter_panel(page)
        else:
            ok = await apply_lpt_dropdown_filter(page, labels, value)

        results[field] = ok
        if not ok:
            logger.warning("Other filter failed: %s=%s", field, value)

    applied = {k: v for k, v in data.items() if (v or "").strip() and v != "不限"}
    if applied:
        from packages.workflow_events import emit

        emit(
            "info",
            f"其他筛选: {applied}",
            category="search",
            meta={"other_filters": applied, "results": results},
        )
    return results
