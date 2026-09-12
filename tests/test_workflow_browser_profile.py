"""Tests for per-workflow isolated Liepin browser profiles."""

from pathlib import Path

import pytest

from services.fetch_worker import workflow_browser_profile as wbp


@pytest.fixture
def browser_profiles_root(tmp_path, monkeypatch):
    root = tmp_path / "browser_profiles"
    root.mkdir()

    def profile_dir_for(name: str) -> Path:
        return root / name

    def profile_has_cache(name: str = "hr_default") -> bool:
        default = root / name / "Default"
        if not default.is_dir():
            return False
        markers = ("Cookies", "Local Storage", "Preferences", "Network")
        return any((default / marker).exists() for marker in markers)

    monkeypatch.setattr(wbp, "profile_dir_for", profile_dir_for)
    monkeypatch.setattr(wbp, "profile_has_cache", profile_has_cache)
    return root


def _seed_default_profile(root: Path) -> None:
    default = root / "hr_default" / "Default"
    default.mkdir(parents=True)
    (default / "Cookies").write_text("cookie-data", encoding="utf-8")
    (default / "Preferences").write_text("{}", encoding="utf-8")


def test_workflow_browser_profile_name():
    assert wbp.workflow_browser_profile_name("abc-123-def-456").startswith("wf_")
    assert len(wbp.workflow_browser_profile_name("abc-123-def-456")) <= 19


def test_ensure_workflow_browser_profile_clones_login(browser_profiles_root):
    _seed_default_profile(browser_profiles_root)
    wf_id = "workflow-test-001"
    profile = wbp.ensure_workflow_browser_profile(wf_id)
    assert profile == wbp.workflow_browser_profile_name(wf_id)
    dest = browser_profiles_root / profile / "Default" / "Cookies"
    assert dest.read_text(encoding="utf-8") == "cookie-data"


def test_ensure_workflow_browser_profile_reuses_existing(browser_profiles_root):
    _seed_default_profile(browser_profiles_root)
    wf_id = "workflow-test-002"
    first = wbp.ensure_workflow_browser_profile(wf_id)
    dest = browser_profiles_root / first / "Default" / "Cookies"
    dest.write_text("mutated", encoding="utf-8")
    second = wbp.ensure_workflow_browser_profile(wf_id)
    assert second == first
    assert dest.read_text(encoding="utf-8") == "mutated"


def test_ensure_workflow_browser_profile_requires_login(browser_profiles_root):
    with pytest.raises(ValueError, match="请先完成猎聘登录"):
        wbp.ensure_workflow_browser_profile("wf-no-login")


def test_cleanup_workflow_browser_profile(browser_profiles_root):
    _seed_default_profile(browser_profiles_root)
    wf_id = "workflow-test-003"
    profile = wbp.ensure_workflow_browser_profile(wf_id)
    assert (browser_profiles_root / profile).exists()
    wbp.cleanup_workflow_browser_profile(wf_id)
    assert not (browser_profiles_root / profile).exists()
