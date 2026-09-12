"""猎聘 IM 中心 /chat/im 页面选择器与 DOM 辅助。"""

IM_URL = "https://lpt.liepin.com/chat/im"

IM_TAB_INITIATED = ["我发起的", "我发起"]
IM_TAB_UNREAD = ["未读"]
IM_SEND_LABELS = ["发送", "发 送"]

# Playwright 文本 / 结构选择器
IM_CONTACT_ITEM = [
    "[class*='contact-list'] [class*='item']",
    "[class*='session-list'] [class*='item']",
    "[class*='chat-list'] li",
    "[class*='conversation-list'] > div",
]

IM_CHAT_INPUT = [
    "textarea[placeholder*='请输入']",
    "textarea[placeholder*='消息']",
    "textarea[placeholder*='沟通']",
    "[class*='chat-input'] textarea",
    "[class*='im-input'] textarea",
    "[contenteditable='true']",
]

IM_SEND_BUTTON = [
    "button:has-text('发送')",
    "[class*='send-btn']",
    "button[class*='Send']",
]

IM_MESSAGE_INBOUND = [
    "[class*='message-item'][class*='other']",
    "[class*='msg-item']:not([class*='self'])",
    "[class*='chat-message'][class*='left']",
]


def build_im_contact_key(
    display_name: str | None,
    current_title: str | None = None,
    *,
    age: str | None = None,
    school: str | None = None,
    education: str | None = None,
) -> str:
    from services.fetch_worker.im_contact_match import build_im_contact_key as _build

    return _build(
        display_name,
        age=age,
        school=school,
        education=education,
        current_title=current_title,
    )
