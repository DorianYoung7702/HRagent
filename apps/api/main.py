import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from apps.api.routes import (
    browser_setup,
    candidates,
    conversations,
    followup,
    messages,
    runtime_settings,
    system,
    workflows,
)
from services.agent_service.agent_errors import AgentInferenceError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HTML_CACHE_CONTROL = "no-store, no-cache, must-revalidate, max-age=0"
HASHED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


class ConsoleStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        normalized_path = path.replace("\\", "/")
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = HTML_CACHE_CONTROL
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif normalized_path.startswith("assets/"):
            response.headers["Cache-Control"] = HASHED_ASSET_CACHE_CONTROL
        return response

templates_dir = Path(__file__).parent.parent / "admin-web" / "templates"
templates = Jinja2Templates(directory=str(templates_dir)) if templates_dir.exists() else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    from packages.runtime_config import apply_runtime_config_to_env
    from packages.settings import reload_settings

    apply_runtime_config_to_env()
    settings = reload_settings()
    if settings.database_url.startswith("sqlite"):
        from packages.db.session import init_db

        await init_db()
    from packages.db.schema_upgrade import ensure_schema_upgrades

    await ensure_schema_upgrades()
    from services.agent_service.pdf_import_service import cleanup_stale_pdf_import_staging

    stale_pdf_staging = cleanup_stale_pdf_import_staging()
    if stale_pdf_staging:
        logger.info("Removed %d stale PDF import staging directorie(s)", stale_pdf_staging)
    from services.agent_service.talent_archive_service import backfill_talent_archive

    archived_count = await backfill_talent_archive()
    if archived_count:
        logger.info("Refreshed %d talent archive profile(s) after startup", archived_count)
    from packages.workflow_runtime import reconcile_stale_workflows_on_startup

    stale_count = await reconcile_stale_workflows_on_startup()
    if stale_count:
        logger.info("Marked %d stale workflow(s) as stopped after startup", stale_count)
    logger.info(
        "Starting recruiting-agent-system API (DEEPSEEK_MODEL=%s, env_file=%s)",
        settings.deepseek_model,
        settings.model_config.get("env_file"),
    )
    yield
    logger.info("Shutting down API...")
    from packages.asyncio_compat import shutdown_playwright_loop
    from packages.background_tasks import shutdown as shutdown_background_tasks

    await shutdown_background_tasks()
    shutdown_playwright_loop()
    from services.fetch_worker.resume_library_viewer import close_resume_library_viewer

    try:
        await close_resume_library_viewer()
    except Exception:
        logger.exception("Failed to close resume library viewer")
    logger.info("Shutdown complete")


app = FastAPI(
    title="招聘多 Agent 协作系统",
    description="Workflow-driven recruiting system with Playwright, Pydantic AI, and Temporal",
    version="0.1.0",
    lifespan=lifespan,
)

# 生产网页模式：控制台与 API 同源 (/:8001)，无需 CORS。
# 开发模式 (Vite :5173) 及局域网调试：允许私有网段来源。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https?://192\.168\.\d+\.\d+(:\d+)?|https?://10\.\d+\.\d+\.\d+(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows.router)
app.include_router(browser_setup.router)


@app.exception_handler(AgentInferenceError)
async def agent_inference_error_handler(_request: Request, exc: AgentInferenceError):
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc), "error_type": "agent_inference_failed"},
    )


app.include_router(candidates.router)
app.include_router(conversations.router)
app.include_router(followup.router)
app.include_router(messages.router)
app.include_router(system.router)
app.include_router(runtime_settings.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/deepseek")
async def health_deepseek():
    """Check DeepSeek API connectivity (for troubleshooting)."""
    import httpx

    from packages.settings import get_settings
    from services.agent_service.llm import get_deepseek_http_client

    settings = get_settings()
    if not settings.deepseek_api_key:
        return {"ok": False, "error": "DEEPSEEK_API_KEY 未配置"}

    try:
        client = get_deepseek_http_client()
        resp = await client.get(f"{settings.deepseek_base_url.rstrip('/')}/models")
        return {
            "ok": resp.status_code < 500,
            "status_code": resp.status_code,
            "trust_env": settings.deepseek_trust_env,
            "base_url": settings.deepseek_base_url,
        }
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e), "hint": "若含 proxy，请确认 .env 中 DEEPSEEK_TRUST_ENV=false"}


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if templates:
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={},
        )
    return HTMLResponse("<h1>Admin UI</h1><p>Templates not found. API is running at /docs</p>")


@app.get("/admin/workflows/{workflow_id}", response_class=HTMLResponse)
async def admin_workflow_detail(request: Request, workflow_id: str):
    if templates:
        return templates.TemplateResponse(
            request=request,
            name="workflow_detail.html",
            context={"workflow_id": workflow_id},
        )
    return HTMLResponse(f"<h1>Workflow {workflow_id}</h1>")


console_dist = Path(os.environ.get("HRAGENT_CONSOLE_DIST") or Path(__file__).parent.parent / "console-web" / "dist")
if console_dist.exists():
    app.mount("/", ConsoleStaticFiles(directory=str(console_dist), html=True), name="console")
    logger.info("Mounted console SPA from %s", console_dist)
