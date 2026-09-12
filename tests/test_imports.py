import inspect


def test_api_app_import():
    from apps.api.main import app

    assert app.title == "招聘多 Agent 协作系统"


def test_workflow_worker_import():
    from services.workflow_worker.candidate_conversation_workflow import (
        CandidateConversationWorkflow,
    )
    from services.workflow_worker.recruiting_workflow import RecruitingWorkflow

    assert RecruitingWorkflow is not None
    assert CandidateConversationWorkflow is not None


def test_agent_service_import():
    from services.agent_service.outreach_agent import create_outreach_agent
    from services.agent_service.reply_parser_agent import create_reply_parser_agent
    from services.agent_service.rescreening_agent import create_rescreening_agent
    from services.agent_service.screening_agent import create_screening_agent

    assert all(
        inspect.isfunction(fn)
        for fn in (
            create_screening_agent,
            create_outreach_agent,
            create_reply_parser_agent,
            create_rescreening_agent,
        )
    )


def test_fetch_worker_import():
    from services.fetch_worker.message_sender import send_platform_message
    from services.fetch_worker.runner import run_fetch_task

    assert callable(run_fetch_task)
    assert callable(send_platform_message)
