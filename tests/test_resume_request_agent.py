"""Tests for resume request agent helpers."""

from services.agent_service.resume_request_agent import (
    _normalize_message_text,
    fallback_resume_request_output,
)


def test_normalize_plain_text():
    assert _normalize_message_text("  方便发一份简历吗？  ") == "方便发一份简历吗？"


def test_normalize_json_wrapped_text():
    raw = '{"message_text": "您好，方便发简历吗？"}'
    assert _normalize_message_text(raw) == "您好，方便发简历吗？"


def test_fallback_resume_request_output():
    out = fallback_resume_request_output(
        candidate_snapshot_id="snap-1",
        display_name="张",
        job_title="拉美中方销售",
    )
    assert out.candidate_snapshot_id == "snap-1"
    assert "简历" in out.message_text
    assert "拉美中方销售" in out.message_text
