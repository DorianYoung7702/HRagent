import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./data/recruiting.db"
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "recruiting-task-queue"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout: float = 120.0
    deepseek_trust_env: bool = False  # False = ignore HTTP_PROXY, fix ConnectError via proxy

    redis_url: str = "redis://localhost:6379/0"
    browser_profile_dir: str = "./data/browser_profiles/hr_default"
    browser_headless: bool = True
    send_mode: str = "draft_first"

    api_host: str = "127.0.0.1"
    api_port: int = 8001
    api_base_url: str = "http://localhost:8001"
    reply_scan_interval_minutes: int = 5

    # 全局 Agent 招聘方身份（IM/追问等对外话术）
    hr_company_name: str = ""

    app_version: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Clear cached settings (e.g. after .env edit) and reload."""
    get_settings.cache_clear()
    return get_settings()


def is_browser_headless() -> bool:
    """Read headless flag at runtime (env var overrides cached settings)."""
    env_val = os.environ.get("BROWSER_HEADLESS")
    if env_val is not None:
        return env_val.strip().lower() not in ("false", "0", "no")
    return get_settings().browser_headless
