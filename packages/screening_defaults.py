"""Fictional examples; configure criteria for the actual vacancy before screening."""

from typing import TypedDict


class JobPreset(TypedDict):
    id: str
    label: str
    search_requirement: str
    screening_criteria: str
    followup_question: str


JOB_PRESETS: list[JobPreset] = [
    {
        "id": "example_python_developer",
        "label": "Python 开发工程师（示例）",
        "search_requirement": "Python 开发工程师，2年以上开发经验，处理20份简历",
        "screening_criteria": """岗位：Python 开发工程师（虚构示例，请按实际岗位修改）

## 必备
1. 有 Python 服务端项目开发经验
2. 能说明自己在项目中的职责与技术方案

## 快速淘汰
1. 明确表示不考虑软件开发岗位

## 加分
1. 有自动化测试、数据库或 API 设计经验

## 追问
1. 项目职责不明确时，确认个人负责的模块和交付成果

## 初筛结论规则
- 证据满足岗位要求：观察
- 信息不足，需要确认：追问
- 有明确不匹配证据：排除""",
        "followup_question": "方便补充您在最近一个项目中负责的模块和交付成果吗？",
    },
]
DEFAULT_PRESET_ID = JOB_PRESETS[0]["id"]
DEFAULT_JOB_NAME = JOB_PRESETS[0]["label"]
DEFAULT_SEARCH_REQUIREMENT = JOB_PRESETS[0]["search_requirement"]
DEFAULT_SCREENING_CRITERIA = JOB_PRESETS[0]["screening_criteria"]
DEFAULT_FOLLOWUP_QUESTION = JOB_PRESETS[0]["followup_question"]


def get_job_preset(preset_id: str) -> JobPreset | None:
    return next((preset for preset in JOB_PRESETS if preset["id"] == preset_id), None)


def resolve_screening_criteria(criteria: str | None) -> str:
    return (criteria or "").strip() or DEFAULT_SCREENING_CRITERIA
