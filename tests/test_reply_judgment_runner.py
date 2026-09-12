"""Tests for manual reply judgment runner."""

from unittest.mock import AsyncMock, patch

import pytest

from services.agent_service import reply_judgment_runner


def test_reply_judgment_status_defaults():
    reply_judgment_runner._status.clear()
    reply_judgment_runner._running.clear()
    st = reply_judgment_runner.reply_judgment_status("wf-new")
    assert st["phase"] == "standby"
    assert st["running"] is False
    assert "待机" in st["message"]


def test_stop_reply_judgment_sets_flag():
    reply_judgment_runner._running.add("wf-stop")
    try:
        result = reply_judgment_runner.stop_reply_judgment("wf-stop")
        assert result["stopped"] is True
        assert reply_judgment_runner._get_stop_event("wf-stop").is_set()
    finally:
        reply_judgment_runner._running.discard("wf-stop")
        reply_judgment_runner._get_stop_event("wf-stop").clear()


@pytest.mark.asyncio
async def test_start_reply_judgment_empty_queue_runs_summary_report():
    reply_judgment_runner._status.clear()
    reply_judgment_runner._running.clear()
    with (
        patch.object(
            reply_judgment_runner,
            "list_reply_judgment_targets",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            reply_judgment_runner,
            "run_serial_reply_judgment",
            new_callable=AsyncMock,
        ) as mock_run,
        patch.object(
            reply_judgment_runner,
            "generate_reply_judgment_summary_report",
            new_callable=AsyncMock,
            return_value={
                "workflow_id": "wf-empty",
                "ranked_candidates": [],
                "summary": "No replies, ranked existing candidates.",
            },
        ) as mock_summary,
    ):
        result = await reply_judgment_runner.start_reply_judgment("wf-empty")
    mock_run.assert_not_called()
    mock_summary.assert_awaited_once()
    assert result["phase"] == "standby"
    assert result["report_ready"] is True
    assert result["summary_report"]["summary"] == "No replies, ranked existing candidates."
    assert result["already_running"] is False


@pytest.mark.asyncio
async def test_start_reply_judgment_serial_run():
    reply_judgment_runner._status.clear()
    reply_judgment_runner._running.clear()
    queue = [{"candidate_snapshot_id": "s1", "display_name": "张三"}]
    with (
        patch.object(
            reply_judgment_runner,
            "list_reply_judgment_targets",
            new_callable=AsyncMock,
            return_value=queue,
        ),
        patch.object(
            reply_judgment_runner,
            "run_serial_reply_judgment",
            new_callable=AsyncMock,
            return_value=[
                {
                    "candidate_snapshot_id": "s1",
                    "display_name": "张三",
                    "ok": True,
                    "updated_level": "observe",
                    "summary_for_list": "美签已确认",
                }
            ],
        ),
        patch.object(
            reply_judgment_runner,
            "generate_reply_judgment_summary_report",
            new_callable=AsyncMock,
            return_value={
                "workflow_id": "wf-run",
                "ranked_candidates": [
                    {
                        "candidate_snapshot_id": "s1",
                        "display_name": "寮犱笁",
                        "rank": 1,
                        "priority": "high",
                        "recommendation": "top",
                        "risk_points": [],
                        "talking_points": [],
                    }
                ],
                "summary": "One candidate ready.",
            },
        ) as mock_summary,
        patch.object(reply_judgment_runner, "_workflow_im_lock") as mock_lock,
    ):
        mock_lock.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_lock.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await reply_judgment_runner.start_reply_judgment("wf-run")
    mock_summary.assert_awaited_once()
    assert result["enriched"] == 1
    assert result["passed"] == 1
    assert result["report_ready"] is True
    assert result["summary_report"]["summary"] == "One candidate ready."
    assert result["phase"] == "standby"


@pytest.mark.asyncio
async def test_start_reply_judgment_does_not_summarize_when_stopped_after_serial():
    reply_judgment_runner._status.clear()
    reply_judgment_runner._running.clear()
    queue = [{"candidate_snapshot_id": "s1", "display_name": "Stopped"}]

    async def fake_run(*args, **kwargs):
        reply_judgment_runner._get_stop_event("wf-stopped").set()
        return [
            {
                "candidate_snapshot_id": "s1",
                "display_name": "Stopped",
                "ok": True,
                "updated_level": "observe",
                "followup_passed": True,
            }
        ]

    with (
        patch.object(
            reply_judgment_runner,
            "list_reply_judgment_targets",
            new_callable=AsyncMock,
            return_value=queue,
        ),
        patch.object(
            reply_judgment_runner,
            "run_serial_reply_judgment",
            new_callable=AsyncMock,
            side_effect=fake_run,
        ),
        patch.object(
            reply_judgment_runner,
            "generate_reply_judgment_summary_report",
            new_callable=AsyncMock,
        ) as mock_summary,
        patch.object(reply_judgment_runner, "_workflow_im_lock") as mock_lock,
    ):
        mock_lock.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_lock.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await reply_judgment_runner.start_reply_judgment("wf-stopped")

    mock_summary.assert_not_called()
    assert result["phase"] == "stopped"
    assert result["report_ready"] is False


def test_inbound_already_stored():
    from services.agent_service.followup_conversation_service import _inbound_already_stored

    class Msg:
        def __init__(self, direction, text):
            self.direction = direction
            self.message_text = text

    msgs = [Msg("outbound", "你好"), Msg("inbound", "有的，美签")]
    assert _inbound_already_stored(msgs, "有的，美签") is True
    assert _inbound_already_stored(msgs, "新回复") is False
