from services.agent_service.candidate_dialogue_agent import generate_candidate_dialogue_reply


def test_dialogue_agent_auto_replies_when_salary_profile_is_present():
    out = generate_candidate_dialogue_reply(
        candidate_snapshot_id="snap-1",
        latest_message="What is the salary range?",
        conversation_history=[],
        candidate_profile={"display_name": "Alice"},
        workflow_config={},
        job_qa_profile={"salary_range": "15-25K, 13薪"},
        hr_preference_memory={},
    )

    assert out.action == "auto_reply"
    assert out.question_type == "salary"
    assert out.auto_send_allowed is True
    assert out.answer_source == "job_qa_profile.salary_range"
    assert "15-25K" in out.message_text


def test_dialogue_agent_escalates_when_required_profile_field_is_missing():
    out = generate_candidate_dialogue_reply(
        candidate_snapshot_id="snap-1",
        latest_message="What is the salary range?",
        conversation_history=[],
        candidate_profile={"display_name": "Alice"},
        workflow_config={},
        job_qa_profile={"work_location": "Shenzhen"},
        hr_preference_memory={},
    )

    assert out.action == "escalate_to_hr"
    assert out.question_type == "salary"
    assert out.auto_send_allowed is False
    assert out.answer_source == ""
    assert "confirm" in out.message_text.lower()


def test_dialogue_agent_uses_context_for_short_followup_question():
    out = generate_candidate_dialogue_reply(
        candidate_snapshot_id="snap-1",
        latest_message="And location?",
        conversation_history=[
            {"direction": "inbound", "message_text": "What is the salary range?"},
            {"direction": "outbound", "message_text": "The salary range is 15-25K."},
        ],
        candidate_profile={"display_name": "Alice"},
        workflow_config={},
        job_qa_profile={"work_location": "Shenzhen Nanshan"},
        hr_preference_memory={},
    )

    assert out.action == "auto_reply"
    assert out.question_type == "work_location"
    assert out.history_used is True
    assert "Shenzhen Nanshan" in out.message_text
