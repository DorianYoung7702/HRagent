"""辅助发现猎聘 IM 中心 /chat/im 页面选择器（需已登录 LPT）。"""

import asyncio
import sys

from services.fetch_worker.browser import BrowserManager
from services.fetch_worker.im_chat_runner import (
    _list_contact_texts,
    click_initiated_tab,
    enable_unread_filter,
    navigate_to_im_center,
)


async def main() -> None:
    browser = BrowserManager()
    try:
        page = await browser.new_page()
        await navigate_to_im_center(page)
        await click_initiated_tab(page)
        contacts = await _list_contact_texts(page)
        print(f"我发起的 列表项 ({len(contacts)}):", flush=True)
        for idx, text in contacts[:10]:
            print(f"  [{idx}] {text[:120]}", flush=True)
        await enable_unread_filter(page)
        unread = await _list_contact_texts(page)
        print(f"未读筛选后 ({len(unread)}):", flush=True)
        for idx, text in unread[:10]:
            print(f"  [{idx}] {text[:120]}", flush=True)
    finally:
        await browser.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
