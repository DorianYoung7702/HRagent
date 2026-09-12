"""简历库浏览器会话：按 profile 复用标签页，在岗位文件夹内匹配候选人行。"""



from __future__ import annotations



import asyncio

import logging

from typing import Any



from packages.asyncio_compat import run_on_playwright_loop

from services.fetch_worker.browser_pool import acquire_browser, release_browser

from services.fetch_worker.im_contact_match import candidate_display_name

from services.fetch_worker.resume_library_nav import open_candidate_in_resume_library

from services.fetch_worker.resume_library_row_match import ResumeLibraryMatchProfile



logger = logging.getLogger(__name__)



_lock = asyncio.Lock()

_viewer_pages: dict[str, Any] = {}

_browser_refs: dict[str, bool] = {}





async def _ensure_viewer_page(profile_name: str = "hr_default"):

    page = _viewer_pages.get(profile_name)

    if page is not None and not page.is_closed():

        return page



    if page is not None and not page.is_closed():

        await page.close()



    if not _browser_refs.get(profile_name):

        await acquire_browser(profile_name)

        _browser_refs[profile_name] = True



    from services.fetch_worker import browser_pool



    entry = browser_pool._pool.get(profile_name)

    if not entry:

        raise RuntimeError("无法启动猎聘浏览器，请确认 Playwright 已安装")

    mgr = entry[0]

    page = await mgr.new_page()

    _viewer_pages[profile_name] = page

    return page





async def close_resume_library_viewer_for_profile(profile_name: str) -> None:

    page = _viewer_pages.pop(profile_name, None)

    if page is not None and not page.is_closed():

        try:

            await page.close()

        except Exception:

            pass

    if _browser_refs.pop(profile_name, False):

        try:

            await release_browser(profile_name)

        except Exception:

            pass





async def close_resume_library_viewer() -> None:

    for profile in list(_viewer_pages.keys()):

        await close_resume_library_viewer_for_profile(profile)





async def _open_snapshot_impl(

    snapshot: Any,

    screening: Any | None,

    *,

    job_folder: str = "",

    profile_name: str = "hr_default",

) -> dict:

    level = screening.level if screening else None

    if level not in ("observe", "followup"):

        raise ValueError("仅支持「观察」或「追问」清单中的候选人跳转简历库")



    profile = ResumeLibraryMatchProfile.from_candidate(

        display_name=candidate_display_name(snapshot),

        current_title=snapshot.current_title,

        current_company=snapshot.current_company,

        education=snapshot.education,

        screening_level=level,

        metadata=snapshot.metadata_ or {},

        captured_at=snapshot.captured_at.isoformat() if snapshot.captured_at else None,

        job_folder=job_folder or None,

    )



    page = await _ensure_viewer_page(profile_name)

    return await open_candidate_in_resume_library(page, profile)





async def open_candidate_resume_library(workflow_id: str, snapshot_id: str) -> dict:

    from packages.db.repositories import CandidateRepository, ScreeningRepository, WorkflowRepository

    from packages.db.session import async_session_factory

    from services.fetch_worker.collect_grouping import resolve_job_collect_folder_from_config

    from services.fetch_worker.workflow_browser_profile import workflow_browser_profile_name



    async with async_session_factory() as session:

        candidate_repo = CandidateRepository(session)

        screening_repo = ScreeningRepository(session)

        workflow_repo = WorkflowRepository(session)

        snap = await candidate_repo.get(snapshot_id)

        if not snap or snap.workflow_id != workflow_id:

            raise ValueError("候选人不存在")

        screening = await screening_repo.get_latest_for_candidate(workflow_id, snapshot_id)

        wf = await workflow_repo.get(workflow_id)

        job_folder = resolve_job_collect_folder_from_config(wf.config if wf else None)

        fetch_cfg = (wf.config or {}).get("fetch") if wf else {}

        profile_name = (fetch_cfg or {}).get("browser_profile") or workflow_browser_profile_name(

            workflow_id

        )



    async with _lock:

        return await _open_snapshot_impl(

            snap,

            screening,

            job_folder=job_folder,

            profile_name=profile_name,

        )





async def open_candidate_resume_library_via_loop(workflow_id: str, snapshot_id: str) -> dict:

    return await run_on_playwright_loop(open_candidate_resume_library(workflow_id, snapshot_id))

