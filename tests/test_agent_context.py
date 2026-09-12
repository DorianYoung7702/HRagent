from packages.agent_context import (
    get_hr_company_name,
    hr_agent_system_prefix,
    hr_context_block,
)
from packages.settings import reload_settings


def test_default_company_is_generic(monkeypatch):
    monkeypatch.delenv("HRAGENT_PERSONAL_MODE", raising=False)
    monkeypatch.setenv("HR_COMPANY_NAME", "")
    reload_settings()
    assert get_hr_company_name() == "招聘团队"


def test_legacy_mode_flag_does_not_change_company_fallback(monkeypatch):
    monkeypatch.setenv("HRAGENT_PERSONAL_MODE", "1")
    monkeypatch.setenv("HR_COMPANY_NAME", "")
    reload_settings()
    assert get_hr_company_name() == "招聘团队"


def test_system_prefix_forbids_wrong_company(monkeypatch):
    monkeypatch.delenv("HRAGENT_PERSONAL_MODE", raising=False)
    monkeypatch.setenv("HR_COMPANY_NAME", "")
    reload_settings()
    text = hr_agent_system_prefix()
    assert "招聘团队" in text
    assert "严禁" in text


def test_context_block_includes_job(monkeypatch):
    monkeypatch.delenv("HRAGENT_PERSONAL_MODE", raising=False)
    monkeypatch.setenv("HR_COMPANY_NAME", "")
    reload_settings()
    block = hr_context_block(job_title="拉美中方销售")
    assert "招聘团队" in block
    assert "拉美中方销售" in block
