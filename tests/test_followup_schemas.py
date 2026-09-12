"""Tests for followup outreach schemas."""

from packages.schemas.outreach import (
    FollowupConversationOutput,
    FollowupReplyEnrichmentOutput,
    ResumeRequestOutput,
)


def test_followup_conversation_output_defaults():
    out = FollowupConversationOutput(message_text="您好，请问是否持有美签？")
    assert out.action == "draft_message"
    assert out.auto_send_allowed is False


def test_reply_enrichment_output():
    out = FollowupReplyEnrichmentOutput(
        need_resume_request=True,
        summary_for_list="候选人确认有美签",
        updated_level="observe",
    )
    assert out.need_resume_request
    assert out.updated_level == "observe"


def test_resume_request_output():
    out = ResumeRequestOutput(message_text="方便发一份简历吗？")
    assert "简历" in out.message_text
