"""猎聘平台 selector 配置与 fallback 链。"""

from dataclasses import dataclass, field


@dataclass
class LiepinSelectors:
    list_card: list[str] = field(default_factory=lambda: [
        ".resume-list li",
        "[class*='resume-card']",
        "[class*='candidate-item']",
        ".search-result-list .item",
        "div[class*='ResumeCard']",
    ])
    card_name: list[str] = field(default_factory=lambda: [
        ".name",
        "[class*='name']",
        "h3",
        ".title-name",
    ])
    card_title: list[str] = field(default_factory=lambda: [
        ".title",
        "[class*='job-title']",
        ".position",
    ])
    card_company: list[str] = field(default_factory=lambda: [
        ".company",
        "[class*='company']",
    ])
    card_link: list[str] = field(default_factory=lambda: [
        "a[href*='resume']",
        "a[href*='candidate']",
        "a",
    ])
    next_page: list[str] = field(default_factory=lambda: [
        ".ant-pagination-next:not(.ant-pagination-disabled)",
        "[class*='pagination'] .next:not(.disabled)",
        "button:has-text('下一页')",
        "a:has-text('下一页')",
    ])
    detail_sections: dict[str, list[str]] = field(default_factory=lambda: {
        "工作经历": [".work-experience", "[class*='work-exp']", "section:has-text('工作经历')"],
        "项目经历": [".project-experience", "[class*='project']", "section:has-text('项目经历')"],
        "教育经历": [".education", "[class*='edu']", "section:has-text('教育经历')"],
        "技能标签": [".skill-tag", "[class*='skill']", "section:has-text('技能')"],
        "求职意向": [".job-intention", "section:has-text('求职意向')"],
        "个人优势": [".advantage", "section:has-text('个人优势')", "section:has-text('自我评价')"],
    })
    detail_name: list[str] = field(default_factory=lambda: [
        ".resume-name",
        "[class*='user-name']",
        "h1",
        ".name",
    ])
    expand_buttons: list[str] = field(default_factory=lambda: [
        "text=展开",
        "text=查看更多",
        "text=查看全部",
        "[class*='expand']",
    ])
    chat_input: list[str] = field(default_factory=lambda: [
        "textarea[placeholder*='输入']",
        ".chat-input textarea",
        "[class*='message-input']",
        "div[contenteditable='true']",
    ])
    chat_send: list[str] = field(default_factory=lambda: [
        "button:has-text('发送')",
        ".send-btn",
        "[class*='send-button']",
    ])
    chat_list_item: list[str] = field(default_factory=lambda: [
        ".chat-list-item",
        "[class*='conversation-item']",
        ".message-list li",
    ])
    chat_message_inbound: list[str] = field(default_factory=lambda: [
        ".message-in",
        "[class*='msg-left']",
        "[class*='received']",
    ])


SELECTORS = LiepinSelectors()

SECTION_TITLES = [
    "工作经历",
    "项目经历",
    "教育经历",
    "技能标签",
    "求职意向",
    "个人优势",
    "自我评价",
]
