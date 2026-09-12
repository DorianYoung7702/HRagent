import asyncio
import uuid

from packages.schemas.candidate import FetchInput, FetchOutput
from packages.settings import is_browser_headless

from services.fetch_worker.browser_pool import new_page, release_browser

from services.fetch_worker.extract_detail import extract_resume_detail

from services.fetch_worker.extract_list import (

    extract_candidate_cards,

    go_next_page,

    has_next_page,

)

from services.fetch_worker.extract_popup import extract_from_popup_cards

from packages.db.repositories import WorkflowRepository
from packages.db.session import async_session_factory

from services.fetch_worker.lpt_adapter import LptSearchParams

from services.fetch_worker.experience_fallback import (
    experience_try_sequence,
    initial_experience_filter,
    next_experience_fallback,
    normalize_experience,
)
from services.fetch_worker.keyword_fallback import next_keyword_fallback
from services.fetch_worker.lpt_search import (
    count_result_cards,
    rerun_lpt_search_with_experience,
    rerun_lpt_search_with_keywords,
    run_lpt_search,
    wait_for_result_cards,
)

from services.fetch_worker.normalizer import normalize_card_to_snapshot

from services.fetch_worker.page_detector import PageDetectionError, PageType, detect_page_type

from services.fetch_worker.snapshot_writer import save_snapshots


async def _live_collect_only(workflow_id: str, fallback: bool) -> bool:
    try:
        async with async_session_factory() as session:
            wf = await WorkflowRepository(session).get(workflow_id)
            if wf and wf.config:
                return bool((wf.config.get("fetch") or {}).get("collect_only", fallback))
    except Exception:
        pass
    return fallback


async def _live_im_review_required(workflow_id: str, fallback: bool = False) -> bool:
    try:
        async with async_session_factory() as session:
            wf = await WorkflowRepository(session).get(workflow_id)
            if wf and wf.config:
                outreach = wf.config.get("outreach") or {}
                if isinstance(outreach, dict):
                    return bool(outreach.get("im_review_required", fallback))
    except Exception:
        pass
    return fallback


async def run_fetch_task(fetch_input: FetchInput) -> FetchOutput:
    fetch_task_id = f"fetch_{uuid.uuid4().hex[:12]}"
    if fetch_input.platform == "boss" or fetch_input.search.mode == "boss_search":
        from services.fetch_worker.boss_runner import run_boss_fetch_task

        return await run_boss_fetch_task(fetch_input, fetch_task_id=fetch_task_id)

    profile = fetch_input.browser_profile
    snapshots_data: list = []
    saved_ids: list[str] = []
    failed_items: list[dict[str, str]] = []

    had_error = False
    page = None
    try:
        page = await new_page(profile)

        if fetch_input.search.mode == "lpt_search":
            snapshots_data, failed_items, saved_ids = await _run_lpt_search_fetch(page, fetch_input)
        else:
            snapshots_data, failed_items = await _run_url_direct_fetch(page, fetch_input)

    except Exception:
        had_error = True
        raise
    finally:
        if had_error and not is_browser_headless():
            await asyncio.sleep(5)
        if page is not None:
            await page.close()
        await release_browser(profile)

    if saved_ids:
        snapshot_ids = saved_ids
    elif snapshots_data:
        snapshot_ids = await save_snapshots(snapshots_data)
    else:
        snapshot_ids = []

    return FetchOutput(
        fetch_task_id=fetch_task_id,
        workflow_id=fetch_input.workflow_id,
        captured_count=len(snapshot_ids),
        candidate_snapshot_ids=snapshot_ids,
        failed_items=failed_items,
    )





async def _run_lpt_search_fetch(page, fetch_input: FetchInput):
    snapshots_data = []
    saved_ids: list[str] = []
    failed_items: list[dict[str, str]] = []

    from packages.workflow_events import emit, workflow_context

    params = LptSearchParams(
        keywords=fetch_input.search.keywords,
        city=fetch_input.search.city,
        cities=list(fetch_input.search.cities or []),
        current_cities=list(fetch_input.search.current_cities or []),
        experience=fetch_input.search.experience,
        education=fetch_input.search.education,
        other_filters=fetch_input.search.other_filters,
        entry_url=fetch_input.search.entry_url or fetch_input.start_url,
    )

    tried_experiences: set[str] = set()
    tried_keywords: set[str] = set()
    seen_candidate_fps: set[str] = set()
    requested_experience = (params.experience or "").strip()
    exp_plan = experience_try_sequence(requested_experience)
    current_experience = initial_experience_filter(requested_experience)
    current_keywords = (params.keywords or "").strip()
    tried_keywords.add(current_keywords)
    target_count = fetch_input.target_count

    if requested_experience and requested_experience != current_experience:
        emit(
            "info",
            f"工作年限「{normalize_experience(requested_experience)}」"
            f"→ 猎聘筛选项「{current_experience}」"
            + (f"（备选: {'、'.join(exp_plan[1:3])}…）" if len(exp_plan) > 1 else ""),
            category="search",
            workflow_id=fetch_input.workflow_id,
            meta={
                "requested_experience": requested_experience,
                "experience": current_experience,
                "experience_plan": exp_plan,
            },
        )

    from packages.workflow_control import wait_if_paused

    with workflow_context(fetch_input.workflow_id):
        while True:
            await wait_if_paused(fetch_input.workflow_id)
            params.experience = current_experience
            fetch_input.search.experience = current_experience
            tried_experiences.add(current_experience)

            if len(tried_experiences) == 1:
                await run_lpt_search(page, params)
            else:
                await rerun_lpt_search_with_experience(page, params, current_experience)

            has_cards = await wait_for_result_cards(page)
            card_count = await count_result_cards(page) if has_cards else 0
            captured_so_far = len(saved_ids) + len(snapshots_data)

            if not has_cards or card_count == 0:
                next_exp = next_experience_fallback(
                    current_experience,
                    tried_experiences,
                    requested=requested_experience,
                )
                if next_exp:
                    emit(
                        "warn",
                        f"搜索无结果（年限 {current_experience}），"
                        f"切换需求年限段为 {next_exp} 后重搜",
                        category="search",
                        workflow_id=fetch_input.workflow_id,
                        meta={"from": current_experience, "to": next_exp},
                    )
                    current_experience = next_exp
                    continue
                failed_items.append(
                    {
                        "error": (
                            f"搜索完成但未找到简历卡片（已尝试年限: "
                            f"{', '.join(sorted(tried_experiences))}）"
                        )
                    }
                )
                break

            remaining = target_count - captured_so_far
            collect_only = await _live_collect_only(
                fetch_input.workflow_id,
                fetch_input.collect_only,
            )
            im_review_required = await _live_im_review_required(fetch_input.workflow_id)
            snapshots_batch, popup_failed, saved_batch, list_exhausted = (
                await extract_from_popup_cards(
                    page,
                    workflow_id=fetch_input.workflow_id,
                    platform=fetch_input.platform,
                    target_count=remaining,
                    job_id=fetch_input.job_id,
                    job_title=fetch_input.job_title,
                    job_description=fetch_input.job_description,
                    screening_criteria=fetch_input.screening_criteria,
                    min_score=fetch_input.screening_min_score,
                    auto_screen=fetch_input.search.auto_screen,
                    seen_candidate_fps=seen_candidate_fps,
                    collect_only=collect_only,
                    im_review_required=im_review_required,
                    collect_parent_group=fetch_input.collect_parent_group,
                )
            )
            snapshots_data.extend(snapshots_batch)
            saved_ids.extend(saved_batch)
            failed_items.extend(popup_failed)

            captured_so_far = len(saved_ids) + len(snapshots_data)
            if captured_so_far >= target_count:
                break

            if captured_so_far < target_count:
                next_exp = next_experience_fallback(
                    current_experience,
                    tried_experiences,
                    requested=requested_experience,
                )
                if next_exp:
                    if list_exhausted:
                        emit(
                            "warn",
                            (
                                f"列表候选人不足（{captured_so_far}/{target_count}），"
                                f"先切换工作年限 {current_experience} → {next_exp} 后重搜"
                                f"（需求区间 {normalize_experience(requested_experience)}）"
                            ),
                            category="search",
                            workflow_id=fetch_input.workflow_id,
                            meta={
                                "captured": captured_so_far,
                                "target_count": target_count,
                                "from": current_experience,
                                "to": next_exp,
                                "list_exhausted": True,
                            },
                        )
                    else:
                        emit(
                            "warn",
                            (
                                f"已处理 {captured_so_far}/{target_count} 份，"
                                f"切换工作年限 {current_experience} → {next_exp} 后继续搜索"
                            ),
                            category="search",
                            workflow_id=fetch_input.workflow_id,
                            meta={
                                "captured": captured_so_far,
                                "target_count": target_count,
                                "from": current_experience,
                                "to": next_exp,
                            },
                        )
                    current_experience = next_exp
                    continue

                if list_exhausted:
                    next_kw = next_keyword_fallback(current_keywords, tried_keywords)
                    if next_kw:
                        emit(
                            "warn",
                            (
                                f"列表候选人不足（{captured_so_far}/{target_count}），"
                                f"需求年限段已全部尝试，删减搜索关键词"
                                f"「{current_keywords}」→「{next_kw}」后重搜"
                                f"（保留必要词：西班牙语、销售）"
                            ),
                            category="search",
                            workflow_id=fetch_input.workflow_id,
                            meta={
                                "from_keywords": current_keywords,
                                "to_keywords": next_kw,
                                "captured": captured_so_far,
                                "target_count": target_count,
                            },
                        )
                        current_keywords = next_kw
                        tried_keywords.add(next_kw)
                        params.keywords = next_kw
                        fetch_input.search.keywords = next_kw
                        current_experience = initial_experience_filter(requested_experience)
                        tried_experiences.clear()
                        await rerun_lpt_search_with_keywords(page, params, next_kw)
                        continue

                    emit(
                        "error",
                        (
                            f"列表候选人不足（{captured_so_far}/{target_count}），"
                            f"需求年限段与搜索关键词均已无法继续调整，停止搜索"
                        ),
                        category="search",
                        workflow_id=fetch_input.workflow_id,
                        meta={
                            "keywords": current_keywords,
                            "captured": captured_so_far,
                            "target_count": target_count,
                            "experiences_tried": sorted(tried_experiences),
                        },
                    )
                    if captured_so_far == 0:
                        failed_items.append(
                            {
                                "error": (
                                    f"候选人不足且需求年限段、关键词均已用尽，"
                                    f"未达目标 {target_count} 份"
                                )
                            }
                        )
                    break

                if captured_so_far == 0:
                    failed_items.append(
                        {
                            "error": (
                                f"未满足目标份数 {target_count}（已尝试年限: "
                                f"{', '.join(sorted(tried_experiences))}）"
                            )
                        }
                    )
                else:
                    emit(
                        "warn",
                        f"仅抓取到 {captured_so_far}/{target_count} 份，需求年限段已全部尝试",
                        category="search",
                        workflow_id=fetch_input.workflow_id,
                        meta={"captured": captured_so_far, "target_count": target_count},
                    )
                break

    return snapshots_data, failed_items, saved_ids





async def _run_url_direct_fetch(page, fetch_input: FetchInput):

    snapshots_data = []

    failed_items: list[dict[str, str]] = []



    await page.goto(fetch_input.start_url, wait_until="domcontentloaded")

    await page.wait_for_timeout(2000)



    page_type = await detect_page_type(page)

    if page_type == PageType.LOGIN:

        raise PageDetectionError(

            PageType.LOGIN,

            "检测到登录页，请先运行: .\\scripts\\login_liepin.ps1 完成猎聘 LPT 登录",

        )

    if page_type == PageType.PERMISSION:

        raise PageDetectionError(PageType.PERMISSION, "无权限访问该页面")



    captured = 0

    current_page = 0



    while captured < fetch_input.target_count and current_page < fetch_input.max_pages:

        cards = await extract_candidate_cards(page)

        if not cards:

            failed_items.append({"page": str(current_page), "error": "未找到候选人卡片"})

            break



        for card in cards:

            if captured >= fetch_input.target_count:

                break



            try:

                detail = None

                if fetch_input.detail_required and card.source_url:

                    detail_page = await page.context.new_page()

                    try:

                        await detail_page.goto(card.source_url, wait_until="domcontentloaded")

                        await detail_page.wait_for_timeout(1500)

                        d_type = await detect_page_type(detail_page)

                        if d_type == PageType.DETAIL:

                            detail = await extract_resume_detail(detail_page)

                        elif d_type == PageType.LOGIN:

                            raise PageDetectionError(PageType.LOGIN, "详情页需要登录")

                    finally:

                        await detail_page.close()



                snap = normalize_card_to_snapshot(

                    card, detail, fetch_input.workflow_id, fetch_input.platform

                )

                snapshots_data.append(snap)

                captured += 1

            except Exception as e:

                failed_items.append({

                    "candidate": card.display_name or "unknown",

                    "error": str(e),

                })



        current_page += 1

        if current_page >= fetch_input.max_pages or captured >= fetch_input.target_count:

            break

        if not await has_next_page(page):

            break

        if not await go_next_page(page):

            break



    return snapshots_data, failed_items
