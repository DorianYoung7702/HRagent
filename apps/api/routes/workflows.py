import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_db
from apps.api.job_runner import run_fetch_job, run_screening_job
from packages.background_tasks import spawn
from packages.workflow_runtime import register_workflow_session, unregister_workflow_session
from apps.api.temporal_client import start_recruiting_workflow
from packages.candidate_identity import dedupe_candidate_records, snapshot_identity_key
from packages.db.repositories import (
    CandidateRepository,
    ScreeningRepository,
    WorkflowRepository,
)
from packages.screening_defaults import resolve_screening_criteria as _resolve_screening_criteria
from packages.schemas.workflow import (
    ConsoleStartRequest,
    HRReport,
    HRReportCandidate,
    HRPreferenceChatRequest,
    HRPreferenceMemory,
    HRPreferenceMemoryRequest,
    HRPreferenceUpdateRequest,
    LiepinLptDemoRequest,
    LiepinSearchConfig,
    RecruitingWorkflowConfig,
    RecruitingWorkflowCreate,
    RecruitingWorkflowResponse,
    RecruitingWorkflowStatus,
    SearchIntentRequest,
    SearchIntentOutput,
    FetchConfig,
    JobConfig,
    JobQaProfile,
    JobQaProfileUpdateRequest,
    ScreeningConfig,
    OutreachConfig,
    PdfImportStartRequest,
    WorkflowRuntimeOptionsUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])

PLATFORM_LABELS = {
    "liepin": "猎聘",
    "boss": "BOSS",
    "local_pdf": "本地 PDF",
}

PLATFORM_START_URLS = {
    "liepin": "https://lpt.liepin.com/search",
    "boss": "https://www.zhipin.com/web/geek/job",
}


async def _assign_isolated_liepin_browser(
    repo: WorkflowRepository,
    workflow_id: str,
    demo_create: RecruitingWorkflowCreate,
) -> RecruitingWorkflowCreate:
    """Give each Liepin workflow its own Chromium profile (cloned from hr_default)."""
    from services.fetch_worker.workflow_browser_profile import ensure_workflow_browser_profile

    profile = ensure_workflow_browser_profile(workflow_id)
    demo_create.fetch.browser_profile = profile
    await repo.patch_fetch(workflow_id, browser_profile=profile)
    return demo_create


def _dedupe_candidate_items(items: list[dict]) -> list[dict]:
    return dedupe_candidate_records(
        items,
        score_getter=lambda item: (item.get("screening") or {}).get("total_score"),
        captured_getter=lambda item: item.get("captured_at"),
    )


@router.post("/parse-search-intent", response_model=SearchIntentOutput)
async def parse_search_intent_endpoint(body: SearchIntentRequest):
    """Parse natural language into LPT search keywords and filters."""
    from packages.runtime_guards import require_task_start
    from services.agent_service.search_intent_agent import parse_search_intent

    require_task_start()

    result = await parse_search_intent(
        body.search_requirement,
        body.screening_criteria,
        unified_requirement=body.unified_requirement,
        position_name=body.position_name,
    )
    logger.info(
        "Search intent parsed: keywords=%s city=%s criteria_len=%d",
        result.keywords,
        result.city,
        len(result.screening_criteria or ""),
    )
    return result


@router.post("/parse-search-intent/stream")
async def parse_search_intent_stream_endpoint(body: SearchIntentRequest):
    """Stream parse progress (SSE) then return structured result."""
    from packages.runtime_guards import require_task_start
    from services.agent_service.search_intent_agent import parse_search_intent_stream

    require_task_start()

    async def event_generator():
        try:
            async for item in parse_search_intent_stream(
                body.search_requirement,
                body.screening_criteria,
                unified_requirement=body.unified_requirement,
                position_name=body.position_name,
            ):
                event = item["event"]
                payload = json.dumps(item["data"], ensure_ascii=False)
                yield f"event: {event}\ndata: {payload}\n\n"
        except Exception as exc:
            logger.exception("parse-search-intent stream failed")
            err = json.dumps({"message": str(exc)}, ensure_ascii=False)
            yield f"event: error\ndata: {err}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/preference-memory/init", response_model=HRPreferenceMemory)
async def init_preference_memory_endpoint(body: HRPreferenceMemoryRequest):
    from services.agent_service.hr_preference_agent import initialize_preference_memory

    return await initialize_preference_memory(body)


@router.post("/preference-memory/chat", response_model=HRPreferenceMemory)
async def chat_preference_memory_endpoint(body: HRPreferenceChatRequest):
    from services.agent_service.hr_preference_agent import update_preference_memory

    return await update_preference_memory(body)


@router.post("/pdf-import", status_code=202)
async def start_pdf_import(
    config: str = Form(...),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Start a one-time in-memory PDF batch. No file identifier enters workflow state."""
    from packages.runtime_guards import require_task_start
    from packages.workflow_events import emit
    from services.agent_service.pdf_import_service import (
        MAX_PDF_FILE_BYTES,
        MAX_PDF_IMPORT_FILES,
        MAX_PDF_IMPORT_TOTAL_BYTES,
        PDF_IMPORT_READ_CHUNK_BYTES,
        cleanup_pdf_import_staging_dir,
        create_pdf_import_staging_dir,
        initial_pdf_import_progress,
        run_pdf_import_job,
    )

    require_task_start()
    try:
        body = PdfImportStartRequest.model_validate_json(config)
    except ValueError as exc:
        raise HTTPException(422, "PDF 导入配置无效") from exc

    if not files or len(files) > MAX_PDF_IMPORT_FILES:
        raise HTTPException(400, f"每批最多导入 {MAX_PDF_IMPORT_FILES} 份 PDF")

    staging_dir = create_pdf_import_staging_dir()
    file_paths: list[Path] = []
    total_bytes = 0
    try:
        for index, upload in enumerate(files, start=1):
            header = await upload.read(5)
            if not header.startswith(b"%PDF-"):
                raise HTTPException(400, "仅支持有文本层的 PDF 文件")
            path = staging_dir / f"{index:04d}.pdf"
            file_bytes = len(header)
            total_bytes += file_bytes
            with path.open("wb") as stream:
                stream.write(header)
                while chunk := await upload.read(PDF_IMPORT_READ_CHUNK_BYTES):
                    file_bytes += len(chunk)
                    total_bytes += len(chunk)
                    if file_bytes > MAX_PDF_FILE_BYTES:
                        raise HTTPException(400, "单份 PDF 不能超过 30MB")
                    if total_bytes > MAX_PDF_IMPORT_TOTAL_BYTES:
                        raise HTTPException(400, "单批 PDF 总大小不能超过 5GB")
                    stream.write(chunk)
            file_paths.append(path)
    except Exception:
        cleanup_pdf_import_staging_dir(staging_dir)
        raise
    finally:
        for upload in files:
            await upload.close()

    criteria = body.screening_criteria.strip()
    memory = body.hr_preference_memory.model_dump() if body.hr_preference_memory else None
    if memory and str(memory.get("screening_criteria") or "").strip():
        criteria = str(memory["screening_criteria"]).strip()
    criteria_version = int((memory or {}).get("criteria_version") or 1)
    workflow_config = {
        "name": body.name,
        "platform": "local_pdf",
        "start_url": "local://pdf-import",
        "fetch": {
            "target_count": len(file_paths),
            "max_pages": 0,
            "detail_required": False,
            "browser_profile": "local_pdf",
            "search": {},
        },
        "job": {
            "job_id": body.job_id,
            "description": body.job_description,
            "title": body.preset_label or body.name,
            "requirements": [],
            "screening_criteria": criteria,
        },
        "screening": {"top_k": body.top_k, "min_score": body.min_score},
        "outreach": {"enabled": False, "send_mode": "draft_first", "max_rounds": 0},
        "pdf_import": initial_pdf_import_progress(len(file_paths)),
        "criteria_version": max(1, criteria_version),
        "initial_screening_criteria": criteria,
        "initial_criteria_version": max(1, criteria_version),
    }
    if body.preset_id or body.preset_label:
        workflow_config["requirement_preset"] = {
            "id": body.preset_id,
            "label": body.preset_label,
            "screening_criteria": criteria,
        }
    if memory:
        workflow_config["hr_preference_memory"] = memory

    repo = WorkflowRepository(db)
    try:
        workflow = await repo.create(
            name=body.preset_label or body.name,
            platform="local_pdf",
            start_url="local://pdf-import",
            job_id=body.job_id,
            config=workflow_config,
        )
        await repo.update_status(workflow.id, "SCREENING")
        await db.commit()
    except Exception:
        cleanup_pdf_import_staging_dir(staging_dir)
        raise

    register_workflow_session(workflow.id)
    emit(
        "info",
        f"一次性 PDF 导入任务已创建：共 {len(file_paths)} 份",
        category="pdf_import",
        workflow_id=workflow.id,
    )
    spawn(run_pdf_import_job(workflow.id, body, file_paths), workflow_id=workflow.id)
    return {
        "workflow_id": workflow.id,
        "status": "SCREENING",
        "console_url": f"/?workflow_id={workflow.id}",
        "message": "PDF 已进入一次性解析筛选队列",
    }


@router.post("/demo/liepin-lpt/start")
async def start_liepin_lpt_demo_async(
    body: ConsoleStartRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create one workflow per selected platform and start fetch/screen in background."""
    import os

    from packages.runtime_guards import require_task_start
    from packages.workflow_events import emit

    require_task_start()

    if os.environ.get("HRAGENT_FORCE_HEADLESS") != "1":
        os.environ["BROWSER_HEADLESS"] = "false"

    platforms = _normalize_start_platforms(body.platforms)
    platform_group_id = uuid.uuid4().hex
    repo = WorkflowRepository(db)
    pending_starts: list[tuple[str, object, RecruitingWorkflowConfig]] = []
    platform_results: list[dict] = []

    for platform in platforms:
        demo_create = _workflow_create_from_console_body(
            body,
            platform=platform,
            multi_platform=len(platforms) > 1,
        )
        config_payload = _console_config_payload(
            body,
            demo_create,
            platforms=platforms,
            platform_group_id=platform_group_id,
        )
        wf = await repo.create(
            name=demo_create.name,
            platform=demo_create.platform,
            start_url=demo_create.start_url,
            job_id=demo_create.job.job_id,
            config=config_payload,
        )
        if platform == "liepin":
            demo_create = await _assign_isolated_liepin_browser(repo, wf.id, demo_create)
            config_payload = dict(wf.config or config_payload)
            fetch_cfg = dict(config_payload.get("fetch") or {})
            fetch_cfg["browser_profile"] = demo_create.fetch.browser_profile
            config_payload["fetch"] = fetch_cfg
        config = RecruitingWorkflowConfig(
            workflow_id=wf.id,
            name=demo_create.name,
            platform=demo_create.platform,
            start_url=demo_create.start_url,
            fetch=demo_create.fetch,
            job=demo_create.job,
            screening=demo_create.screening,
            outreach=demo_create.outreach,
        )
        pending_starts.append((platform, wf, config))
        platform_results.append(
            {
                "platform": platform,
                "platform_label": PLATFORM_LABELS[platform],
                "workflow_id": wf.id,
                "status": "FETCHING",
                "console_url": f"/?workflow_id={wf.id}",
                "message": f"{PLATFORM_LABELS[platform]}筛选任务已启动",
            }
        )

    await db.commit()

    for platform, wf, config in pending_starts:
        _emit_console_task_created(emit, body, wf.id, platform)
        register_workflow_session(wf.id)
        spawn(run_fetch_job(wf.id, config), workflow_id=wf.id)

    primary = platform_results[0]
    return {
        "workflow_id": primary["workflow_id"],
        "status": "FETCHING",
        "console_url": primary["console_url"],
        "message": (
            "多平台筛选任务已并行启动，请在控制台查看实时日志。"
            if len(platform_results) > 1
            else "筛选任务已启动，请在控制台查看实时日志。"
        ),
        "platform_results": platform_results,
    }


def _normalize_start_platforms(platforms: list[str] | None) -> list[str]:
    aliases = {
        "liepin": "liepin",
        "lpt": "liepin",
        "猎聘": "liepin",
        "猎聘lpt": "liepin",
        "boss": "boss",
        "boss直聘": "boss",
        "boss_zhipin": "boss",
        "zhipin": "boss",
    }
    normalized: list[str] = []
    for raw in platforms or ["liepin"]:
        key = str(raw or "").strip().lower().replace(" ", "")
        platform = aliases.get(key)
        if not platform:
            raise HTTPException(400, f"不支持的平台: {raw}")
        if platform not in normalized:
            normalized.append(platform)
    if not normalized:
        return ["liepin"]
    return normalized


def _console_demo_request_from_body(body: ConsoleStartRequest) -> LiepinLptDemoRequest:
    return LiepinLptDemoRequest(
        name=body.name,
        keywords=body.keywords,
        city=body.city,
        cities=list(body.cities or []),
        current_cities=list(body.current_cities or []),
        experience=body.experience,
        education=body.education,
        other_filters=body.other_filters,
        target_count=body.target_count,
        job_id=body.job_id,
        job_description=body.job_description or body.search_requirement,
        screening_criteria=body.screening_criteria,
        chat_job_title=body.chat_job_title,
        min_score=body.min_score,
        top_k=body.top_k,
        collect_only=body.collect_only,
        im_review_required=body.im_review_required,
        collect_parent_group=body.collect_parent_group,
        job_qa_profile=body.job_qa_profile,
    )


def _workflow_create_from_console_body(
    body: ConsoleStartRequest,
    *,
    platform: str,
    multi_platform: bool,
) -> RecruitingWorkflowCreate:
    demo_create = _demo_create_from_body(_console_demo_request_from_body(body))
    base_name = _resolve_position_name(body) or body.name
    demo_create.name = base_name
    if multi_platform:
        demo_create.name = f"{base_name} - {PLATFORM_LABELS[platform]}"

    if platform == "liepin":
        return demo_create

    if platform == "boss":
        demo_create.platform = "boss"
        demo_create.start_url = PLATFORM_START_URLS["boss"]
        demo_create.fetch.search.mode = "boss_search"
        demo_create.fetch.search.entry_url = PLATFORM_START_URLS["boss"]
        return demo_create

    raise HTTPException(400, f"不支持的平台: {platform}")


def _console_config_payload(
    body: ConsoleStartRequest,
    demo_create: RecruitingWorkflowCreate,
    *,
    platforms: list[str],
    platform_group_id: str,
) -> dict:
    position_name = _resolve_position_name(body)
    config_payload = demo_create.model_dump()
    config_payload["search_intent"] = {
        "search_requirement": body.search_requirement,
        "screening_criteria": body.screening_criteria,
        "keywords": body.keywords,
        "city": body.city,
        "cities": body.cities,
        "current_cities": body.current_cities,
        "experience": body.experience,
        "education": body.education.model_dump(),
        "other_filters": body.other_filters.model_dump(),
        "target_count": body.target_count,
        "job_description": body.job_description or body.search_requirement,
        "chat_job_title": position_name,
        "name": body.name,
        "parse_summary": body.parse_summary,
        "collect_parent_group": body.collect_parent_group or "",
    }
    if body.collect_parent_group:
        folder = body.collect_parent_group.strip()
        config_payload["collect_group"] = {
            "parent_name": folder,
            "observe_label": "observe",
            "followup_label": "followup",
        }
    config_payload["platform_group"] = {
        "id": platform_group_id,
        "platforms": platforms,
        "primary_platform": platforms[0],
    }
    if body.preset_id or body.preset_label:
        config_payload["requirement_preset"] = {
            "id": body.preset_id,
            "label": body.preset_label,
            "search_requirement": body.search_requirement,
            "screening_criteria": body.screening_criteria,
        }
    if body.job_qa_profile:
        config_payload["job_qa_profile"] = body.job_qa_profile.model_dump()
    if body.hr_preference_memory:
        memory = body.hr_preference_memory.model_dump()
        criteria_version = max(1, int(memory.get("criteria_version") or 1))
        memory_criteria = str(memory.get("screening_criteria") or "").strip()
        if memory_criteria:
            config_payload["job"]["screening_criteria"] = memory_criteria
            config_payload["search_intent"]["screening_criteria"] = memory_criteria
            if "requirement_preset" in config_payload:
                config_payload["requirement_preset"]["screening_criteria"] = memory_criteria
        config_payload["hr_preference_memory"] = memory
        config_payload["criteria_version"] = criteria_version
    else:
        config_payload["criteria_version"] = 1
    config_payload["initial_screening_criteria"] = str(
        (config_payload.get("job") or {}).get("screening_criteria") or ""
    ).strip()
    config_payload["initial_criteria_version"] = int(config_payload["criteria_version"] or 1)
    return config_payload


def _emit_console_task_created(emit_func, body: ConsoleStartRequest, workflow_id: str, platform: str) -> None:
    city_label = "、".join(body.cities) if body.cities else body.city
    current_label = "、".join(body.current_cities) if body.current_cities else ""
    edu = body.education
    filter_bits = [city_label, body.experience]
    if current_label:
        filter_bits.insert(0, f"目前城市 {current_label}")
    if edu.degree:
        filter_bits.append(f"学历 {edu.degree}")
    if edu.school_tiers:
        filter_bits.append("院校 " + "、".join(edu.school_tiers))
    emit_func(
        "info",
        f"{PLATFORM_LABELS[platform]}任务已创建: {body.keywords} | {' | '.join(filter_bits)}",
        category="system",
        workflow_id=workflow_id,
        meta={
            "platform": platform,
            "keywords": body.keywords,
            "city": city_label,
            "cities": body.cities or [body.city],
            "current_cities": body.current_cities,
            "experience": body.experience,
            "education": body.education.model_dump(),
            "other_filters": body.other_filters.model_dump(),
        },
    )


@router.post("/demo/liepin-lpt", response_model=RecruitingWorkflowResponse)
async def create_liepin_lpt_demo(
    body: LiepinLptDemoRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    start_background: bool = False,
):
    """一键 Demo：LPT 搜索抓取 3 条 + 自动 DeepSeek 初筛。

    start_background=false（默认）时仅创建 workflow 记录，由客户端前台运行 fetch（可见浏览器）。
    """
    demo_create = _demo_create_from_body(body)
    return await create_recruiting_workflow(
        demo_create, background_tasks, db, use_temporal=False, skip_background=not start_background
    )


def _resolve_position_name(body: LiepinLptDemoRequest | ConsoleStartRequest) -> str:
    """主页岗位名：仅用于开聊选岗与任务展示，不做 screening 文本反推。"""
    for value in (
        getattr(body, "chat_job_title", None),
        getattr(body, "preset_label", None),
    ):
        text = (value or "").strip()
        if text:
            return text[:48]
    return (body.name or "深圳 ToB 大客户销售")[:48]


def _demo_create_from_body(body: LiepinLptDemoRequest) -> RecruitingWorkflowCreate:
    position_name = _resolve_position_name(body)
    return RecruitingWorkflowCreate(
        name=position_name or body.name,
        platform="liepin",
        start_url="https://lpt.liepin.com/search",
        fetch=FetchConfig(
            target_count=body.target_count,
            max_pages=1,
            detail_required=True,
            browser_profile="hr_default",
            collect_only=body.collect_only,
            collect_parent_group=body.collect_parent_group or "",
            search=LiepinSearchConfig(
                mode="lpt_search",
                keywords=body.keywords,
                city=body.city,
                cities=list(body.cities or []),
                current_cities=list(body.current_cities or []),
                experience=body.experience,
                education=body.education,
                other_filters=body.other_filters,
                auto_screen=True,
            ),
        ),
        job=JobConfig(
            job_id=body.job_id,
            title=_resolve_position_name(body),
            description=body.job_description,
            screening_criteria=_resolve_screening_criteria(body.screening_criteria),
        ),
        screening=ScreeningConfig(top_k=body.top_k, min_score=body.min_score),
        outreach=OutreachConfig(enabled=False, im_review_required=body.im_review_required),
        job_qa_profile=body.job_qa_profile,
    )


@router.post("/demo/liepin-lpt/run-visible")
async def run_liepin_lpt_demo_visible(
    body: LiepinLptDemoRequest,
    db: AsyncSession = Depends(get_db),
):
    """Demo: create workflow + run fetch/screen in API process with visible browser.

    Blocks until complete. Avoids SQLite lock from a second Python process.
    """
    import os

    if os.environ.get("HRAGENT_FORCE_HEADLESS") != "1":
        os.environ["BROWSER_HEADLESS"] = "false"

    demo_create = _demo_create_from_body(body)
    repo = WorkflowRepository(db)
    wf = await repo.create(
        name=demo_create.name,
        platform=demo_create.platform,
        start_url=demo_create.start_url,
        job_id=demo_create.job.job_id,
        config=demo_create.model_dump(),
    )
    if demo_create.platform == "liepin":
        demo_create = await _assign_isolated_liepin_browser(repo, wf.id, demo_create)
    config = RecruitingWorkflowConfig(
        workflow_id=wf.id,
        name=demo_create.name,
        platform=demo_create.platform,
        start_url=demo_create.start_url,
        fetch=demo_create.fetch,
        job=demo_create.job,
        screening=demo_create.screening,
        outreach=demo_create.outreach,
    )
    await db.commit()

    logger.info("Starting visible LPT fetch for workflow %s", wf.id)
    await run_fetch_job(wf.id, config)

    from packages.db.session import async_session_factory

    async with async_session_factory() as fresh_db:
        fresh_repo = WorkflowRepository(fresh_db)
        wf = await fresh_repo.get(wf.id)

    status = wf.status if wf else "UNKNOWN"
    error_msg = wf.error_message if wf else None
    ok = status in ("FETCH_COMPLETED", "SCREENING_COMPLETED", "PARTIAL_FAILED")

    return {
        "id": wf.id if wf else config.workflow_id,
        "status": status,
        "error_message": error_msg,
        "success": ok,
        "admin_url": f"/admin/workflows/{config.workflow_id}",
        "message": (
            "Demo 完成，请打开 admin_url 查看结果。"
            if ok
            else f"Demo 失败: {error_msg or status}"
        ),
    }


@router.post("/recruiting", response_model=RecruitingWorkflowResponse)
async def create_recruiting_workflow(
    body: RecruitingWorkflowCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    use_temporal: bool = False,
    skip_background: bool = False,
):
    repo = WorkflowRepository(db)
    wf = await repo.create(
        name=body.name,
        platform=body.platform,
        start_url=body.start_url,
        job_id=body.job.job_id,
        config=body.model_dump(),
    )

    if body.platform == "liepin":
        body = await _assign_isolated_liepin_browser(repo, wf.id, body)

    config = RecruitingWorkflowConfig(
        workflow_id=wf.id,
        name=body.name,
        platform=body.platform,
        start_url=body.start_url,
        fetch=body.fetch,
        job=body.job,
        screening=body.screening,
        outreach=body.outreach,
    )

    if not skip_background:
        if use_temporal:
            try:
                temporal_id = await start_recruiting_workflow(config)
                await repo.update_status(wf.id, "FETCHING", temporal_workflow_id=temporal_id)
            except Exception as e:
                logger.warning("Temporal unavailable, falling back to background task: %s", e)
                await db.commit()
                register_workflow_session(wf.id)
                spawn(run_fetch_job(wf.id, config), workflow_id=wf.id)
        else:
            await db.commit()
            register_workflow_session(wf.id)
            spawn(run_fetch_job(wf.id, config), workflow_id=wf.id)
    else:
        await db.commit()

    await db.refresh(wf)
    return _to_response(wf)


@router.get("", response_model=list[RecruitingWorkflowResponse])
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    repo = WorkflowRepository(db)
    workflows = await repo.list_all(limit=limit)
    return [_to_response(wf) for wf in workflows]


@router.get("/active", response_model=list[RecruitingWorkflowResponse])
async def list_active_workflows(
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    """Return workflows with live fetch/screen/IM work (for concurrent task switching)."""
    from packages.workflow_runtime import is_workflow_active_for_console

    repo = WorkflowRepository(db)
    workflows = await repo.list_active(limit=limit)
    live = [wf for wf in workflows if is_workflow_active_for_console(wf.id, wf.status)]
    return [_to_response(wf) for wf in live]


@router.get("/{workflow_id}/events")
async def list_workflow_events(workflow_id: str, since: int = 0):
    """Poll workflow events (fallback when SSE unavailable)."""
    from packages.workflow_events import get_events

    return {"workflow_id": workflow_id, "events": get_events(workflow_id, since_id=since)}


@router.get("/{workflow_id}/events/stream")
async def stream_workflow_events(workflow_id: str, request: Request):
    """SSE stream of workflow log events."""
    from packages.workflow_events import get_events, subscribe, unsubscribe

    last_event_id = request.headers.get("Last-Event-ID")
    since_id = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def event_generator():
        queue = await subscribe(workflow_id, since_id=since_id)
        try:
            for event in get_events(workflow_id, since_id=since_id):
                if event["id"] > since_id:
                    yield f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_obj = await asyncio.wait_for(queue.get(), timeout=25.0)
                    payload = event_obj.to_sse_data()
                    yield f"id: {event_obj.id}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(workflow_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_RUNNABLE_STATUSES = frozenset({
    "FETCHING",
    "SCREENING",
    "FETCH_COMPLETED",
    "SCREENING_COMPLETED",
    "CONVERSATIONS_STARTED",
    "PARTIAL_FAILED",
})


def _execution_can_pause(wf, workflow_id: str) -> bool:
    if wf.status in _RUNNABLE_STATUSES:
        return True
    from services.agent_service.im_autopilot import is_im_monitor_running
    from services.agent_service.reply_judgment_runner import reply_judgment_status

    if is_im_monitor_running(workflow_id):
        return True
    if reply_judgment_status(workflow_id).get("running"):
        return True
    return False


@router.get("/{workflow_id}/execution-control")
async def get_execution_control(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from packages.workflow_control import get_control_state

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    ctrl = get_control_state(workflow_id)
    return {
        "workflow_id": workflow_id,
        **ctrl,
        "can_pause": _execution_can_pause(wf, workflow_id) or ctrl.get("paused"),
    }


@router.post("/{workflow_id}/execution/pause")
async def pause_execution(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from packages.workflow_control import get_control_state, pause_global
    from packages.workflow_events import emit

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if not _execution_can_pause(wf, workflow_id):
        raise HTTPException(400, f"当前无运行中的 Agent，不可暂停: {wf.status}")

    pause_global(workflow_id)
    emit("warn", "用户已全局暂停", category="control", workflow_id=workflow_id)
    return {"workflow_id": workflow_id, **get_control_state(workflow_id)}


@router.post("/{workflow_id}/execution/resume")
async def resume_execution(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from packages.workflow_control import get_control_state, resume_global
    from packages.workflow_events import emit

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    resume_global()
    emit("info", "用户已继续运行（全局）", category="control", workflow_id=workflow_id)
    return {"workflow_id": workflow_id, **get_control_state(workflow_id)}


@router.post("/{workflow_id}/pause")
async def pause_workflow_execution(workflow_id: str, db: AsyncSession = Depends(get_db)):
    return await pause_execution(workflow_id, db)


@router.post("/{workflow_id}/resume")
async def resume_workflow_execution(workflow_id: str, db: AsyncSession = Depends(get_db)):
    return await resume_execution(workflow_id, db)


@router.post("/{workflow_id}/cancel")
async def cancel_workflow_execution(workflow_id: str, db: AsyncSession = Depends(get_db)):
    """User exits task: stop fetch/screening/agents and mark workflow stopped."""
    from packages.background_tasks import cancel_workflow_tasks
    from packages.workflow_control import get_control_state, is_cancelled, request_cancel, resume_global
    from packages.workflow_events import emit
    from services.agent_service.im_autopilot import stop_im_autopilot
    from services.agent_service.reply_judgment_runner import stop_reply_judgment

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    terminal = frozenset({"COMPLETED", "FAILED", "PARTIAL_FAILED"})
    if wf.status in terminal and not _execution_can_pause(wf, workflow_id):
        return {
            "workflow_id": workflow_id,
            "cancelled": False,
            "already_stopped": True,
            "status": wf.status,
        }

    if not is_cancelled(workflow_id):
        request_cancel(workflow_id)
    stop_im_autopilot(workflow_id)
    stop_reply_judgment(workflow_id)
    tasks_cancelled = cancel_workflow_tasks(workflow_id)
    resume_global()

    if wf.status in ("FETCHING", "SCREENING", "CREATED"):
        await repo.update_status(
            workflow_id,
            "PARTIAL_FAILED",
            error_message="用户已退出任务",
        )
        await db.commit()

    emit("warn", "用户已退出本次任务", category="control", workflow_id=workflow_id)
    unregister_workflow_session(workflow_id)
    return {
        "workflow_id": workflow_id,
        "cancelled": True,
        "tasks_cancelled": tasks_cancelled,
        **get_control_state(workflow_id),
    }


@router.post("/{workflow_id}/execution/cancel")
async def cancel_execution(workflow_id: str, db: AsyncSession = Depends(get_db)):
    return await cancel_workflow_execution(workflow_id, db)


@router.delete("/{workflow_id}")
async def delete_workflow_data(workflow_id: str, db: AsyncSession = Depends(get_db)):
    """Permanently delete workflow and all related rows in recruiting.db."""
    from packages.background_tasks import cancel_workflow_tasks
    from packages.workflow_control import clear_workflow_control, request_cancel
    from packages.workflow_events import clear_workflow
    from services.agent_service.im_autopilot import stop_im_autopilot
    from services.agent_service.reply_judgment_runner import stop_reply_judgment

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    request_cancel(workflow_id)
    stop_im_autopilot(workflow_id)
    stop_reply_judgment(workflow_id)
    tasks_cancelled = cancel_workflow_tasks(workflow_id)

    deleted = await repo.delete_workflow_data(workflow_id)
    if not deleted:
        raise HTTPException(404, "Workflow not found")

    if wf.platform == "liepin":
        from services.fetch_worker.resume_library_viewer import close_resume_library_viewer_for_profile
        from services.fetch_worker.workflow_browser_profile import (
            cleanup_workflow_browser_profile,
            workflow_browser_profile_name,
        )

        fetch_cfg = (wf.config or {}).get("fetch") or {}
        profile = fetch_cfg.get("browser_profile") or workflow_browser_profile_name(workflow_id)
        await close_resume_library_viewer_for_profile(profile)
        cleanup_workflow_browser_profile(workflow_id)

    clear_workflow(workflow_id)
    clear_workflow_control(workflow_id)
    unregister_workflow_session(workflow_id)

    return {
        "workflow_id": workflow_id,
        "deleted": True,
        "tasks_cancelled": tasks_cancelled,
    }


def _preference_memory_from_config(config: dict | None) -> HRPreferenceMemory:
    cfg = dict(config or {})
    raw = cfg.get("hr_preference_memory") or {}
    if isinstance(raw, dict) and raw:
        try:
            return HRPreferenceMemory(**raw)
        except Exception:
            logger.warning("Invalid hr_preference_memory in workflow config", exc_info=True)
    job = dict(cfg.get("job") or {})
    return HRPreferenceMemory(
        screening_criteria=str(job.get("screening_criteria") or ""),
        criteria_version=max(1, int(cfg.get("criteria_version") or 1)),
        ready=bool(str(job.get("screening_criteria") or "").strip()),
    )


def _patch_preference_config(config: dict | None, memory: HRPreferenceMemory) -> dict:
    cfg = dict(config or {})
    criteria = (memory.screening_criteria or "").strip()

    job = dict(cfg.get("job") or {})
    if criteria:
        job["screening_criteria"] = criteria
    cfg["job"] = job

    search_intent = dict(cfg.get("search_intent") or {})
    if criteria:
        search_intent["screening_criteria"] = criteria
    cfg["search_intent"] = search_intent

    requirement_preset = dict(cfg.get("requirement_preset") or {})
    if requirement_preset or criteria:
        if criteria:
            requirement_preset["screening_criteria"] = criteria
        cfg["requirement_preset"] = requirement_preset

    cfg["hr_preference_memory"] = memory.model_dump()
    cfg["criteria_version"] = max(1, int(memory.criteria_version or 1))
    return cfg


async def _preference_update_targets(
    repo: WorkflowRepository,
    wf,
    *,
    apply_to_platform_group: bool,
):
    if not apply_to_platform_group:
        return [wf]

    group_id = ((wf.config or {}).get("platform_group") or {}).get("id")
    if not group_id:
        return [wf]

    rows = await repo.list_all(limit=500)
    targets = [
        row
        for row in rows
        if (((row.config or {}).get("platform_group") or {}).get("id") == group_id)
    ]
    return targets or [wf]


@router.get("/{workflow_id}/preference-memory")
async def get_workflow_preference_memory(workflow_id: str, db: AsyncSession = Depends(get_db)):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return {
        "workflow_id": workflow_id,
        "memory": _preference_memory_from_config(wf.config).model_dump(),
    }


@router.put("/{workflow_id}/preference-memory")
async def update_workflow_preference_memory(
    workflow_id: str,
    body: HRPreferenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    raise HTTPException(409, "筛选标准在任务启动后已锁定；请新建任务并在启动前调整")


@router.post("/{workflow_id}/preference-memory/rescreen-existing")
async def rescreen_existing_with_preference(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    workflow = await WorkflowRepository(db).get(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    raise HTTPException(409, "已完成候选保留启动时的初筛结果；请新建任务重新筛选")


@router.patch("/{workflow_id}/runtime-options")
async def update_workflow_runtime_options(
    workflow_id: str,
    body: WorkflowRuntimeOptionsUpdate,
    db: AsyncSession = Depends(get_db),
):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    if body.collect_only is not None:
        await repo.patch_fetch(workflow_id, collect_only=body.collect_only)

    if body.im_auto_reply is not None:
        cfg = dict(wf.config or {})
        outreach = dict(cfg.get("outreach") or {})
        outreach["im_review_required"] = not body.im_auto_reply
        await repo.patch_config(workflow_id, {"outreach": outreach})

    wf = await repo.get(workflow_id)
    cfg = wf.config if wf else {}
    fetch = (cfg or {}).get("fetch") or {}
    outreach = (cfg or {}).get("outreach") or {}
    await db.commit()
    return {
        "workflow_id": workflow_id,
        "collect_only": bool(fetch.get("collect_only")),
        "im_auto_reply": not bool(outreach.get("im_review_required")),
    }


@router.get("/{workflow_id}/job-qa-profile")
async def get_workflow_job_qa_profile(workflow_id: str, db: AsyncSession = Depends(get_db)):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    raw = (wf.config or {}).get("job_qa_profile") or {}
    return {
        "workflow_id": workflow_id,
        "profile": JobQaProfile(**raw).model_dump() if isinstance(raw, dict) else JobQaProfile().model_dump(),
    }


@router.put("/{workflow_id}/job-qa-profile")
async def update_workflow_job_qa_profile(
    workflow_id: str,
    body: JobQaProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    cfg = dict(wf.config or {})
    cfg["job_qa_profile"] = body.profile.model_dump()
    await repo.patch_config(workflow_id, cfg)
    await db.commit()
    return {"workflow_id": workflow_id, "profile": cfg["job_qa_profile"]}


@router.post("/{workflow_id}/dialogue/sync-and-reply")
async def sync_and_reply_dialogue(workflow_id: str, db: AsyncSession = Depends(get_db)):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    from services.agent_service.candidate_dialogue_service import process_pending_dialogue_replies

    return {"workflow_id": workflow_id, **await process_pending_dialogue_replies(workflow_id)}


@router.get("/{workflow_id}", response_model=RecruitingWorkflowResponse)
async def get_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from packages.workflow_control import get_control_state, is_paused

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    candidate_repo = CandidateRepository(db)
    count = await candidate_repo.count_by_workflow(workflow_id)

    ctrl = get_control_state(workflow_id)
    response = _to_response(wf)
    response.config["candidate_count"] = count
    response.config["paused"] = is_paused(workflow_id)
    response.config["global_paused"] = bool(ctrl.get("global_paused"))
    response.config["can_pause"] = _execution_can_pause(wf, workflow_id) or bool(ctrl.get("paused"))
    return response


@router.get("/{workflow_id}/pdf-import/status")
async def get_pdf_import_status(workflow_id: str, db: AsyncSession = Depends(get_db)):
    workflow = await WorkflowRepository(db).get(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    if workflow.platform != "local_pdf":
        raise HTTPException(400, "不是 PDF 导入任务")
    progress = dict((workflow.config or {}).get("pdf_import") or {})
    return {
        "workflow_id": workflow_id,
        "status": workflow.status,
        "progress": {
            "total": int(progress.get("total") or 0),
            "processing": int(progress.get("processing") or 0),
            "completed": int(progress.get("completed") or 0),
            "duplicate": int(progress.get("duplicate") or 0),
            "failed": int(progress.get("failed") or 0),
            "state": str(progress.get("state") or "queued"),
            "ranking_state": str(progress.get("ranking_state") or "queued"),
            "ranking_error": str(progress.get("ranking_error") or ""),
        },
    }


@router.get("/{workflow_id}/pdf-import/report")
async def get_pdf_import_report(workflow_id: str, db: AsyncSession = Depends(get_db)):
    workflow = await WorkflowRepository(db).get(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    if workflow.platform != "local_pdf":
        raise HTTPException(400, "不是 PDF 导入任务")

    from services.agent_service.reply_summary_agent import normalize_summary_report_payload

    report = (workflow.config or {}).get("pdf_import_summary_report")
    report = normalize_summary_report_payload(report if isinstance(report, dict) else None)
    return {
        "workflow_id": workflow_id,
        "ready": isinstance(report, dict),
        "report": report,
    }


@router.post("/{workflow_id}/pdf-import/report/regenerate", status_code=202)
async def regenerate_pdf_import_report(workflow_id: str, db: AsyncSession = Depends(get_db)):
    workflow = await WorkflowRepository(db).get(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    if workflow.platform != "local_pdf":
        raise HTTPException(400, "不是 PDF 导入任务")
    progress = dict((workflow.config or {}).get("pdf_import") or {})
    if str(progress.get("ranking_state") or "") == "ranking":
        return {"workflow_id": workflow_id, "status": "PDF_RANKING_RUNNING", "message": "综合排名正在生成"}

    from packages.workflow_events import emit
    from services.agent_service.pdf_import_service import run_pdf_import_ranking

    emit("info", "用户请求重新生成 PDF 综合排名", category="pdf_import", workflow_id=workflow_id, meta={"phase": "ranking"})
    spawn(run_pdf_import_ranking(workflow_id, progress), workflow_id=workflow_id)
    return {"workflow_id": workflow_id, "status": "PDF_RANKING_STARTED", "message": "综合排名已在后台重新生成"}


@router.get("/{workflow_id}/candidates")
async def list_workflow_candidates(workflow_id: str, db: AsyncSession = Depends(get_db)):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    from services.fetch_worker.im_contact_match import candidate_display_name

    candidate_repo = CandidateRepository(db)
    screening_repo = ScreeningRepository(db)
    snapshots = await candidate_repo.list_by_workflow(workflow_id)

    items = []
    for s in snapshots:
        screening = await screening_repo.get_latest_for_candidate(workflow_id, s.id)
        items.append({
            "id": s.id,
            "platform": s.platform,
            "display_name": candidate_display_name(s),
            "identity_key": snapshot_identity_key(s, display_name=candidate_display_name(s)),
            "current_title": s.current_title,
            "current_company": s.current_company,
            "work_years": float(s.work_years) if s.work_years else None,
            "education": s.education,
            "city": s.city,
            "skills": s.skills or [],
            "extraction_confidence": float(s.extraction_confidence) if s.extraction_confidence else None,
            "captured_at": s.captured_at.isoformat(),
            "screening": {
                "total_score": float(screening.total_score) if screening and screening.total_score else None,
                "level": screening.level if screening else None,
                "matched_points": screening.matched_points if screening else [],
                "gaps": screening.gaps if screening else [],
                "missing_info": screening.missing_info if screening else [],
                "score_detail": screening.score_detail if screening else {},
                "resume_summary": (screening.score_detail or {}).get("resume_summary") if screening else None,
                "reason": (screening.score_detail or {}).get("reason") if screening else None,
                "criteria_analysis": (screening.score_detail or {}).get("criteria_analysis") if screening else None,
                "summary_for_list": (screening.score_detail or {}).get("summary_for_list") if screening else None,
            } if screening else None,
            "metadata": s.metadata_ or {},
        })
    return _dedupe_candidate_items(items)


@router.post("/{workflow_id}/candidates/{snapshot_id}/resume-library")
async def open_candidate_in_resume_library(
    workflow_id: str,
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
):
    """在猎聘简历库中定位候选人并打开在线简历（复用同一浏览器标签页）。"""
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    from services.fetch_worker.resume_library_viewer import open_candidate_resume_library_via_loop

    try:
        result = await open_candidate_resume_library_via_loop(workflow_id, snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        logger.exception("resume-library open failed")
        raise HTTPException(status_code=500, detail=f"打开简历库失败: {e}") from e

    return {
        "workflow_id": workflow_id,
        "snapshot_id": snapshot_id,
        **result,
        "message": f"已打开 {result.get('matched_name', '候选人')} 的在线简历，任务完成",
    }


@router.post("/{workflow_id}/screen")
async def trigger_screening(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    if wf.status not in ("FETCH_COMPLETED", "SCREENING_COMPLETED", "PARTIAL_FAILED"):
        raise HTTPException(400, f"Cannot screen in status: {wf.status}")

    config = _build_workflow_config(wf)
    spawn(run_screening_job(workflow_id, config), workflow_id=workflow_id)
    return {"status": "SCREENING", "workflow_id": workflow_id}


@router.get("/{workflow_id}/shortlist")
async def get_shortlist(workflow_id: str, db: AsyncSession = Depends(get_db)):
    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if not wf.shortlist_id:
        raise HTTPException(404, "Shortlist not yet generated")

    screening_repo = ScreeningRepository(db)
    shortlist, candidates = await screening_repo.get_shortlist(wf.shortlist_id)
    from services.fetch_worker.im_contact_match import candidate_display_name

    candidate_repo = CandidateRepository(db)

    items = []
    for c in candidates:
        snap = await candidate_repo.get(c.candidate_snapshot_id)
        screening = await screening_repo.get_latest_for_candidate(workflow_id, c.candidate_snapshot_id)
        items.append({
            "rank": c.rank,
            "score": float(c.score) if c.score else None,
            "level": c.level,
            "candidate_snapshot_id": c.candidate_snapshot_id,
            "display_name": candidate_display_name(snap) if snap else None,
            "matched_points": screening.matched_points if screening else [],
            "missing_info": screening.missing_info if screening else [],
        })

    return {
        "shortlist_id": wf.shortlist_id,
        "selected_count": shortlist.selected_count if shortlist else 0,
        "candidates": items,
    }


@router.get("/{workflow_id}/report", response_model=HRReport)
async def get_hr_report(workflow_id: str, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone

    repo = WorkflowRepository(db)
    wf = await repo.get(workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    from services.fetch_worker.im_contact_match import candidate_display_name

    screening_repo = ScreeningRepository(db)
    candidate_repo = CandidateRepository(db)
    results = await screening_repo.list_by_workflow(workflow_id)

    recommended = []
    backup = []
    rejected_count = 0

    for r in results:
        snap = await candidate_repo.get(r.candidate_snapshot_id)
        entry = HRReportCandidate(
            candidate_snapshot_id=r.candidate_snapshot_id,
            display_name=candidate_display_name(snap) if snap else None,
            total_score=float(r.total_score) if r.total_score else 0,
            level=r.level or "unknown",
            decision=r.suggested_action or "unknown",
            matched_points=r.matched_points or [],
            reasons=r.gaps or [],
        )
        if r.level == "recommend":
            recommended.append(entry)
        elif r.level == "backup":
            backup.append(entry)
        else:
            rejected_count += 1

    return HRReport(
        workflow_id=workflow_id,
        job_id=wf.job_id or "",
        generated_at=datetime.now(timezone.utc),
        total_candidates=len(results),
        recommended=recommended,
        backup=backup,
        rejected_count=rejected_count,
        summary=f"共筛选 {len(results)} 人，推荐 {len(recommended)} 人，备选 {len(backup)} 人，淘汰 {rejected_count} 人。",
    )


def _build_workflow_config(wf) -> RecruitingWorkflowConfig:
    cfg = wf.config
    fetch_raw = cfg.get("fetch", {})
    search_raw = fetch_raw.get("search", {})
    return RecruitingWorkflowConfig(
        workflow_id=wf.id,
        name=cfg.get("name", wf.name),
        platform=cfg.get("platform", wf.platform),
        start_url=cfg.get("start_url", wf.start_url),
        fetch=FetchConfig(
            target_count=fetch_raw.get("target_count", 50),
            max_pages=fetch_raw.get("max_pages", 5),
            detail_required=fetch_raw.get("detail_required", True),
            browser_profile=fetch_raw.get("browser_profile", "hr_default"),
            search=LiepinSearchConfig(**search_raw) if search_raw else LiepinSearchConfig(),
        ),
        job=JobConfig(**cfg["job"]),
        screening=ScreeningConfig(**cfg.get("screening", {})),
        outreach=OutreachConfig(**cfg.get("outreach", {})),
    )


def _to_response(wf) -> RecruitingWorkflowResponse:
    from packages.schemas.workflow import WorkflowLogSummary
    from packages.workflow_events import get_workflow_log_summary

    raw_summary = get_workflow_log_summary(wf.id)
    log_summary = WorkflowLogSummary.model_validate(raw_summary)
    return RecruitingWorkflowResponse(
        id=wf.id,
        name=wf.name,
        platform=wf.platform,
        start_url=wf.start_url,
        status=RecruitingWorkflowStatus(wf.status),
        config=wf.config,
        fetch_task_id=wf.fetch_task_id,
        shortlist_id=wf.shortlist_id,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        log_summary=log_summary,
    )
