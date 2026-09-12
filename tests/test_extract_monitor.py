"""Tests for extract loop stuck monitor."""

from services.fetch_worker.extract_monitor import ExtractStuckMonitor, JobSelectStuckTracker, PageSnapshot


def _snap(**kwargs) -> PageSnapshot:
    defaults = dict(
        list_cards=5,
        has_resume_popup=False,
        has_job_select=False,
        list_interactive=True,
        url="https://lpt.liepin.com/search",
    )
    defaults.update(kwargs)
    return PageSnapshot(**defaults)


def test_no_stuck_when_progressing():
    m = ExtractStuckMonitor()
    stuck, _ = m.on_loop_start(1, _snap())
    assert not stuck
    stuck, _ = m.on_loop_start(2, _snap())
    assert not stuck


def test_stuck_on_no_progress():
    m = ExtractStuckMonitor()
    for _ in range(ExtractStuckMonitor.NO_PROGRESS_LIMIT):
        stuck, reason = m.on_loop_start(0, _snap())
    assert stuck
    assert "无简历处理进展" in reason


def test_stuck_on_overlay():
    m = ExtractStuckMonitor()
    blocked = _snap(has_resume_popup=True, list_interactive=False)
    stuck = False
    for _ in range(ExtractStuckMonitor.OVERLAY_STUCK_LIMIT):
        stuck, reason = m.on_loop_start(0, blocked)
    assert stuck
    assert "浮层遮挡" in reason


def test_job_select_stuck_after_five_cycles():
    t = JobSelectStuckTracker()
    stuck = False
    for _ in range(JobSelectStuckTracker.REPEAT_LIMIT):
        stuck, reason = t.on_cycle_complete(True)
    assert stuck
    assert "岗位弹窗重复操作" in reason


def test_job_select_resets_on_success():
    t = JobSelectStuckTracker()
    for _ in range(3):
        t.on_cycle_complete(True)
    t.on_cycle_complete(False)
    stuck, _ = t.on_cycle_complete(True)
    assert not stuck
    assert t.failed_cycles == 1


def test_recovery_resets_streak():
    m = ExtractStuckMonitor()
    blocked = _snap(has_resume_popup=True, list_interactive=False)
    for _ in range(3):
        m.on_loop_start(0, blocked)
    m.on_recovery_done(_snap())
    stuck, _ = m.on_loop_start(0, _snap())
    assert not stuck
