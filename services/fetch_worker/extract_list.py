import re

from playwright.async_api import Page

from packages.schemas.candidate import CandidateCard
from services.fetch_worker.liepin_adapter import SELECTORS


async def _first_visible_text(page: Page, parent_selector: str, selectors: list[str]) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(f"{parent_selector} {sel}").first
            if await loc.is_visible(timeout=1000):
                text = (await loc.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue
    return None


async def _first_visible_href(page: Page, parent_selector: str, selectors: list[str]) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(f"{parent_selector} {sel}").first
            if await loc.is_visible(timeout=1000):
                href = await loc.get_attribute("href")
                if href:
                    return href
        except Exception:
            continue
    return None


def _parse_work_years(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*年", text)
    if match:
        return float(match.group(1))
    return None


async def extract_candidate_cards(page: Page) -> list[CandidateCard]:
    cards: list[CandidateCard] = []
    card_selector = None

    for sel in SELECTORS.list_card:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                card_selector = sel
                break
        except Exception:
            continue

    if not card_selector:
        return cards

    count = await page.locator(card_selector).count()
    for i in range(count):
        parent = f"{card_selector} >> nth={i}"
        try:
            name = await _first_visible_text(page, parent, SELECTORS.card_name)
            title = await _first_visible_text(page, parent, SELECTORS.card_title)
            company = await _first_visible_text(page, parent, SELECTORS.card_company)
            href = await _first_visible_href(page, parent, SELECTORS.card_link)

            card_text = ""
            try:
                card_text = await page.locator(parent).inner_text()
            except Exception:
                pass

            cards.append(
                CandidateCard(
                    source_candidate_id=_extract_id_from_url(href),
                    source_url=_normalize_url(page.url, href),
                    display_name=name,
                    current_title=title,
                    current_company=company,
                    work_years=_parse_work_years(card_text),
                )
            )
        except Exception:
            continue

    return cards


async def has_next_page(page: Page) -> bool:
    for sel in SELECTORS.next_page:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=2000):
                disabled = await loc.get_attribute("disabled")
                class_name = await loc.get_attribute("class") or ""
                if disabled or "disabled" in class_name:
                    return False
                return True
        except Exception:
            continue
    return False


async def go_next_page(page: Page) -> bool:
    for sel in SELECTORS.next_page:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=2000):
                await loc.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                return True
        except Exception:
            continue
    return False


def _extract_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"(?:resume|candidate)[/_-]?(\w+)", url, re.I)
    return match.group(1) if match else None


def _normalize_url(base: str, href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http"):
        return href
    from urllib.parse import urljoin

    return urljoin(base, href)
