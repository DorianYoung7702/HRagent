"""One-time PDF resume import.

Uploaded PDFs are staged under the OS temporary directory using sequence-only
filenames. The worker reads at most ten files concurrently and removes each
source immediately after processing. Source bytes, original names, extracted
text, and hashes never enter workflow metadata, events, or the database.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import shutil
import tempfile
import uuid
from pathlib import Path

from pypdf import PdfReader

from packages.db.repositories import CandidateRepository, ScreeningRepository, WorkflowRepository
from packages.db.session import async_session_factory
from packages.db.sqlite_guard import run_sqlite_write
from packages.schemas.candidate import CandidateSnapshotData
from packages.schemas.workflow import PdfImportStartRequest
from packages.workflow_events import emit
from packages.workflow_runtime import unregister_workflow_session
from services.agent_service.screening_service import (
    annotate_screening_output,
    rebuild_shortlist_from_latest,
    resolve_workflow_screening_context,
)
from services.agent_service.reply_summary_agent import (
    _fallback_report,
    list_reply_summary_candidates,
    persist_reply_judgment_summary_report,
)
from services.agent_service.visa_screening_agent import screen_visa_only, visa_result_to_screening

MAX_PDF_PAGES = 30
MAX_EXTRACTED_CHARS = 50_000
MAX_PDF_IMPORT_FILES = 1_000
MAX_PDF_FILE_BYTES = 30 * 1024 * 1024
MAX_PDF_IMPORT_TOTAL_BYTES = 5 * 1024 * 1024 * 1024
PDF_IMPORT_CONCURRENCY = 10
PDF_IMPORT_READ_CHUNK_BYTES = 1024 * 1024
_PDF_IMPORT_TEMP_PREFIX = "hragent-pdf-import-"

# Process-wide by design: separate PDF workflows cannot exceed ten simultaneous model calls.
_pdf_import_semaphore = asyncio.Semaphore(PDF_IMPORT_CONCURRENCY)


class PdfImportError(ValueError):
    """A non-persistent per-file import error."""


def create_pdf_import_staging_dir() -> Path:
    """Create a per-request temporary queue; only sequence names are used."""
    return Path(tempfile.mkdtemp(prefix=_PDF_IMPORT_TEMP_PREFIX))


def cleanup_pdf_import_staging_dir(directory: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    if directory.is_symlink() or directory.parent.resolve() != temp_root:
        raise ValueError("Refusing to clean a directory outside the PDF temporary root")
    if not directory.name.startswith(_PDF_IMPORT_TEMP_PREFIX):
        raise ValueError("Refusing to clean a directory not owned by PDF import")
    shutil.rmtree(directory, ignore_errors=True)


def cleanup_stale_pdf_import_staging() -> int:
    """Remove abandoned upload queues after a stopped or crashed API process."""
    removed = 0
    for directory in Path(tempfile.gettempdir()).glob(f"{_PDF_IMPORT_TEMP_PREFIX}*"):
        if not directory.is_dir():
            continue
        cleanup_pdf_import_staging_dir(directory)
        removed += 1
    return removed


def extract_pdf_text(content: bytes | Path) -> str:
    try:
        source = io.BytesIO(content) if isinstance(content, bytes) else str(content)
        reader = PdfReader(source)
        if reader.is_encrypted:
            raise PdfImportError("encrypted_pdf")
        chunks: list[str] = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            chunks.append(page.extract_text() or "")
            if sum(len(chunk) for chunk in chunks) >= MAX_EXTRACTED_CHARS:
                break
    except PdfImportError:
        raise
    except Exception as exc:
        raise PdfImportError("invalid_or_unreadable_pdf") from exc

    text = "\n".join(chunks).strip()[:MAX_EXTRACTED_CHARS]
    if len("".join(text.split())) < 100:
        raise PdfImportError("pdf_text_not_found")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(PDF_IMPORT_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def initial_pdf_import_progress(total: int) -> dict[str, int | str]:
    return {
        "total": total,
        "processing": 0,
        "completed": 0,
        "duplicate": 0,
        "failed": 0,
        "state": "queued",
        "ranking_state": "queued",
        "ranking_error": "",
    }


async def _patch_progress(workflow_id: str, progress: dict[str, int | str]) -> None:
    async def write() -> None:
        async with async_session_factory() as session:
            await WorkflowRepository(session).patch_config(
                workflow_id, {"pdf_import": dict(progress)}
            )
            await session.commit()

    await run_sqlite_write(write)


async def _save_screened_candidate(
    workflow_id: str,
    job_id: str,
    visa,
    screening_criteria: str,
    criteria_version: int,
) -> None:
    """Persist only Agent-produced structured facts; source text is already out of scope here."""

    async def write() -> None:
        async with async_session_factory() as session:
            candidate_repo = CandidateRepository(session)
            screening_repo = ScreeningRepository(session)
            snapshot = await candidate_repo.save_snapshot(
                CandidateSnapshotData(
                    workflow_id=workflow_id,
                    platform="local_pdf",
                    display_name=(visa.display_name or "").strip() or None,
                    current_title=(visa.current_title or "").strip() or None,
                    current_company=(visa.current_company or "").strip() or None,
                    work_years=visa.work_years,
                    education=(visa.education or "").strip() or None,
                    city=(visa.city or "").strip() or None,
                    skills=list(visa.skills or []),
                    summary=(visa.resume_summary or "").strip() or None,
                    experience_summary=(visa.experience_summary or "").strip() or None,
                    project_summary=(visa.project_summary or "").strip() or None,
                    raw_text="",
                    extraction_confidence=0.8,
                    template_type="local_pdf_one_time_v1",
                    metadata={"source_type": "pdf_one_time"},
                )
            )
            output = annotate_screening_output(
                visa_result_to_screening(snapshot.id, visa),
                screening_criteria=screening_criteria,
                criteria_version=criteria_version,
                preference_source="hr_preference_memory",
            )
            await screening_repo.save_result(workflow_id, job_id, output)
            await session.commit()

    await run_sqlite_write(write)


async def _finish_workflow(workflow_id: str, *, partial: bool = False) -> None:
    async def write() -> None:
        async with async_session_factory() as session:
            repo = WorkflowRepository(session)
            workflow = await repo.get(workflow_id)
            if not workflow:
                return
            config = dict(workflow.config or {})
            progress = dict(config.get("pdf_import") or {})
            progress["processing"] = 0
            progress["state"] = "partial_failed" if partial else "completed"
            await repo.patch_config(workflow_id, {"pdf_import": progress})
            if partial:
                await repo.update_status(
                    workflow_id,
                    "PARTIAL_FAILED",
                    error_message="PDF 导入已中断，请重新上传未完成的简历",
                )
            else:
                screening_cfg = dict(config.get("screening") or {})
                shortlist = await rebuild_shortlist_from_latest(
                    workflow_id,
                    job_id=workflow.job_id,
                    top_k=int(screening_cfg.get("top_k") or 10),
                    min_score=float(screening_cfg.get("min_score") or 60),
                    session=session,
                )
                await repo.update_status(
                    workflow_id,
                    "SCREENING_COMPLETED",
                    shortlist_id=shortlist.shortlist_id,
                )
            await session.commit()

    await run_sqlite_write(write)


async def run_pdf_import_ranking(
    workflow_id: str,
    progress: dict[str, int | str] | None = None,
) -> dict | None:
    if progress is None:
        async with async_session_factory() as session:
            workflow = await WorkflowRepository(session).get(workflow_id)
            if not workflow:
                raise ValueError(f"Workflow not found: {workflow_id}")
            progress = dict((workflow.config or {}).get("pdf_import") or {})

    progress["ranking_state"] = "ranking"
    progress["ranking_error"] = ""
    await _patch_progress(workflow_id, progress)
    emit(
        "info",
        "PDF 综合排名开始：按初筛匹配分数重排",
        category="pdf_import",
        workflow_id=workflow_id,
        meta={"phase": "ranking", "ranking_source": "initial_fit_score"},
    )
    try:
        candidates = await list_reply_summary_candidates(
            workflow_id,
            candidate_levels=frozenset({"observe", "followup"}),
        )
        report = _fallback_report(workflow_id, candidates)
        report["summary"] = (
            "## 候选人排序总结报告\n\n"
            "### 排名依据\n"
            "以下排序直接按初筛 Agent 已保存的匹配分数（fit_score）从高到低生成；"
            "不会再次调用模型。候选人的命中项、风险点和推荐理由均来自初筛结果。\n\n"
            + str(report.get("summary") or "")
        )
        await persist_reply_judgment_summary_report(
            workflow_id,
            report,
            config_key="pdf_import_summary_report",
        )
        progress["ranking_state"] = "completed"
        emit(
            "success",
            f"PDF 综合排名完成：{len(report.get('ranked_candidates') or [])} 人（按初筛分数）",
            category="pdf_import",
            workflow_id=workflow_id,
            meta={"phase": "ranking", "ranking_source": "initial_fit_score"},
        )
        return report
    except Exception as exc:
        progress["ranking_state"] = "failed"
        progress["ranking_error"] = "综合排名生成失败"
        emit(
            "warn",
            f"PDF 综合排名 Agent 异常: {exc}",
            category="pdf_import",
            workflow_id=workflow_id,
            meta={"phase": "ranking", "error_code": type(exc).__name__},
        )
        return None
    finally:
        await _patch_progress(workflow_id, progress)


async def run_pdf_import_job(
    workflow_id: str,
    body: PdfImportStartRequest,
    file_paths: list[Path],
) -> None:
    """Process one disk-backed batch and delete every source on completion."""
    progress = initial_pdf_import_progress(len(file_paths))
    state_lock = asyncio.Lock()
    seen_binary_hashes: set[str] = set()
    seen_text_hashes: set[str] = set()
    staging_dirs = {path.parent for path in file_paths}

    async def update(kind: str) -> None:
        async with state_lock:
            if kind == "processing":
                progress["processing"] = int(progress["processing"]) + 1
            elif kind == "done":
                progress["processing"] = max(0, int(progress["processing"]) - 1)
                progress["completed"] = int(progress["completed"]) + 1
            elif kind == "duplicate":
                progress["duplicate"] = int(progress["duplicate"]) + 1
            elif kind == "failed":
                progress["processing"] = max(0, int(progress["processing"]) - 1)
                progress["failed"] = int(progress["failed"]) + 1
            await _patch_progress(workflow_id, progress)

    async def process_one(index: int) -> None:
        path = file_paths[index]
        try:
            binary_hash = await asyncio.to_thread(_sha256_file, path)
            async with state_lock:
                if binary_hash in seen_binary_hashes:
                    duplicate = True
                else:
                    seen_binary_hashes.add(binary_hash)
                    duplicate = False
            if duplicate:
                await update("duplicate")
                emit("info", f"PDF #{index + 1} 已跳过：与本批文件重复", category="pdf_import", workflow_id=workflow_id, meta={"candidate_index": index + 1, "phase": "dedupe"})
                return

            text = await asyncio.to_thread(extract_pdf_text, path)
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            async with state_lock:
                if text_hash in seen_text_hashes:
                    duplicate_text = True
                else:
                    seen_text_hashes.add(text_hash)
                    duplicate_text = False
            if duplicate_text:
                await update("duplicate")
                emit("info", f"PDF #{index + 1} 已跳过：文本内容重复", category="pdf_import", workflow_id=workflow_id, meta={"candidate_index": index + 1, "phase": "dedupe"})
                return

            await update("processing")
            emit("info", f"PDF #{index + 1} 正在解析与筛选", category="pdf_import", workflow_id=workflow_id, meta={"candidate_index": index + 1, "total": len(file_paths), "phase": "screening"})
            async with _pdf_import_semaphore:
                criteria, criteria_version = await resolve_workflow_screening_context(
                    workflow_id, body.screening_criteria
                )
                visa = await screen_visa_only(
                    f"pdf-import-{uuid.uuid4().hex}", text, {}, criteria
                )
            await _save_screened_candidate(
                workflow_id, body.job_id, visa, criteria, criteria_version
            )
            await update("done")
            emit("success", f"PDF #{index + 1} 筛选完成：{visa.decision or '已完成'}", category="pdf_import", workflow_id=workflow_id, meta={"candidate_index": index + 1, "phase": "screening", "decision": visa.decision or ""})
        except asyncio.CancelledError:
            raise
        except Exception:
            # Per-file details and source identifiers are intentionally never persisted.
            await update("failed")
            emit("warn", f"PDF #{index + 1} 解析失败，已跳过", category="pdf_import", workflow_id=workflow_id, meta={"candidate_index": index + 1, "phase": "screening"})
        finally:
            # Source files are never retained after their one-time screening pass.
            path.unlink(missing_ok=True)

    try:
        progress["state"] = "processing"
        await _patch_progress(workflow_id, progress)
        emit("info", f"PDF 批量筛选已启动：共 {len(file_paths)} 份", category="pdf_import", workflow_id=workflow_id)
        # Schedule only ten files at a time, even for a 1,000-file upload.
        for start in range(0, len(file_paths), PDF_IMPORT_CONCURRENCY):
            stop = min(start + PDF_IMPORT_CONCURRENCY, len(file_paths))
            await asyncio.gather(*(process_one(index) for index in range(start, stop)))
        await _finish_workflow(workflow_id)
        progress["processing"] = 0
        progress["state"] = "completed"
        await run_pdf_import_ranking(workflow_id, progress)
        emit(
            "success",
            "PDF 批量筛选完成："
            f"完成 {progress['completed']}，重复 {progress['duplicate']}，失败 {progress['failed']}",
            category="pdf_import",
            workflow_id=workflow_id,
        )
    except asyncio.CancelledError:
        await asyncio.shield(_finish_workflow(workflow_id, partial=True))
        raise
    except Exception:
        await _finish_workflow(workflow_id, partial=True)
        emit("error", "PDF 批量筛选异常中断，请重新上传未完成简历", category="pdf_import", workflow_id=workflow_id)
    finally:
        for path in file_paths:
            path.unlink(missing_ok=True)
        file_paths.clear()
        for directory in staging_dirs:
            cleanup_pdf_import_staging_dir(directory)
        seen_binary_hashes.clear()
        seen_text_hashes.clear()
        unregister_workflow_session(workflow_id)
