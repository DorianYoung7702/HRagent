from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.schemas.workflow import RecruitingWorkflowConfig
    from services.workflow_worker.activities import (
        fetch_candidates_activity,
        generate_initial_report_activity,
        screen_candidates_activity,
        update_workflow_status_activity,
    )
    from services.workflow_worker.candidate_conversation_workflow import (
        CandidateConversationWorkflow,
    )


@workflow.defn
class RecruitingWorkflow:
    @workflow.run
    async def run(self, config: RecruitingWorkflowConfig | dict) -> dict:
        if isinstance(config, dict):
            config = RecruitingWorkflowConfig(**config)
        retry_policy = RetryPolicy(maximum_attempts=3)

        await workflow.execute_activity(
            update_workflow_status_activity,
            {"workflow_id": config.workflow_id, "status": "FETCHING"},
            start_to_close_timeout=timedelta(minutes=1),
        )

        fetch_result = await workflow.execute_activity(
            fetch_candidates_activity,
            {
                "platform": config.platform,
                "workflow_id": config.workflow_id,
                "start_url": config.start_url,
                "target_count": config.fetch.target_count,
                "max_pages": config.fetch.max_pages,
                "detail_required": config.fetch.detail_required,
                "browser_profile": config.fetch.browser_profile,
                "search": config.fetch.search.model_dump(),
            },
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=retry_policy,
        )

        fetch_status = "FETCH_COMPLETED" if fetch_result["captured_count"] > 0 else "PARTIAL_FAILED"
        await workflow.execute_activity(
            update_workflow_status_activity,
            {
                "workflow_id": config.workflow_id,
                "status": fetch_status,
                "fetch_task_id": fetch_result["fetch_task_id"],
            },
            start_to_close_timeout=timedelta(minutes=1),
        )

        await workflow.execute_activity(
            update_workflow_status_activity,
            {"workflow_id": config.workflow_id, "status": "SCREENING"},
            start_to_close_timeout=timedelta(minutes=1),
        )

        screening_result = await workflow.execute_activity(
            screen_candidates_activity,
            {"workflow_id": config.workflow_id, "config": config.model_dump()},
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=retry_policy,
        )

        await workflow.execute_activity(
            update_workflow_status_activity,
            {
                "workflow_id": config.workflow_id,
                "status": "SCREENING_COMPLETED",
                "shortlist_id": screening_result["shortlist_id"],
            },
            start_to_close_timeout=timedelta(minutes=1),
        )

        child_handles = []
        if config.outreach.enabled:
            for candidate in screening_result.get("shortlist", []):
                handle = await workflow.start_child_workflow(
                    CandidateConversationWorkflow.run,
                    {
                        "workflow_id": config.workflow_id,
                        "candidate_snapshot_id": candidate["candidate_snapshot_id"],
                        "screening_result": candidate,
                        "outreach_config": config.outreach.model_dump(),
                    },
                    id=f"candidate-conv-{candidate['candidate_snapshot_id']}",
                    task_queue=workflow.info().task_queue,
                )
                child_handles.append(handle)

            await workflow.execute_activity(
                update_workflow_status_activity,
                {"workflow_id": config.workflow_id, "status": "CONVERSATIONS_STARTED"},
                start_to_close_timeout=timedelta(minutes=1),
            )

        report = await workflow.execute_activity(
            generate_initial_report_activity,
            config.workflow_id,
            start_to_close_timeout=timedelta(minutes=10),
        )

        final_status = "COMPLETED" if fetch_result["captured_count"] > 0 else "PARTIAL_FAILED"
        await workflow.execute_activity(
            update_workflow_status_activity,
            {"workflow_id": config.workflow_id, "status": final_status},
            start_to_close_timeout=timedelta(minutes=1),
        )

        return {
            "fetch_result": fetch_result,
            "screening_result": screening_result,
            "report": report,
            "conversations_started": len(child_handles),
        }
