"""猎聘 LPT 企业版 selector 配置。"""

from dataclasses import dataclass, field

from packages.schemas.workflow import LptEducationFilters, LptOtherFilters

LPT_SEARCH_URL = "https://lpt.liepin.com/search"

# 左侧菜单
LPT_MENU_SEARCH_TALENT = ["搜索人才", "搜人才", "人才搜索"]

LPT_UNLIMITED_JOB_ANCHOR = "不限职位"

# 搜索栏（填关键词）— 紧挨「不限职位」组件右侧的输入框
LPT_SEARCH_BAR_LABELS = ["任意关键词", "搜索栏", "关键词"]
LPT_JOB_FIELD_LABELS = ["职位名称", "职位", "当前职位"]

LPT_SEARCH_BAR_INPUT = [
    "input[placeholder*='任意关键词']",
    "input[placeholder*='搜索内容']",
    "input[placeholder*='搜人才']",
    "input[placeholder*='搜简历']",
    "[class*='keyword'] input[type='text']",
    "[class*='Keyword'] input",
    "[class*='search-bar'] input",
    "[class*='searchBar'] input",
]

# 旧名兼容
LPT_KEYWORD_INPUT = LPT_SEARCH_BAR_INPUT

# 需跳过的职位/岗位输入框
LPT_JOB_TITLE_INPUT_MARKERS = ["职位名称", "职位", "岗位", "职 位", "job", "title"]

# 兼容旧配置
LPT_SEARCH_INPUT = [
    "input[placeholder*='任意关键词']",
    "input[placeholder*='关键词']",
    "input[placeholder*='关键字']",
]

# 搜索按钮
LPT_SEARCH_BUTTON = [
    "button:has-text('搜索')",
    "[class*='search-btn']",
    "button[type='submit']",
    ".search-button",
]

# 筛选栏城市项
LPT_FILTER_EXPECT_CITY = "期望城市"
LPT_FILTER_CITY = LPT_FILTER_EXPECT_CITY  # 兼容旧名
LPT_FILTER_CURRENT_CITY = ["目前城市", "当前城市", "现居城市"]
LPT_FILTER_CITY_WRONG = ("目标城市", "目前城市", "现居城市")  # 点期望城市时需避开的标签

# 期望/目前城市 → 其他 → 城市卡片
LPT_CITY_OTHER_LABELS = ["其他", "其它", "更多城市"]
LPT_CITY_PICKER_TABS = ["历史/热门", "热门", "历史", "热门城市"]
LPT_CITY_CONFIRM_BUTTONS = ["确定", "确认", "完成"]
LPT_CITY_PICKER_CONTAINER = [
    "[role='dialog']",
    "[class*='city-picker']",
    "[class*='CityPicker']",
    "[class*='city-select']",
]

MAX_LPT_CITIES = 5

# 直辖市：需再点「全北京 / 全上海」等
LPT_MUNICIPALITY_CITIES = frozenset({"北京", "上海", "天津", "重庆"})
LPT_CITY_WHOLE_SUFFIX = "全"  # 全北京 = 全 + 北京

LPT_KNOWN_CITIES = [
    "深圳", "北京", "上海", "广州", "杭州", "成都", "南京", "武汉",
    "苏州", "东莞", "佛山", "厦门", "青岛", "西安", "重庆", "天津",
    "惠州", "中山", "珠海", "宁波", "无锡", "常州", "温州", "长沙",
    "郑州", "合肥", "昆明", "南宁", "石家庄", "太原", "济南", "福州",
    "南昌", "贵阳", "兰州", "海口", "大连", "沈阳", "哈尔滨", "长春",
]

# 筛选标签 - 工作经验
LPT_FILTER_EXP_LABEL = ["工作经验", "工作年限", "经验要求"]

# 教育经历行
LPT_FILTER_EDU_ROW = ["教育经历", "学历"]
LPT_FILTER_SCHOOL_TIER = "院校要求"
LPT_DEGREE_OPTIONS = [
    "不限",
    "大专",
    "本科",
    "硕士",
    "MBA/EMBA",
    "博士",
]
LPT_SCHOOL_TIER_OPTIONS = ["985", "211", "双一流", "海外留学"]

# 其他筛选行
LPT_FILTER_OTHER_ROW = ["其他筛选", "更多筛选"]
LPT_OTHER_FILTER_LABELS: dict[str, list[str]] = {
    "activity": ["活跃状态", "活跃度"],
    "job_seeking": ["求职状态"],
    "job_hop": ["跳槽频率"],
    "age": ["年龄要求", "年龄"],
    "gender": ["性别要求", "性别"],
    "language": ["语言要求", "语言"],
    "grad_industry": ["毕业行业"],
    "current_industry": ["当前行业"],
    "expected_industry": ["期望行业"],
}
LPT_OTHER_FILTER_OPTIONS: dict[str, list[str]] = {
    "activity": [
        "不限",
        "今日活跃",
        "3日内活跃",
        "7日内活跃",
        "30日内活跃",
        "最近活跃",
    ],
    "job_seeking": [
        "不限",
        "在职，看看新机会",
        "在职，急寻新工作",
        "在职，暂无跳槽打算",
        "离职，正在找工作",
        "离职，看看新机会",
        "应届毕业生",
    ],
    "job_hop": [
        "不限",
        "5年少于3份",
        "5年3-4份",
        "5年4份以上",
        "平均每份大于1年",
    ],
    "age": [
        "不限",
        "20-25",
        "25-30",
        "30-35",
        "35-40",
        "40-50",
        "50以上",
    ],
    "gender": ["不限", "男", "女"],
    "language": [
        "不限",
        "英语",
        "日语",
        "法语",
        "德语",
        "西班牙语",
        "韩语",
        "俄语",
        "阿拉伯语",
        "葡萄牙语",
    ],
    "grad_industry": [],  # 行业类：解析为关键词，打开面板搜索匹配
    "current_industry": [],
    "expected_industry": [],
}

# 搜索结果底部分页（1 2 3 … ›）
LPT_PAGINATION_NEXT = [
    ".ant-pagination-next:not(.ant-pagination-disabled)",
    "li.ant-pagination-next:not(.ant-pagination-disabled)",
    "[class*='pagination-next']:not([class*='disabled'])",
    "[class*='Pagination-next']:not([class*='disabled'])",
    "button:has-text('下一页')",
    "a:has-text('下一页')",
    ".ant-pagination >> text=›",
    ".ant-pagination >> text=>",
]

# 简历卡片（搜索结果列表）
LPT_RESUME_CARD = [
    "[class*='resume-card']",
    "[class*='ResumeCard']",
    "[class*='candidate-card']",
    "[class*='talent-card']",
    "[class*='search-result'] [class*='card']",
    "[class*='resume-list'] > div",
    "[class*='resume-list'] li",
    "[class*='result-list'] > div",
]

# 在线简历弹窗
LPT_POPUP_CONTAINER = [
    "[role='dialog']",
    "[class*='modal']:visible",
    "[class*='drawer']:visible",
    "[class*='popup']:visible",
    "[class*='resume-detail']:visible",
    "[class*='ResumeDetail']:visible",
    "[class*='online-resume']:visible",
]

LPT_POPUP_CLOSE = [
    "[class*='close']",
    "[aria-label='Close']",
    "button:has-text('关闭')",
    "[class*='modal'] [class*='close']",
]

# 浮层「退出/返回」— 开聊后通常需连点两级才回列表
LPT_EXIT_BUTTONS = [
    "button:has-text('退出')",
    "a:has-text('退出')",
    "text=退出",
    "button:has-text('返回')",
    "a:has-text('返回')",
    "[class*='back-btn']",
    "[class*='Back']",
]

# 点击「收藏」后弹出的「收藏简历」分组弹窗（分组列表内选岗位名称文件夹）
LPT_COLLECT_FOLDER_MODAL = [
    "[role='dialog']:has-text('收藏简历')",
    "div:has-text('收藏简历'):has-text('分组列表')",
]

LPT_COLLECT_FOLDER_ITEMS = {
    "追问": ("追问", r"^追问\(\d+\)$"),
    "观察": ("观察", r"^观察\(\d+\)$"),
}

# 简历库：点击分组标签后，右侧出现收藏候选人列表
LPT_TALENT_MGMT_SIDEBAR = ("人才管理",)
LPT_RESUME_LIBRARY_TOP_TAB = ("简历库",)
LPT_RESUME_LIBRARY_TOP_TAB_SELECTORS = (
    ".ant-tabs-tab:has-text('简历库')",
    "[role='tab']:has-text('简历库')",
    ".ant-tabs-nav >> text=简历库",
    "a:has-text('简历库')",
)
LPT_RESUME_LIBRARY_FOLDERS = ()  # 侧栏按岗位名分组；观察/追问仅作系统 metadata
LPT_RESUME_LIBRARY_TABLE_HEADERS = ("姓名", "性别", "年龄", "学历", "目前职位", "目前公司", "收藏时间")
# 追问分组在页面上可能显示为「候选」
LPT_RESUME_LIBRARY_TAB_LABELS: dict[str, list[str]] = {
    "观察": ["观察"],
    "追问": ["候选", "追问"],
}

# 弹窗/卡片内发起沟通（已沟通过时显示「继续沟通」）
LPT_CONTACT_NOW = [
    "button:has-text('立即沟通')",
    "a:has-text('立即沟通')",
    "button:has-text('继续沟通')",
    "a:has-text('继续沟通')",
    "span:has-text('立即沟通')",
    "span:has-text('继续沟通')",
    "div:has-text('立即沟通')",
    "div:has-text('继续沟通')",
    "[class*='contact']:has-text('立即沟通')",
    "[class*='contact']:has-text('继续沟通')",
    "text=立即沟通",
    "text=继续沟通",
    "button:has-text('立即开聊')",
    "a:has-text('立即开聊')",
    "[class*='contact']:has-text('立即开聊')",
    "text=立即开聊",
]

# 开聊后「选择岗位」最上层弹窗
LPT_JOB_SELECT_TEXT = [
    "选择开聊岗位",
    "选择开聊职位",
    "开聊职位",
    "选择岗位",
    "选择职位",
    "沟通职位",
    "开聊岗位",
    "请选择职位",
]

LPT_JOB_SELECT_CARD = [
    "[class*='job-card']",
    "[class*='JobCard']",
    "[class*='position-card']",
    "[class*='position-item']",
    "[class*='job-item']",
    "[class*='position-list'] > div",
    "[class*='position-list'] li",
    "[class*='job-list'] > div",
    "[class*='job-list'] li",
    "[class*='list'] [class*='item']",
    "[class*='card']",
    "li",
]

LPT_JOB_CONFIRM_BUTTONS = [
    "button:has-text('确认开聊')",
    "button:has-text('确认')",
    "button:has-text('确定')",
    "a:has-text('确认开聊')",
    "a:has-text('确认')",
    "a:has-text('确定')",
    "text=确认开聊",
    "text=确认",
    "text=确定",
]

# 在线简历右侧「收藏」（星标 + 文案）
LPT_COLLECT_BUTTONS = [
    "[class*='collect']",
    "[class*='Collect']",
    "[class*='favorite']",
    "[class*='Favorite']",
    "[class*='star']",
    "[title*='收藏']",
    "[aria-label*='收藏']",
    "button:has-text('收藏')",
    "a:has-text('收藏')",
    "div:has-text('收藏')",
    "span:has-text('收藏')",
    "text=收藏",
]

LPT_COLLECT_GOT_IT = [
    "button:has-text('知道了')",
    "button:has-text('我知道了')",
    "a:has-text('知道了')",
    "span:has-text('知道了')",
    "text=知道了",
    "text=我知道了",
]

# 初筛结论标签：仅写入 metadata，不再作为猎聘侧栏收藏/跳转目标
LPT_COLLECT_DECISION_TAGS = ("追问", "观察")

# 弹窗内简历 section 标题
LPT_SECTION_TITLES = [
    "工作经历",
    "项目经历",
    "教育经历",
    "技能标签",
    "求职意向",
    "个人优势",
    "自我评价",
    "语言能力",
    "证书",
]


@dataclass
class LptSearchParams:
    keywords: str = "西班牙语 美签 海外销售"
    city: str = "深圳"
    cities: list[str] = field(default_factory=list)
    current_cities: list[str] = field(default_factory=list)
    experience: str = "3-5年"
    education: LptEducationFilters = field(default_factory=LptEducationFilters)
    other_filters: LptOtherFilters = field(default_factory=LptOtherFilters)
    entry_url: str = LPT_SEARCH_URL

    def resolved_cities(self) -> list[str]:
        from services.fetch_worker.lpt_city_picker import normalize_city_list

        return normalize_city_list(self.city, self.cities)

    def resolved_current_cities(self) -> list[str]:
        from services.fetch_worker.lpt_city_picker import normalize_city_list_optional

        return normalize_city_list_optional(cities=self.current_cities)
