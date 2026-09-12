"""Phase 2 IM 追问 API。"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from packages.asyncio_compat import run_on_playwright_loop
from packages.background_tasks import spawn
from packages.db.repositories import WorkflowRepository
from packages.runtime_guards import require_hr_identity_for_im

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["followup"])


class IMSendRequest(BaseModel):
    confirmed: bool = False


def _require_im_guards() -> None:
    require_hr_identity_for_im()


# 初筛+shortlist 完成后才可准备 IM 追问（抓取进行中尚无追问清单）
_FOLLOWUP_READY_STATUSES = frozenset({
    "SCREENING_COMPLETED",
    "CONVERSATIONS_STARTED",
    "PARTIAL_FAILED",
})


async def _require_followup_ready(workflow_id: str, status: str) -> None:
    if status in _FOLLOWUP_READY_STATUSES:
        return
    if status == "FETCHING":
        from services.agent_service.followup_conversation_service import count_followup_candidates

        n = await count_followup_candidates(workflow_id)
        if n > 0:
            return
        raise HTTPException(
            400,
            detail="抓取进行中，尚无追问候选人；判定为「追问」后会自动生成草稿，也可稍后再点「生成追问草稿」",
        )
    hints = {
        "SCREENING": "正在生成 Shortlist，请稍候几秒后重试",
        "FETCH_COMPLETED": "抓取刚结束，正在汇总追问清单，请稍候后重试",
        "CREATED": "任务尚未开始执行",
    }
    detail = hints.get(status, f"当前状态不可准备追问: {status}")
    raise HTTPException(400, detail)


@router.post("/{workflow_id}/followup/im-prepare")
async def followup_im_prepare(workflow_id: str, db: AsyncSession = Depends(get_db)):
    _require_im_guards()
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    await _require_followup_ready(workflow_id, wf.status)

    from services.agent_service.followup_conversation_service import prepare_followup_messages

    drafts = await prepare_followup_messages(workflow_id)
    new_count = sum(1 for d in drafts if not d.get("reused_existing"))
    reused_count = len(drafts) - new_count
    return {
        "workflow_id": workflow_id,
        "drafts": drafts,
        "count": len(drafts),
        "new_count": new_count,
        "reused_count": reused_count,
    }


@router.post("/{workflow_id}/followup/im-send")
async def followup_im_send(
    workflow_id: str,
    body: IMSendRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    _require_im_guards()
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if not body.confirmed:
        raise HTTPException(400, "首轮发送需要 confirmed=true")

    async def _run():
        from services.agent_service.followup_conversation_service import confirm_and_send_batch

        return await confirm_and_send_batch(workflow_id, confirmed=True)

    spawn(run_on_playwright_loop(_run()))
    return {"workflow_id": workflow_id, "status": "IM_SEND_STARTED", "message": "IM 追问发送已在后台启动（与抓取并行，共用浏览器新标签页）"}


@router.post("/{workflow_id}/followup/im-send-sync")
async def followup_im_send_sync(
    workflow_id: str,
    body: IMSendRequest,
    db: AsyncSession = Depends(get_db),
):
    """同步发送（调试/脚本用）。"""
    _require_im_guards()
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if not body.confirmed:
        raise HTTPException(400, "首轮发送需要 confirmed=true")

    from services.agent_service.followup_conversation_service import confirm_and_send_batch

    results = await run_on_playwright_loop(confirm_and_send_batch(workflow_id, confirmed=True))
    return {"workflow_id": workflow_id, "results": results}


@router.post("/{workflow_id}/followup/scan-unread")
async def followup_scan_unread(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    _require_im_guards()
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    async def _run():
        from services.agent_service.followup_conversation_service import run_im_unread_scan_and_enrich

        return await run_im_unread_scan_and_enrich(workflow_id)

    spawn(run_on_playwright_loop(_run()))
    return {"workflow_id": workflow_id, "status": "IM_SCAN_STARTED"}


@router.post("/{workflow_id}/followup/continue")
async def followup_continue(workflow_id: str, background_tasks: BackgroundTasks):
    _require_im_guards()
    async def _run():
        from services.agent_service.followup_conversation_service import continue_followup

        return await continue_followup(workflow_id)

    spawn(run_on_playwright_loop(_run()))
    return {"workflow_id": workflow_id, "status": "IM_CONTINUE_STARTED"}


@router.post("/{workflow_id}/observe/im-request-resume")
async def observe_im_request_resume(
    workflow_id: str,
    body: IMSendRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    _require_im_guards()
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if not body.confirmed:
        raise HTTPException(400, "需要 confirmed=true")

    async def _run():
        from services.agent_service.followup_conversation_service import send_observe_resume_batch

        return await send_observe_resume_batch(workflow_id, confirmed=True)

    spawn(run_on_playwright_loop(_run()))
    return {"workflow_id": workflow_id, "status": "RESUME_REQUEST_STARTED"}


_IM_AUTOPILOT_READY = frozenset({
    "FETCHING",
    "FETCH_COMPLETED",
    "SCREENING",
    "SCREENING_COMPLETED",
    "CONVERSATIONS_STARTED",
    "PARTIAL_FAILED",
})


@router.post("/{workflow_id}/followup/im-autopilot-stop")
async def followup_im_autopilot_stop(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """停止 IM Agent，恢复简历抓取/筛选。"""
    from packages.workflow_control import resume_workflow
    from packages.workflow_events import emit
    from services.agent_service.im_autopilot import stop_im_autopilot

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    result = stop_im_autopilot(workflow_id)
    resume_workflow(workflow_id)

    if wf.status == "CONVERSATIONS_STARTED":
        await repo.update_status(workflow_id, "SCREENING_COMPLETED")
        await db.commit()

    emit(
        "info",
        "已停止 IM Agent，已切回简历筛选",
        category="im_autopilot",
        workflow_id=workflow_id,
    )
    return {
        "workflow_id": workflow_id,
        "status": "IM_AUTOPILOT_STOPPED",
        "message": "已停止 IM Agent，抓取/筛选可继续",
        **result,
    }


@router.get("/{workflow_id}/followup/im-autopilot-status")
async def followup_im_autopilot_status(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from services.agent_service.im_autopilot import im_autopilot_status

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return {"workflow_id": workflow_id, **im_autopilot_status(workflow_id)}


@router.post("/{workflow_id}/followup/im-autopilot-start")
async def followup_im_autopilot_start(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """手动启动 IM Agent：补发遗漏、同步回复、自动追问/要简历。"""
    _require_im_guards()
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if wf.status not in _IM_AUTOPILOT_READY:
        raise HTTPException(
            400,
            detail=f"当前状态「{wf.status}」不可启动 IM Agent，请等待抓取或初筛开始",
        )

    async def _run():
        from services.agent_service.im_autopilot import start_im_autopilot

        return await start_im_autopilot(workflow_id)

    spawn(run_on_playwright_loop(_run()))
    return {
        "workflow_id": workflow_id,
        "status": "IM_AUTOPILOT_STARTED",
        "message": "IM Agent 已在后台启动（同步回复 → 自动追问/要简历）",
    }


@router.get("/{workflow_id}/conversations")
async def list_conversations(workflow_id: str, db: AsyncSession = Depends(get_db)):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    from services.agent_service.followup_conversation_service import list_workflow_conversations

    convs = await list_workflow_conversations(workflow_id)
    return {"workflow_id": workflow_id, "conversations": convs}


@router.get("/{workflow_id}/reply-judgment/queue")
async def reply_judgment_queue(workflow_id: str, db: AsyncSession = Depends(get_db)):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    from services.agent_service.followup_conversation_service import list_reply_judgment_targets

    queue = await list_reply_judgment_targets(workflow_id)
    return {"workflow_id": workflow_id, "queue": queue, "count": len(queue)}


@router.get("/{workflow_id}/reply-judgment/status")
async def reply_judgment_status_route(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from services.agent_service.reply_judgment_runner import reply_judgment_status

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return {"workflow_id": workflow_id, **reply_judgment_status(workflow_id)}


@router.get("/{workflow_id}/reply-judgment/report")
async def reply_judgment_report(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from services.agent_service.reply_summary_agent import normalize_summary_report_payload

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    report = (wf.config or {}).get("reply_judgment_summary_report")
    report = normalize_summary_report_payload(report if isinstance(report, dict) else None)
    return {
        "workflow_id": workflow_id,
        "ready": isinstance(report, dict),
        "report": report,
    }


@router.post("/{workflow_id}/reply-judgment/start")
async def reply_judgment_start(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """手动启动最终判定：先串行回复终判，再生成候选总结排名报告。"""
    _require_im_guards()
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    from services.agent_service.reply_judgment_runner import reply_judgment_status, start_reply_judgment

    if reply_judgment_status(workflow_id).get("running"):
        return {
            "workflow_id": workflow_id,
            "status": "REPLY_JUDGMENT_ALREADY_RUNNING",
            "message": "回复判定 Agent 已在运行",
        }

    async def _run():
        return await start_reply_judgment(workflow_id)

    spawn(run_on_playwright_loop(_run()))
    return {
        "workflow_id": workflow_id,
        "status": "REPLY_JUDGMENT_STARTED",
        "message": "最终判定已启动：回复终判完成后会自动生成候选总结排名报告",
    }


@router.post("/{workflow_id}/reply-judgment/stop")
async def reply_judgment_stop(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from services.agent_service.reply_judgment_runner import stop_reply_judgment

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    result = stop_reply_judgment(workflow_id)
    return {
        "workflow_id": workflow_id,
        "status": "REPLY_JUDGMENT_STOPPED",
        "message": "已请求停止回复判定 Agent",
        **result,
    }
