"""抓取循环调度监控：检测卡死并触发强制恢复。"""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Page


@dataclass
class PageSnapshot:
    list_cards: int
    has_resume_popup: bool
    has_job_select: bool
    list_interactive: bool
    url: str

    def state_key(self) -> str:
        return (
            f"cards={self.list_cards}"
            f"|resume={int(self.has_resume_popup)}"
            f"|job={int(self.has_job_select)}"
            f"|ok={int(self.list_interactive)}"
        )


class JobSelectStuckTracker:
    """岗位弹窗「选职位→确认」重复未关闭时判定卡死。"""

    REPEAT_LIMIT = 5

    def __init__(self) -> None:
        self.failed_cycles = 0

    def on_cycle_complete(self, still_visible: bool) -> tuple[bool, str]:
        if still_visible:
            self.failed_cycles += 1
        else:
            self.failed_cycles = 0
            return False, ""
        if self.failed_cycles >= self.REPEAT_LIMIT:
            return True, f"岗位弹窗重复操作 {self.failed_cycles} 次仍未关闭（可能未点到最上层浮层）"
        return False, ""

    def reset(self) -> None:
        self.failed_cycles = 0


class ExtractStuckMonitor:
    """监控 extract 主循环是否陷入无进展/浮层残留死循环。"""

    NO_PROGRESS_LIMIT = 5
    OVERLAY_STUCK_LIMIT = 4
    SAME_STATE_LIMIT = 3
    MAX_RECOVERIES = 8

    def __init__(self) -> None:
        self.last_processed = 0
        self.loop_count = 0
        self.no_progress_streak = 0
        self.overlay_streak = 0
        self.same_state_streak = 0
        self.last_state_key: str | None = None
        self.recovery_count = 0

    def on_loop_start(self, processed: int, snap: PageSnapshot) -> tuple[bool, str]:
        """每轮循环开始时更新指标，返回 (是否卡死, 原因)。"""
        self.loop_count += 1

        if processed > self.last_processed:
            self.no_progress_streak = 0
            self.last_processed = processed
        else:
            self.no_progress_streak += 1

        blocking = snap.has_resume_popup or snap.has_job_select or not snap.list_interactive
        if blocking:
            self.overlay_streak += 1
        else:
            self.overlay_streak = 0

        key = snap.state_key()
        if key == self.last_state_key:
            self.same_state_streak += 1
        else:
            self.same_state_streak = 0
            self.last_state_key = key

        job_streak = 0
        try:
            from services.fetch_worker.extract_popup import _get_job_select_tracker

            job_streak = _get_job_select_tracker().failed_cycles
        except Exception:
            pass
        return self._evaluate(snap, job_select_streak=job_streak)

    def on_recovery_done(self, snap: PageSnapshot) -> None:
        """强制恢复后重置连击计数（保留 recovery_count）。"""
        self.no_progress_streak = 0
        self.overlay_streak = 0
        self.same_state_streak = 0
        self.last_state_key = snap.state_key()
        self.recovery_count += 1

    def can_recover_again(self) -> bool:
        return self.recovery_count < self.MAX_RECOVERIES

    def _evaluate(self, snap: PageSnapshot, *, job_select_streak: int = 0) -> tuple[bool, str]:
        if job_select_streak >= JobSelectStuckTracker.REPEAT_LIMIT:
            return True, f"岗位弹窗重复操作 {job_select_streak} 次未关闭"
        if self.no_progress_streak >= self.NO_PROGRESS_LIMIT:
            return True, f"连续 {self.no_progress_streak} 轮无简历处理进展"
        if self.overlay_streak >= self.OVERLAY_STUCK_LIMIT:
            return True, f"连续 {self.overlay_streak} 轮列表被浮层遮挡"
        if self.same_state_streak >= self.SAME_STATE_LIMIT:
            return True, f"连续 {self.same_state_streak} 轮页面状态未变化 ({snap.state_key()})"
        if (
            not snap.list_interactive
            and (snap.has_resume_popup or snap.has_job_select)
            and self.overlay_streak >= 2
        ):
            return True, "列表不可操作且上方仍有简历/岗位卡片"
        return False, ""


async def capture_page_snapshot(
    page: Page,
    *,
    collect_cards,
    has_blocking_overlay,
    is_list_interactive,
    is_job_select_visible,
    is_popup_visible,
) -> PageSnapshot:
    cards = await collect_cards(page)
    return PageSnapshot(
        list_cards=len(cards),
        has_resume_popup=await is_popup_visible(page),
        has_job_select=await is_job_select_visible(page),
        list_interactive=await is_list_interactive(page),
        url=page.url,
    )
