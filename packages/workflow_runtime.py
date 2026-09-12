"""Detect live workflow execution and reconcile stale DB rows after API restart."""



from __future__ import annotations



import logging



from packages.background_tasks import has_workflow_tasks

from packages.db.repositories import WorkflowRepository

from packages.db.session import async_session_factory



logger = logging.getLogger(__name__)



STARTING_STATUSES = frozenset({"CREATED"})

FETCH_SCREEN_STATUSES = frozenset({"CREATED", "FETCHING", "FETCH_COMPLETED", "SCREENING"})

PIPELINE_STATUSES = frozenset(

    {

        "CREATED",

        "FETCHING",

        "FETCH_COMPLETED",

        "SCREENING",

        "SCREENING_COMPLETED",

        "CONVERSATIONS_STARTED",

    }

)

STALE_RUNTIME_STATUSES = frozenset(FETCH_SCREEN_STATUSES)



# Workflows started in this API process; stay in the console task bar until explicit exit.

_session_workflows: set[str] = set()





def register_workflow_session(workflow_id: str) -> None:

    _session_workflows.add(workflow_id)





def unregister_workflow_session(workflow_id: str) -> None:

    _session_workflows.discard(workflow_id)





def is_workflow_session_registered(workflow_id: str) -> bool:

    return workflow_id in _session_workflows





def is_workflow_starting(workflow_id: str, status: str) -> bool:

    """True while a workflow is bootstrapping (record created, fetch not yet running)."""

    return status in STARTING_STATUSES and is_workflow_execution_live(workflow_id)





def is_workflow_active_for_console(workflow_id: str, status: str) -> bool:

    """True when a workflow belongs in the running-task bar (live, waiting, or IM phase)."""

    from packages.workflow_control import is_cancelled



    if is_cancelled(workflow_id):

        return False

    if status in ("COMPLETED", "FAILED", "CANCELLED"):

        return False

    if status == "PARTIAL_FAILED":

        return is_workflow_execution_live(workflow_id)

    if status not in PIPELINE_STATUSES:

        return False

    if is_workflow_execution_live(workflow_id):

        return True

    return is_workflow_session_registered(workflow_id)





def is_workflow_execution_live(workflow_id: str) -> bool:

    """True when fetch/screen/IM work is actively running in this API process."""

    if has_workflow_tasks(workflow_id):

        return True



    from services.agent_service.im_autopilot import is_im_autopilot_active

    from services.agent_service.reply_judgment_runner import reply_judgment_status



    if is_im_autopilot_active(workflow_id):

        return True

    if reply_judgment_status(workflow_id).get("running"):

        return True

    return False





def is_workflow_suspended(workflow_id: str, status: str, *, paused: bool = False) -> bool:

    """True when a registered workflow is waiting (paused or between async steps)."""

    if not is_workflow_session_registered(workflow_id):

        return False

    if status not in PIPELINE_STATUSES:

        return False

    if is_workflow_execution_live(workflow_id):

        return False

    return paused or status in FETCH_SCREEN_STATUSES





async def reconcile_stale_workflows_on_startup() -> int:

    """Mark orphaned in-progress rows as stopped after server restart."""

    async with async_session_factory() as session:

        repo = WorkflowRepository(session)

        workflows = await repo.list_by_statuses(STALE_RUNTIME_STATUSES)

        if not workflows:

            return 0



        reconciled = 0

        for wf in workflows:

            message = "服务重启或异常中断，任务已停止，请重新启动"
            if wf.platform == "local_pdf":
                message = "PDF 导入在服务重启时中断，请重新上传未完成的简历"

            await repo.update_status(

                wf.id,

                "PARTIAL_FAILED",

                error_message=message,

            )

            reconciled += 1

        await session.commit()

        return reconciled

