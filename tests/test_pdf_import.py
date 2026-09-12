from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.db.models import Base, CandidateSnapshot
from packages.db.repositories import WorkflowRepository
from packages.schemas.screening import VisaScreeningOutput
from packages.schemas.workflow import PdfImportStartRequest


def test_pdf_import_rejects_missing_text_without_persisting_source():
    from services.agent_service.pdf_import_service import PdfImportError, extract_pdf_text

    with pytest.raises(PdfImportError):
        extract_pdf_text(b"not a pdf")


@pytest.mark.asyncio
async def test_pdf_import_dedupes_in_memory_and_persists_structured_result_only(tmp_path, monkeypatch):
    from services.agent_service import pdf_import_service as service
    from services.agent_service import reply_summary_agent

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'pdf_import.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        workflow = await WorkflowRepository(session).create(
            name="PDF 测试",
            platform="local_pdf",
            start_url="local://pdf-import",
            job_id="pdf-test",
            config={
                "job": {"screening_criteria": "有三年经验"},
                "screening": {"top_k": 10, "min_score": 60},
                "pdf_import": service.initial_pdf_import_progress(2),
            },
        )
        await session.commit()

    async def direct_write(factory_fn):
        return await factory_fn()

    async def fake_screen(*_args, **_kwargs):
        return VisaScreeningOutput(
            display_name="张三",
            current_title="项目管理专员",
            work_years=3,
            education="本科",
            city="深圳",
            skills=["薪酬", "绩效"],
            resume_summary="3 年项目管理经验。",
            experience_summary="负责项目管理方案。",
            decision="观察",
            reason="满足标准",
            fit_score=88,
            score_rationale="三年同岗位经验且有方案落地经历。",
        )

    monkeypatch.setattr(service, "async_session_factory", factory)
    monkeypatch.setattr(service, "run_sqlite_write", direct_write)
    monkeypatch.setattr(reply_summary_agent, "async_session_factory", factory)
    monkeypatch.setattr(service, "extract_pdf_text", lambda _content: "可解析的简历文本")
    monkeypatch.setattr(service, "screen_visa_only", fake_screen)
    monkeypatch.setattr(service.tempfile, "gettempdir", lambda: str(tmp_path))
    staging = service.create_pdf_import_staging_dir()
    first_file = staging / "0001.pdf"
    second_file = staging / "0002.pdf"
    first_file.write_bytes(b"same-pdf")
    second_file.write_bytes(b"same-pdf")
    await service.run_pdf_import_job(
        workflow.id,
        PdfImportStartRequest(job_id="pdf-test", screening_criteria="有三年经验"),
        [first_file, second_file],
    )

    async with factory() as session:
        rows = list((await session.execute(select(CandidateSnapshot))).scalars().all())
        wf = await WorkflowRepository(session).get(workflow.id)

    assert len(rows) == 1
    assert rows[0].raw_text == ""
    assert rows[0].raw_text_hash is None
    assert rows[0].source_url is None
    assert rows[0].metadata_.get("source_type") == "pdf_one_time"
    assert wf.status == "SCREENING_COMPLETED"
    assert wf.config["pdf_import"] == {
        "total": 2,
        "processing": 0,
        "completed": 1,
        "duplicate": 1,
        "failed": 0,
        "state": "completed",
        "ranking_state": "completed",
        "ranking_error": "",
    }
    report = wf.config["pdf_import_summary_report"]
    assert report["ranked_candidates"][0]["score"] == 88
    assert "不会再次调用模型" in report["summary"]
    assert not first_file.exists()
    assert not second_file.exists()
    await engine.dispose()


def test_pdf_import_capacity_is_one_thousand_files_with_ten_way_concurrency():
    from services.agent_service.pdf_import_service import (
        MAX_PDF_FILE_BYTES,
        MAX_PDF_IMPORT_FILES,
        MAX_PDF_IMPORT_TOTAL_BYTES,
        PDF_IMPORT_CONCURRENCY,
    )

    assert MAX_PDF_IMPORT_FILES == 1_000
    assert MAX_PDF_FILE_BYTES == 30 * 1024 * 1024
    assert MAX_PDF_IMPORT_TOTAL_BYTES == 5 * 1024 * 1024 * 1024
    assert PDF_IMPORT_CONCURRENCY == 10


def test_pdf_import_cleans_stale_temporary_staging_dirs(tmp_path, monkeypatch):
    from services.agent_service import pdf_import_service as service

    stale = tmp_path / "hragent-pdf-import-stale"
    stale.mkdir()
    (stale / "0001.pdf").write_bytes(b"temporary")
    unrelated = tmp_path / "keep-me"
    unrelated.mkdir()
    monkeypatch.setattr(service.tempfile, "gettempdir", lambda: str(tmp_path))

    assert service.cleanup_stale_pdf_import_staging() == 1
    assert not stale.exists()
    assert unrelated.exists()


def test_pdf_cleanup_refuses_unowned_directory(tmp_path, monkeypatch):
    from services.agent_service import pdf_import_service as service

    unrelated = tmp_path / "user-data"
    unrelated.mkdir()
    monkeypatch.setattr(service.tempfile, "gettempdir", lambda: str(tmp_path))
    with pytest.raises(ValueError):
        service.cleanup_pdf_import_staging_dir(unrelated)
    assert unrelated.exists()
