"""猎聘 LPT 教育经历行筛选：学历 chip + 院校要求。"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from packages.schemas.workflow import LptEducationFilters
from services.fetch_worker.lpt_adapter import (
    LPT_FILTER_EDU_ROW,
    LPT_FILTER_SCHOOL_TIER,
    LPT_SCHOOL_TIER_OPTIONS,
)
from services.fetch_worker.lpt_filter_normalize import normalize_education_filters
from services.fetch_worker.lpt_filter_ops import (
    click_chip_option,
    click_filter_label,
    click_dropdown_option,
    confirm_filter_panel,
)

logger = logging.getLogger(__name__)


async def _apply_degree(page: Page, degree: str) -> bool:
    if not degree or degree == "不限":
        return False
    if await click_chip_option(page, degree, row_anchors=LPT_FILTER_EDU_ROW, allow_global_fallback=False):
        return True
    if await click_filter_label(page, LPT_FILTER_EDU_ROW):
        return await click_dropdown_option(page, degree, allow_global_chip_fallback=False)
    return False


async def _apply_school_tiers(page: Page, tiers: list[str]) -> bool:
    if not tiers:
        return False

    pending: list[str] = []
    ok_any = False
    for tier in tiers:
        if tier not in LPT_SCHOOL_TIER_OPTIONS:
            continue
        if await click_chip_option(
            page,
            tier,
            row_anchors=LPT_FILTER_EDU_ROW,
            allow_global_fallback=False,
        ):
            ok_any = True
            continue
        pending.append(tier)

    if not pending:
        return ok_any

    opened = await click_filter_label(page, [LPT_FILTER_SCHOOL_TIER], row_anchors=LPT_FILTER_EDU_ROW)
    if not opened:
        logger.warning("Cannot open 院校要求 panel in 教育经历 row")
        return ok_any

    for tier in pending:
        if await click_dropdown_option(page, tier, allow_global_chip_fallback=False):
            ok_any = True

    await confirm_filter_panel(page)
    return ok_any


async def apply_education_filters(page: Page, education: LptEducationFilters | None) -> dict[str, bool]:
    """Best-effort apply education row filters; empty fields are skipped."""
    edu = normalize_education_filters(education)
    results: dict[str, bool] = {}

    if edu.degree:
        results["degree"] = await _apply_degree(page, edu.degree)
        if not results["degree"]:
            logger.warning("Failed to select degree: %s", edu.degree)

    if edu.school_tiers:
        results["school_tiers"] = await _apply_school_tiers(page, edu.school_tiers)
        if not results["school_tiers"]:
            logger.warning("Failed to select school tiers: %s", edu.school_tiers)

    if results:
        from packages.workflow_events import emit

        emit(
            "info",
            f"教育筛选: 学历={edu.degree or '—'} 院校={','.join(edu.school_tiers) or '—'}",
            category="search",
            meta={"education": edu.model_dump()},
        )
    return results
