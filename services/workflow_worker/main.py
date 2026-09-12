import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from packages.settings import get_settings
from services.workflow_worker.activities import (
    create_conversation_state_activity,
    fetch_candidates_activity,
    generate_initial_report_activity,
    generate_outreach_message_activity,
    mark_no_reply_or_followup_activity,
    parse_candidate_reply_activity,
    screen_candidates_activity,
    send_or_draft_platform_message_activity,
    update_candidate_profile_and_rescreen_activity,
    update_workflow_status_activity,
)
from services.workflow_worker.candidate_conversation_workflow import CandidateConversationWorkflow
from services.workflow_worker.recruiting_workflow import RecruitingWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
    )

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[RecruitingWorkflow, CandidateConversationWorkflow],
        activities=[
            fetch_candidates_activity,
            screen_candidates_activity,
            create_conversation_state_activity,
            generate_outreach_message_activity,
            send_or_draft_platform_message_activity,
            parse_candidate_reply_activity,
            update_candidate_profile_and_rescreen_activity,
            mark_no_reply_or_followup_activity,
            generate_initial_report_activity,
            update_workflow_status_activity,
        ],
    )

    logger.info("Temporal worker started on queue: %s", settings.temporal_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
