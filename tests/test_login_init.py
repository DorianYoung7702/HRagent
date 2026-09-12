"""Tests for Liepin login init helpers."""

from services.fetch_worker.login_init import clear_login_profile, profile_has_cache


def test_profile_has_cache_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_PROFILE_DIR", str(tmp_path / "hr_default"))
    from packages.settings import reload_settings

    reload_settings()
    assert profile_has_cache("hr_default") is False


def test_profile_has_cache_true_when_default_has_cookies(tmp_path, monkeypatch):
    profile = tmp_path / "hr_default"
    default = profile / "Default"
    default.mkdir(parents=True)
    (default / "Cookies").write_text("x", encoding="utf-8")
    monkeypatch.setenv("BROWSER_PROFILE_DIR", str(profile))
    from packages.settings import reload_settings

    reload_settings()
    assert profile_has_cache("hr_default") is True


def test_clear_login_profile_removes_cache(tmp_path, monkeypatch):
    profile = tmp_path / "hr_default"
    default = profile / "Default"
    default.mkdir(parents=True)
    (default / "Cookies").write_text("x", encoding="utf-8")
    monkeypatch.setenv("BROWSER_PROFILE_DIR", str(profile))
    from packages.settings import reload_settings

    reload_settings()
    assert profile_has_cache("hr_default") is True
    clear_login_profile("hr_default")
    assert profile_has_cache("hr_default") is False
