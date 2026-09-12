from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from packages.settings import get_settings, is_browser_headless


class BrowserManager:
    def __init__(self, profile_name: str = "hr_default"):
        self.settings = get_settings()
        self.profile_dir = Path(self.settings.browser_profile_dir).parent / profile_name
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self) -> BrowserContext:
        headless = is_browser_headless()
        self._playwright = await async_playwright().start()
        launch_kwargs: dict = {
            "user_data_dir": str(self.profile_dir),
            "headless": headless,
            "viewport": {"width": 1440, "height": 900},
            "locale": "zh-CN",
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if not headless:
            launch_kwargs["slow_mo"] = 200
        self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        return self._context

    async def new_page(self) -> Page:
        if not self._context:
            await self.start()
        assert self._context is not None
        page = await self._context.new_page()
        page.set_default_timeout(30000)
        return page

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
