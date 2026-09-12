from enum import Enum

from playwright.async_api import Page


class PageType(str, Enum):
    LIST = "list"
    DETAIL = "detail"
    LOGIN = "login"
    PERMISSION = "permission"
    UNKNOWN = "unknown"


LOGIN_INDICATORS = [
    "text=登录",
    "text=扫码登录",
    "input[placeholder*='手机号']",
    "input[placeholder*='账号']",
    ".login-box",
    "#login",
]

LIST_INDICATORS = [
    ".resume-list",
    ".candidate-list",
    "[class*='resume-card']",
    "[class*='candidate-card']",
    ".search-result-list",
    "li[class*='resume']",
    "[class*='talent-card']",
    "[class*='ResumeCard']",
]

LPT_LOGGED_IN_INDICATORS = [
    "text=搜索人才",
    "text=期望城市",
    "text=人才管理",
    "[class*='sidebar']",
]

LPT_LOGIN_URL_PATTERNS = ["passport", "login", "signin"]

DETAIL_INDICATORS = [
    ".resume-detail",
    "[class*='resume-detail']",
    ".personal-info",
    "text=工作经历",
    "text=项目经历",
]


async def detect_page_type(page: Page) -> PageType:
    url = page.url.lower()

    if any(p in url for p in LPT_LOGIN_URL_PATTERNS):
        return PageType.LOGIN

    for selector in LOGIN_INDICATORS:
        try:
            if await page.locator(selector).first.is_visible(timeout=2000):
                # LPT 已登录页也可能含「登录」链接，需二次判断
                if "lpt.liepin.com" in url:
                    for logged_in in LPT_LOGGED_IN_INDICATORS:
                        try:
                            if await page.locator(logged_in).first.is_visible(timeout=1000):
                                break
                        except Exception:
                            continue
                    else:
                        return PageType.LOGIN
                else:
                    return PageType.LOGIN
        except Exception:
            continue

    if "permission" in url or "403" in url or "无权限" in await page.title():
        return PageType.PERMISSION

    for selector in DETAIL_INDICATORS:
        try:
            if await page.locator(selector).first.is_visible(timeout=2000):
                return PageType.DETAIL
        except Exception:
            continue

    for selector in LIST_INDICATORS:
        try:
            if await page.locator(selector).first.is_visible(timeout=2000):
                return PageType.LIST
        except Exception:
            continue

    body_text = await page.locator("body").inner_text()
    if "工作经历" in body_text and "项目经历" in body_text:
        return PageType.DETAIL
    if "简历" in body_text or "候选人" in body_text:
        return PageType.LIST

    return PageType.UNKNOWN


class PageDetectionError(Exception):
    def __init__(self, page_type: PageType, message: str):
        self.page_type = page_type
        super().__init__(message)
