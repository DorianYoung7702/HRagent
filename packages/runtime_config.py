from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from packages.settings import get_settings


def default_config_path() -> Path:
    explicit = os.environ.get("HRAGENT_CONFIG_PATH")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("HRAGENT_DATA_DIR") or "data") / "config" / "runtime.json"


def load_runtime_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else default_config_path()
    if not cfg_path.exists():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_runtime_config(payload: dict[str, Any], path: str | Path | None = None) -> Path:
    cfg_path = Path(path) if path else default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_runtime_config(cfg_path)
    existing.update(payload)
    cfg_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg_path


def apply_runtime_config_to_env(path: str | Path | None = None) -> dict[str, Any]:
    """Merge persisted operator config into process env before settings reload."""
    cfg = load_runtime_config(path)
    if "deepseek_api_key" in cfg:
        os.environ["DEEPSEEK_API_KEY"] = str(cfg.get("deepseek_api_key") or "")
    if "hr_company_name" in cfg:
        os.environ["HR_COMPANY_NAME"] = str(cfg.get("hr_company_name") or "")
    if "deepseek_model" in cfg:
        os.environ["DEEPSEEK_MODEL"] = str(cfg.get("deepseek_model") or "")
    return cfg


def runtime_config_status(path: str | Path | None = None) -> dict[str, Any]:
    cfg = load_runtime_config(path)
    settings = get_settings()
    api_key = str(
        cfg["deepseek_api_key"] if "deepseek_api_key" in cfg else settings.deepseek_api_key
    ).strip()
    company = str(
        cfg["hr_company_name"] if "hr_company_name" in cfg else settings.hr_company_name
    ).strip()
    preference_memory = cfg.get("default_hr_preference_memory")
    if not isinstance(preference_memory, dict):
        preference_memory = None
    job_qa_profile = cfg.get("default_job_qa_profile")
    if not isinstance(job_qa_profile, dict):
        job_qa_profile = {}
    masked_key = ""
    if api_key:
        masked_key = f"{'*' * max(0, len(api_key) - 4)}{api_key[-4:]}"
    return {
        "deepseek_configured": bool(api_key),
        "deepseek_api_key_masked": masked_key,
        "hr_company_name": company,
        "hr_identity_configured": bool(company),
        "deepseek_model": str(
            cfg["deepseek_model"] if "deepseek_model" in cfg else settings.deepseek_model
        ),
        "default_screening_criteria": str(cfg.get("default_screening_criteria") or ""),
        "default_chat_job_title": str(cfg.get("default_chat_job_title") or ""),
        "default_collect_parent_group": str(cfg.get("default_collect_parent_group") or ""),
        "default_hr_preference_memory": preference_memory,
        "default_job_qa_profile": job_qa_profile,
    }
