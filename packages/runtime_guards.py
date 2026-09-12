"""Configuration checks for model calls and candidate-facing messages."""

from fastapi import HTTPException

from packages.runtime_config import runtime_config_status
from packages.settings import get_settings


def require_task_start() -> None:
    if get_settings().deepseek_api_key.strip():
        return
    raise HTTPException(
        status_code=403,
        detail={
            "reason": "deepseek_not_configured",
            "message": "请先配置 DeepSeek API Key",
        },
    )


def require_hr_identity_for_im() -> None:
    if runtime_config_status()["hr_identity_configured"]:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "reason": "hr_identity_not_configured",
            "message": "请先设置招聘方身份/公司名后再使用 IM 功能",
        },
    )
