"""Temporal client wrapper for workflow orchestration."""

import logging
from datetime import timedelta

from temporalio.client import Client

from packages.schemas.workflow import RecruitingWorkflowConfig
from packages.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def get_temporal_client() -> Client:
    return await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
    )


async def start_recruiting_workflow(config: RecruitingWorkflowConfig) -> str:
    from services.workflow_worker.recruiting_workflow import RecruitingWorkflow

    client = await get_temporal_client()
    workflow_id = f"recruiting-{config.workflow_id}"

    handle = await client.start_workflow(
        RecruitingWorkflow.run,
        config,
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
        execution_timeout=timedelta(days=7),
    )
    logger.info("Started RecruitingWorkflow: %s", workflow_id)
    return handle.id


async def signal_candidate_reply(
    temporal_workflow_id: str, message: dict
) -> None:
    from services.workflow_worker.candidate_conversation_workflow import (
        CandidateConversationWorkflow,
    )

    client = await get_temporal_client()
    handle = client.get_workflow_handle(temporal_workflow_id)
    await handle.signal(CandidateConversationWorkflow.candidate_reply_received, message)
    logger.info("Signaled reply to workflow: %s", temporal_workflow_id)
