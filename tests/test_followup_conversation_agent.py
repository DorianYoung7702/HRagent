import pytest

from services.agent_service.followup_conversation_agent import generate_followup_message


@pytest.mark.asyncio
async def test_round1_uses_screening_followup_verbatim():
    question = (
        "您好，注意到您的西班牙语标注为A2基础水平。"
        "请问您在实际工作中是否能使用西语进行商务交流？"
    )
    out = await generate_followup_message(
        candidate_snapshot_id="snap-1",
        display_name="张三",
        current_title="销售经理",
        missing_info=[{"field": "spanish", "question": question, "importance": "high"}],
        screening_criteria="西班牙语必须能作为工作语言",
        followup_question=question,
        conversation_history=[],
        round_num=1,
        job_title="拉美中方销售",
    )
    assert out.message_text == question
    assert "美签" not in out.message_text
    assert "HRagent" not in out.message_text
