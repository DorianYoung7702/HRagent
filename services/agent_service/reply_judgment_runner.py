"""Manual final-judgment runner: process replies when present, then rank candidates."""

from __future__ import annotations

import asyncio
import logging

from packages.workflow_events import emit
from services.agent_service.followup_conversation_service import (
    list_reply_judgment_targets,
    run_serial_reply_judgment,
)
from services.agent_service.im_autopilot import _workflow_im_lock
from services.agent_service.reply_summary_agent import generate_reply_judgment_summary_report

logger = logging.getLogger(__name__)

_running: set[str] = set()
_stop_events: dict[str, asyncio.Event] = {}
_status: dict[str, dict] = {}


def _default_status() -> dict:
    return {
        "running": False,
        "phase": "standby",
        "total": 0,
        "current_index": 0,
        "current_name": None,
        "processed": 0,
        "enriched": 0,
        "passed": 0,
        "still_followup": 0,
        "excluded": 0,
        "skipped": 0,
        "failed": 0,
        "results": [],
        "report_ready": False,
        "summary_report": None,
        "report_error": None,
        "message": "待机：可手动启动最终判定",
    }


def _get_stop_event(workflow_id: str) -> asyncio.Event:
    if workflow_id not in _stop_events:
        _stop_events[workflow_id] = asyncio.Event()
    return _stop_events[workflow_id]


def _set_status(workflow_id: str, **kwargs) -> dict:
    base = dict(_status.get(workflow_id) or _default_status())
    base.update(kwargs)
    _status[workflow_id] = base
    return base


def reply_judgment_status(workflow_id: str) -> dict:
    st = dict(_status.get(workflow_id) or _default_status())
    st["running"] = workflow_id in _running
    return st


def _level_counts(results: list[dict]) -> dict:
    completed = [r for r in results if r.get("ok") and not r.get("skipped")]
    return {
        "passed": sum(1 for r in completed if r.get("updated_level") == "observe"),
        "still_followup": sum(1 for r in completed if r.get("updated_level") == "followup"),
        "excluded": sum(1 for r in completed if r.get("updated_level") == "exclude"),
    }


def stop_reply_judgment(workflow_id: str) -> dict:
    was_running = workflow_id in _running
    _get_stop_event(workflow_id).set()
    if was_running:
        emit(
            "info",
            "已请求停止最终判定 Agent",
            category="reply_judgment",
            workflow_id=workflow_id,
        )
    _set_status(workflow_id, phase="stopped", message="已停止")
    return {"stopped": True, "was_running": was_running}


async def _run_summary_phase(
    workflow_id: str,
    stop_ev: asyncio.Event,
    *,
    results: list[dict],
    message: str,
) -> dict:
    enriched = sum(1 for r in results if r.get("ok") and not r.get("skipped"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = sum(1 for r in results if not r.get("ok"))
    counts = _level_counts(results)

    _set_status(
        workflow_id,
        running=True,
        phase="summarizing",
        processed=len(results),
        enriched=enriched,
        skipped=skipped,
        failed=failed,
        **counts,
        results=results[-20:],
        current_name=None,
        report_ready=False,
        summary_report=None,
        report_error=None,
        message=message,
    )

    summary_report = None
    report_error = None
    try:
        summary_report = await generate_reply_judgment_summary_report(
            workflow_id,
            should_stop=stop_ev.is_set,
        )
    except Exception as e:
        logger.exception("reply summary ranking failed for %s", workflow_id)
        report_error = str(e)
        emit(
            "warn",
            f"候选总结排名 Agent 异常: {e}",
            category="reply_judgment",
            workflow_id=workflow_id,
        )

    if stop_ev.is_set():
        return _set_status(
            workflow_id,
            running=False,
            phase="stopped",
            processed=len(results),
            enriched=enriched,
            skipped=skipped,
            failed=failed,
            **counts,
            results=results[-20:],
            current_name=None,
            report_ready=False,
            summary_report=None,
            report_error=report_error,
            message="已停止，未生成完整候选总结排名报告",
        )

    report_ready = bool(summary_report)
    final_message = (
        f"全部完成：终判 {enriched} 人，通过 {counts['passed']} 人，"
        f"仍需追问 {counts['still_followup']} 人，排除 {counts['excluded']} 人，"
        f"跳过 {skipped} 人，失败 {failed} 人。"
        + ("候选总结报告已生成。" if report_ready else "候选总结报告未生成。")
    )
    if not results:
        final_message = (
            "暂无待处理回复，已直接生成候选总结排名报告。"
            if report_ready
            else "暂无待处理回复，候选总结排名报告未生成。"
        )
    if report_error:
        final_message += f" 总结排名失败：{report_error}"

    return _set_status(
        workflow_id,
        running=False,
        phase="standby",
        processed=len(results),
        enriched=enriched,
        skipped=skipped,
        failed=failed,
        **counts,
        results=results[-20:],
        current_name=None,
        report_ready=report_ready,
        summary_report=summary_report,
        report_error=report_error,
        message=final_message,
    )


async def _run_serial(workflow_id: str) -> dict:
    stop_ev = _get_stop_event(workflow_id)
    stop_ev.clear()

    queue = await list_reply_judgment_targets(workflow_id)
    total = len(queue)
    _set_status(
        workflow_id,
        running=True,
        phase="judging",
        total=total,
        current_index=0,
        current_name=None,
        processed=0,
        enriched=0,
        passed=0,
        still_followup=0,
        excluded=0,
        skipped=0,
        failed=0,
        results=[],
        report_ready=False,
        summary_report=None,
        report_error=None,
        message=f"开始检查回复并终判，共 {total} 人",
    )
    emit(
        "info",
        f"最终判定启动：待检查回复 {total} 人",
        category="reply_judgment",
        workflow_id=workflow_id,
    )

    if total == 0:
        return await _run_summary_phase(
            workflow_id,
            stop_ev,
            results=[],
            message="暂无待处理回复，直接生成候选总结排名报告",
        )

    def on_progress(index: int, count: int, name: str) -> None:
        _set_status(
            workflow_id,
            current_index=index,
            total=count,
            current_name=name,
            message=f"正在处理 {name}（{index}/{count}）",
        )

    async with _workflow_im_lock(workflow_id):
        results = await run_serial_reply_judgment(
            workflow_id,
            should_stop=stop_ev.is_set,
            on_progress=on_progress,
        )

    if stop_ev.is_set():
        enriched = sum(1 for r in results if r.get("ok") and not r.get("skipped"))
        skipped = sum(1 for r in results if r.get("skipped"))
        failed = sum(1 for r in results if not r.get("ok"))
        counts = _level_counts(results)
        return _set_status(
            workflow_id,
            running=False,
            phase="stopped",
            processed=len(results),
            enriched=enriched,
            skipped=skipped,
            failed=failed,
            **counts,
            results=results[-20:],
            current_name=None,
            report_ready=False,
            summary_report=None,
            message="已停止，未生成候选总结排名报告",
        )

    return await _run_summary_phase(
        workflow_id,
        stop_ev,
        results=results,
        message="回复终判完成，候选总结排名 Agent 正在生成报告",
    )


async def start_reply_judgment(workflow_id: str) -> dict:
    if workflow_id in _running:
        st = reply_judgment_status(workflow_id)
        return {"already_running": True, **st}

    _running.add(workflow_id)
    try:
        summary = await _run_serial(workflow_id)
        return {"already_running": False, **summary}
    except Exception as e:
        logger.exception("reply judgment failed for %s", workflow_id)
        emit(
            "warn",
            f"最终判定 Agent 异常: {e}",
            category="reply_judgment",
            workflow_id=workflow_id,
        )
        return _set_status(
            workflow_id,
            running=False,
            phase="standby",
            message=f"运行异常: {e}",
        )
    finally:
        _running.discard(workflow_id)
