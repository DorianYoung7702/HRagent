"""一次性登录猎聘 LPT，持久化 browser profile。"""

import asyncio
import logging

from services.fetch_worker.browser import BrowserManager
from services.fetch_worker.lpt_adapter import LPT_SEARCH_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    print("=" * 60)
    print("猎聘 LPT 登录向导")
    print("=" * 60)
    print(f"1. 将打开浏览器并导航到: {LPT_SEARCH_URL}")
    print("2. 请在浏览器中手动登录猎聘企业账号")
    print("3. 登录成功后，确认能看到「搜索人才」页面")
    print("4. 回到终端按 Enter 关闭浏览器，登录态将保存到 data/browser_profiles/hr_default")
    print("=" * 60)

    browser = BrowserManager(profile_name="hr_default")
    try:
        page = await browser.new_page()
        await page.goto(LPT_SEARCH_URL, wait_until="domcontentloaded")
        input("\n登录完成后按 Enter 关闭浏览器...")
    finally:
        await browser.close()
    print("登录态已保存。后续抓取将自动复用此 profile。")


if __name__ == "__main__":
    asyncio.run(main())
