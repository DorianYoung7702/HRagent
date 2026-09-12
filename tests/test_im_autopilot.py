"""Tests for IM autopilot decision routing."""

from unittest.mock import AsyncMock, patch

import pytest

from services.agent_service import im_autopilot


@pytest.mark.asyncio
async def test_auto_outreach_followup_path():
    draft = {
        "conversation_id": "c1",
        "candidate_snapshot_id": "s1",
        "display_name": "张三",
        "message_text": "请问是否有美签？",
        "round": 1,
    }
    with (
        patch.object(
            im_autopilot,
            "is_chat_initiated",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(
            im_autopilot,
            "is_prior_communication",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(
            im_autopilot,
            "_workflow_im_review_required",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(
            im_autopilot,
            "prepare_followup_for_candidate",
            new_callable=AsyncMock,
            return_value=draft,
        ),
        patch.object(
            im_autopilot,
            "_send_single_draft",
            new_callable=AsyncMock,
            return_value={"ok": True, "conversation_id": "c1"},
        ),
    ):
        result = await im_autopilot.auto_outreach_for_candidate("wf1", "s1", "追问")
    assert result is not None
    assert result["action"] == "追问"
    assert result["send"]["ok"] is True


@pytest.mark.asyncio
async def test_auto_outreach_observe_path():
    draft = {
        "conversation_id": "c2",
        "candidate_snapshot_id": "s2",
        "display_name": "李四",
        "message_text": "方便发一份简历吗？",
        "round": 1,
        "action": "要简历",
    }
    with (
        patch.object(
            im_autopilot,
            "is_chat_initiated",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(
            im_autopilot,
            "is_prior_communication",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(
            im_autopilot,
            "_workflow_im_review_required",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(
            im_autopilot,
            "prepare_resume_for_candidate",
            new_callable=AsyncMock,
            return_value=draft,
        ),
        patch.object(
            im_autopilot,
            "_send_single_draft",
            new_callable=AsyncMock,
            return_value={"ok": True, "conversation_id": "c2"},
        ),
    ):
        result = await im_autopilot.auto_outreach_for_candidate("wf1", "s2", "观察")
    assert result is not None
    assert result["action"] == "要简历"


@pytest.mark.asyncio
async def test_auto_outreach_review_mode_keeps_draft_only():
    draft = {
        "conversation_id": "c1",
        "candidate_snapshot_id": "s1",
        "display_name": "张三",
        "message_text": "请问是否有美签？",
        "round": 2,
    }
    with (
        patch.object(
            im_autopilot,
            "is_chat_initiated",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(
            im_autopilot,
            "is_prior_communication",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(
            im_autopilot,
            "_workflow_im_review_required",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(
            im_autopilot,
            "prepare_followup_for_candidate",
            new_callable=AsyncMock,
            return_value=draft,
        ),
        patch.object(
            im_autopilot,
            "_send_single_draft",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        result = await im_autopilot.auto_outreach_for_candidate("wf1", "s1", "追问")
    assert result is not None
    assert result["review_pending"] is True
    assert result["send"] is None
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_outreach_skips_unknown_decision():
    result = await im_autopilot.auto_outreach_for_candidate("wf1", "s1", "排除")
    assert result is None


@pytest.mark.asyncio
async def test_auto_outreach_skips_without_chat_initiated():
    with patch.object(
        im_autopilot,
        "is_chat_initiated",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await im_autopilot.auto_outreach_for_candidate("wf1", "s1", "追问")
    assert result is None


@pytest.mark.asyncio
async def test_auto_outreach_skips_prior_communication():
    with (
        patch.object(
            im_autopilot,
            "is_chat_initiated",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(
            im_autopilot,
            "is_prior_communication",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(
            im_autopilot,
            "prepare_followup_for_candidate",
            new_callable=AsyncMock,
        ) as mock_prepare,
    ):
        result = await im_autopilot.auto_outreach_for_candidate("wf1", "s1", "追问")
    assert result is None
    mock_prepare.assert_not_awaited()


def test_stop_im_autopilot_sets_flag():
    im_autopilot._get_stop_event("wf-stop").clear()
    result = im_autopilot.stop_im_autopilot("wf-stop")
    assert result["stopped"] is True
    assert im_autopilot.is_im_autopilot_stopped("wf-stop")
    im_autopilot._get_stop_event("wf-stop").clear()


@pytest.mark.asyncio
async def test_start_im_autopilot_skips_duplicate_monitor():
    with (
        patch.object(
            im_autopilot,
            "run_im_autopilot_cycle",
            new_callable=AsyncMock,
            return_value={"enriched": 1, "enrich_sent": 0, "catchup_sent": 0},
        ),
        patch.object(im_autopilot, "run_im_autopilot_monitor", new_callable=AsyncMock),
    ):
        im_autopilot._monitor_running.add("wf1")
        try:
            result = await im_autopilot.start_im_autopilot("wf1")
        finally:
            im_autopilot._monitor_running.discard("wf1")
    assert result["status"] == "cycle_only"
    assert result["already_running"] is True


@pytest.mark.asyncio
async def test_schedule_auto_im_outreach_ignores_stop_flag():
    with (
        patch.object(im_autopilot, "is_im_autopilot_stopped", return_value=True),
        patch.object(
            im_autopilot,
            "auto_outreach_for_candidate",
            new_callable=AsyncMock,
            return_value={"review_pending": True, "send": None},
        ) as mock_auto,
    ):
        result = await im_autopilot.schedule_auto_im_outreach("wf1", "s1", "追问")
    assert result is not None
    mock_auto.assert_awaited_once_with("wf1", "s1", "追问", respect_im_stop=False)


@pytest.mark.asyncio
async def test_auto_outreach_respects_stop_by_default():
    with patch.object(im_autopilot, "is_im_autopilot_stopped", return_value=True):
        result = await im_autopilot.auto_outreach_for_candidate("wf1", "s1", "追问")
    assert result is None
    enriched = [
        {
            "ok": True,
            "candidate_snapshot_id": "s1",
            "updated_level": "observe",
            "need_resume_request": True,
        }
    ]
    with patch.object(
        im_autopilot,
        "auto_outreach_for_candidate",
        new_callable=AsyncMock,
        return_value={"send": {"ok": True}},
    ) as mock_auto:
        sent = await im_autopilot._process_enrichment_actions("wf1", enriched)
    assert sent == 1
    mock_auto.assert_awaited_once_with("wf1", "s1", "观察")
