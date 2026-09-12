import re

from playwright.async_api import Locator, Page

from services.fetch_worker.liepin_adapter import SECTION_TITLES, SELECTORS


async def expand_all_sections(scope: Page | Locator) -> None:
    for sel in SELECTORS.expand_buttons:
        try:
            buttons = scope.locator(sel)
            count = await buttons.count()
            for i in range(min(count, 10)):
                btn = buttons.nth(i)
                if await btn.is_visible(timeout=500):
                    await btn.click()
        except Exception:
            continue


async def scroll_to_load(scope: Page | Locator) -> None:
    page = scope if isinstance(scope, Page) else scope.page
    for _ in range(5):
        if isinstance(scope, Page):
            await scope.evaluate("window.scrollBy(0, window.innerHeight)")
        else:
            await scope.evaluate("el => el.scrollTop += el.clientHeight")
        await page.wait_for_timeout(500)
    if isinstance(scope, Page):
        await scope.evaluate("window.scrollTo(0, 0)")


async def _extract_by_section_title(page: Page, title: str) -> str | None:
    try:
        section = page.locator(f"text={title}").first
        if await section.is_visible(timeout=2000):
            parent = section.locator("xpath=ancestor::div[1]")
            text = await parent.inner_text()
            text = text.replace(title, "", 1).strip()
            if text:
                return text
    except Exception:
        pass

    try:
        section = page.locator(f"section:has-text('{title}')").first
        if await section.is_visible(timeout=1000):
            return (await section.inner_text()).strip()
    except Exception:
        pass

    return None


async def _extract_by_selectors(page: Page, selectors: list[str]) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1000):
                text = (await loc.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue
    return None


async def _extract_name(page: Page) -> str | None:
    return await _extract_by_selectors(page, SELECTORS.detail_name)


def _parse_work_years(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*年", text)
    return float(match.group(1)) if match else None


def _parse_education(text: str) -> str | None:
    for edu in ["博士", "硕士", "本科", "大专", "MBA"]:
        if edu in text:
            return edu
    return None


def _parse_city(text: str) -> str | None:
    cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "苏州"]
    for city in cities:
        if city in text:
            return city
    return None


def _parse_skills(text: str) -> list[str]:
    skills = []
    common = [
        "Java", "Python", "Go", "Spring Boot", "Spring", "MySQL", "Redis",
        "Kafka", "Docker", "Kubernetes", "React", "Vue", "微服务", "高并发",
    ]
    for skill in common:
        if skill.lower() in text.lower() or skill in text:
            skills.append(skill)
    return skills


async def extract_resume_detail(page: Page) -> dict:
    await scroll_to_load(page)
    await expand_all_sections(page)
    await page.wait_for_timeout(1000)

    raw_text = await page.locator("body").inner_text()
    name = await _extract_name(page)

    sections: dict[str, str | None] = {}
    for title in SECTION_TITLES:
        content = await _extract_by_section_title(page, title)
        if not content and title in SELECTORS.detail_sections:
            content = await _extract_by_selectors(page, SELECTORS.detail_sections[title])
        sections[title] = content

    experience = sections.get("工作经历")
    project = sections.get("项目经历")
    education_text = sections.get("教育经历")
    summary = sections.get("个人优势") or sections.get("自我评价")

    skills_text = sections.get("技能标签") or ""
    skills = _parse_skills(raw_text + " " + skills_text)

    missing_fields = [k for k, v in sections.items() if not v and k in SECTION_TITLES[:4]]
    if not experience:
        missing_fields.append("experience_summary")
    if not project:
        missing_fields.append("project_summary")

    filled = sum(1 for v in sections.values() if v)
    total = len(SECTION_TITLES)
    confidence = round(filled / total, 2) if total else 0.5

    current_title = None
    if experience:
        lines = [line.strip() for line in experience.split("\n") if line.strip()]
        if lines:
            current_title = lines[0][:100]

    return {
        "display_name": name,
        "current_title": current_title,
        "current_company": None,
        "work_years": _parse_work_years(raw_text),
        "education": _parse_education(raw_text) or (education_text[:50] if education_text else None),
        "city": _parse_city(raw_text),
        "skills": skills,
        "summary": summary,
        "experience_summary": experience,
        "project_summary": project,
        "raw_text": raw_text[:50000],
        "extraction_confidence": confidence,
        "missing_fields": missing_fields,
        "template_type": "liepin_resume_detail_v2",
        "sections": sections,
    }
