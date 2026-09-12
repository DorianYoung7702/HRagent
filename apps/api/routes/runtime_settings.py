from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from packages.runtime_config import (
    apply_runtime_config_to_env,
    runtime_config_status,
    save_runtime_config,
)
from packages.settings import reload_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class RuntimeConfigUpdate(BaseModel):
    deepseek_api_key: str | None = None
    hr_company_name: str | None = None
    deepseek_model: str | None = None
    default_screening_criteria: str | None = None
    default_chat_job_title: str | None = None
    default_collect_parent_group: str | None = None
    default_hr_preference_memory: dict[str, Any] | None = None
    default_job_qa_profile: dict[str, Any] | None = None


@router.get("/runtime")
async def get_runtime_settings():
    return runtime_config_status()


@router.put("/runtime")
async def update_runtime_settings(body: RuntimeConfigUpdate):
    payload: dict[str, Any] = {}
    if body.deepseek_api_key is not None:
        payload["deepseek_api_key"] = body.deepseek_api_key.strip()
    if body.hr_company_name is not None:
        payload["hr_company_name"] = body.hr_company_name.strip()
    if body.deepseek_model is not None:
        payload["deepseek_model"] = body.deepseek_model.strip()
    if body.default_screening_criteria is not None:
        payload["default_screening_criteria"] = body.default_screening_criteria.strip()
    if body.default_chat_job_title is not None:
        payload["default_chat_job_title"] = body.default_chat_job_title.strip()
    if body.default_collect_parent_group is not None:
        payload["default_collect_parent_group"] = body.default_collect_parent_group.strip()
    if body.default_hr_preference_memory is not None:
        payload["default_hr_preference_memory"] = body.default_hr_preference_memory
    if body.default_job_qa_profile is not None:
        payload["default_job_qa_profile"] = body.default_job_qa_profile

    save_runtime_config(payload)
    apply_runtime_config_to_env()
    reload_settings()
    return runtime_config_status()
