from __future__ import annotations

import pytest
from fastapi import HTTPException

from packages.runtime_config import (
    apply_runtime_config_to_env,
    default_config_path,
    runtime_config_status,
    save_runtime_config,
)
from packages.runtime_guards import require_hr_identity_for_im, require_task_start
from packages.settings import get_settings, reload_settings


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("HRAGENT_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("HR_COMPANY_NAME", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_runtime_config_roundtrip():
    save_runtime_config({"deepseek_api_key": "test-key-1234", "hr_company_name": "Example HR"})
    apply_runtime_config_to_env()
    reload_settings()
    status = runtime_config_status()
    assert status["deepseek_configured"] is True
    assert status["hr_company_name"] == "Example HR"
    assert status["deepseek_api_key_masked"].endswith("1234")
    assert "test-key" not in status["deepseek_api_key_masked"]
    require_task_start()
    require_hr_identity_for_im()


def test_legacy_license_flags_cannot_block_task_start(monkeypatch):
    monkeypatch.setenv("HRAGENT_PERSONAL_MODE", "1")
    monkeypatch.setenv("HRAGENT_LICENSE_REQUIRED", "1")
    monkeypatch.setenv("HRAGENT_LICENSE_CACHE", "/nonexistent/license.cache")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    reload_settings()
    require_task_start()


def test_task_start_still_requires_model_key():
    with pytest.raises(HTTPException) as exc:
        require_task_start()
    assert exc.value.status_code == 403
    assert exc.value.detail["reason"] == "deepseek_not_configured"


def test_im_identity_guard_blocks_when_empty():
    save_runtime_config({"hr_company_name": ""})
    with pytest.raises(HTTPException) as exc:
        require_hr_identity_for_im()
    assert exc.value.status_code == 403
    assert exc.value.detail["reason"] == "hr_identity_not_configured"


def test_default_config_uses_data_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("HRAGENT_CONFIG_PATH")
    monkeypatch.setenv("HRAGENT_DATA_DIR", str(tmp_path))
    assert default_config_path() == tmp_path / "config" / "runtime.json"


def test_explicit_legacy_config_is_preserved(monkeypatch, tmp_path):
    path = tmp_path / "existing" / "config.json"
    save_runtime_config({"hr_company_name": "Existing HR"}, path)
    monkeypatch.setenv("HRAGENT_CONFIG_PATH", str(path))
    assert runtime_config_status()["hr_company_name"] == "Existing HR"
    require_hr_identity_for_im()


def test_runtime_status_reads_settings_from_dotenv(monkeypatch, tmp_path):
    from packages.settings import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=test-env-key\nHR_COMPANY_NAME=Example HR\n")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.delenv("HR_COMPANY_NAME")
    settings = Settings(_env_file=env_file)
    monkeypatch.setattr("packages.runtime_config.get_settings", lambda: settings)
    assert runtime_config_status()["deepseek_configured"] is True
    assert runtime_config_status()["hr_identity_configured"] is True
