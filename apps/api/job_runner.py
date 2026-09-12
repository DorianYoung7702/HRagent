"""Background job runner."""

import asyncio
import logging

from packages.asyncio_compat import run_on_playwright_loop
from packages.db.repositories import WorkflowRepository
from packages.db.session import async_session_factory
from packages.schemas.candidate import FetchInput
from packages.schemas.workflow import RecruitingWorkflowConfig

logger = logging.getLogger(__name__)

DB_RETRY_ATTEMPTS = 5
DB_RETRY_DELAY_SEC = 0.5


async def _with_db_retry(coro_factory):
    last_err = None
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            return await coro_factory()
        except Exception as e:
            if "locked" not in str(e).lower() or attempt == DB_RETRY_ATTEMPTS - 1:
                raise
            last_err = e
            await asyncio.sleep(DB_RETRY_DELAY_SEC * (attempt + 1))
    raise last_err


async def run_fetch_job(workflow_id: str, config: RecruitingWorkflowConfig) -> None:
    from packages.workflow_control import WorkflowCancelledError, clear_workflow_control, resume_global
    from packages.workflow_events import emit
    from services.fetch_worker.runner import run_fetch_task

    resume_global()

    if config.platform == "liepin":
        from services.fetch_worker.workflow_browser_profile import ensure_workflow_browser_profile

        profile = ensure_workflow_browser_profile(workflow_id)
        config.fetch.browser_profile = profile

        async def _persist_profile():
            async with async_session_factory() as session:
                repo = WorkflowRepository(session)
                await repo.patch_fetch(workflow_id, browser_profile=profile)
                await session.commit()

        await _with_db_retry(_persist_profile)
        emit(
            "info",
            f"使用独立浏览器窗口（{profile}），可与其他猎聘任务并行",
            category="system",
            workflow_id=workflow_id,
        )

    async def _mark_fetching():
        async with async_session_factory() as session:
            repo = WorkflowRepository(session)
            await repo.update_status(workflow_id, "FETCHING")
            await session.commit()

    await _with_db_retry(_mark_fetching)

    emit("info", "开始抓取候选人", category="system", workflow_id=workflow_id)

    from packages.keep_awake import keep_awake_session

    try:
        fetch_input = FetchInput(
            platform=config.platform,
            workflow_id=workflow_id,
            start_url=config.start_url,
            target_count=config.fetch.target_count,
            max_pages=config.fetch.max_pages,
            detail_required=config.fetch.detail_required,
            browser_profile=config.fetch.browser_profile,
            search=config.fetch.search,
            job_id=config.job.job_id,
            job_title=config.job.title,
            job_description=config.job.description,
            screening_criteria=config.job.screening_criteria,
            screening_min_score=config.screening.min_score,
            collect_only=config.fetch.collect_only,
            collect_parent_group=config.fetch.collect_parent_group,
        )
        with keep_awake_session(f"fetch {workflow_id}"):
            result = await run_on_playwright_loop(run_fetch_task(fetch_input))

        async def _mark_done():
            async with async_session_factory() as session:
                repo = WorkflowRepository(session)
                status = "FETCH_COMPLETED" if result.captured_count > 0 else "PARTIAL_FAILED"
                await repo.update_status(
                    workflow_id,
                    status,
                    fetch_task_id=result.fetch_task_id,
                )
                await session.commit()

        await _with_db_retry(_mark_done)
        logger.info("Fetch completed for %s: %d candidates", workflow_id, result.captured_count)
        emit(
            "success",
            f"抓取完成，共 {result.captured_count} 人",
            category="system",
            workflow_id=workflow_id,
            meta={"captured_count": result.captured_count},
        )

        if result.captured_count > 0 and config.fetch.search.auto_screen:
            logger.info("Finalizing shortlist after per-card screening for %s", workflow_id)
            await run_screening_job(workflow_id, config, inline_already_done=True)

    except WorkflowCancelledError:
        logger.info("Fetch cancelled by user for %s", workflow_id)
        emit("warn", "用户已退出任务，抓取已停止", category="system", workflow_id=workflow_id)

        async def _mark_cancelled():
            async with async_session_factory() as session:
                repo = WorkflowRepository(session)
                await repo.update_status(
                    workflow_id, "PARTIAL_FAILED", error_message="用户已退出任务"
                )
                await session.commit()

        try:
            await _with_db_retry(_mark_cancelled)
        except Exception:
            logger.exception("Failed to mark workflow as cancelled")
    except asyncio.CancelledError:
        logger.info("Fetch cancelled for %s (server shutdown)", workflow_id)
        emit("warn", "抓取已取消（服务正在关闭）", category="system", workflow_id=workflow_id)

        async def _mark_cancelled():
            async with async_session_factory() as session:
                repo = WorkflowRepository(session)
                await repo.update_status(
                    workflow_id, "PARTIAL_FAILED", error_message="服务关闭，抓取已取消"
                )
                await session.commit()

        try:
            await _with_db_retry(_mark_cancelled)
        except Exception:
            logger.exception("Failed to mark workflow as cancelled")
        raise
    except Exception as e:
        error_message = str(e)
        logger.exception("Fetch failed for %s", workflow_id)
        emit("error", f"抓取失败: {e}", category="system", workflow_id=workflow_id)

        async def _mark_failed():
            async with async_session_factory() as session:
                repo = WorkflowRepository(session)
                await repo.update_status(workflow_id, "FAILED", error_message=error_message)
                await session.commit()

        try:
            await _with_db_retry(_mark_failed)
        except Exception:
            logger.exception("Failed to mark workflow as FAILED")
    finally:
        clear_workflow_control(workflow_id)


async def run_screening_job(
    workflow_id: str, config: RecruitingWorkflowConfig, *, inline_already_done: bool = False
) -> None:
    from packages.workflow_control import WorkflowCancelledError, clear_workflow_control, wait_if_paused
    from services.agent_service.screening_service import finalize_shortlist, run_screening_batch

    async def _mark_screening():
        async with async_session_factory() as session:
            repo = WorkflowRepository(session)
            await repo.update_status(workflow_id, "SCREENING")
            await session.commit()

    await _with_db_retry(_mark_screening)

    from packages.workflow_events import emit

    emit("info", "正在生成 Shortlist / 追问列表", category="system", workflow_id=workflow_id)

    try:
        await wait_if_paused(workflow_id)
        if inline_already_done:
            result = await finalize_shortlist(workflow_id, config)
        else:
            result = await run_screening_batch(workflow_id, config)

        async def _mark_done():
            async with async_session_factory() as session:
                repo = WorkflowRepository(session)
                await repo.update_status(
                    workflow_id,
                    "SCREENING_COMPLETED",
                    shortlist_id=result.shortlist_id,
                )
                await session.commit()

        await _with_db_retry(_mark_done)
        logger.info("Screening completed for %s: %d shortlisted", workflow_id, len(result.shortlist))
        emit(
            "success",
            f"初筛完成，清单 {len(result.shortlist)} 人",
            category="system",
            workflow_id=workflow_id,
            meta={"shortlist_count": len(result.shortlist)},
        )

        if not config.fetch.collect_only:
            from packages.background_tasks import spawn
            from services.agent_service.im_autopilot import run_post_screening_im_autopilot

            spawn(
                run_on_playwright_loop(run_post_screening_im_autopilot(workflow_id)),
                workflow_id=workflow_id,
            )
        else:
            emit(
                "info",
                "仅收藏模式：跳过 IM 自动跟进",
                category="system",
                workflow_id=workflow_id,
            )
    except WorkflowCancelledError:
        logger.info("Screening cancelled by user for %s", workflow_id)
        emit("warn", "用户已退出任务，初筛已停止", category="system", workflow_id=workflow_id)

        async def _mark_cancelled():
            async with async_session_factory() as session:
                repo = WorkflowRepository(session)
                await repo.update_status(
                    workflow_id, "PARTIAL_FAILED", error_message="用户已退出任务"
                )
                await session.commit()

        try:
            await _with_db_retry(_mark_cancelled)
        except Exception:
            logger.exception("Failed to mark workflow as cancelled")
    except Exception as e:
        error_message = str(e)
        logger.exception("Screening failed for %s", workflow_id)
        emit("error", f"初筛失败: {e}", category="system", workflow_id=workflow_id)

        async def _mark_failed():
            async with async_session_factory() as session:
                repo = WorkflowRepository(session)
                await repo.update_status(workflow_id, "FAILED", error_message=error_message)
                await session.commit()

        try:
            await _with_db_retry(_mark_failed)
        except Exception:
            logger.exception("Failed to mark screening as FAILED")
    finally:
        clear_workflow_control(workflow_id)
