from scripts.check_public_release import inspect_file


def test_public_release_rejects_private_data_and_live_configuration():
    assert inspect_file(".env", b"MODEL_KEY=example")
    assert inspect_file("data/recruiting.db", b"")
    assert inspect_file(".pytest_case/result.db", b"")
    assert inspect_file("deliverables/report.pptx", b"")
    assert not inspect_file(".env.example", b"MODEL_KEY=your-own-key")
    assert not inspect_file("apps/api/main.py", b"print('example')")


def test_public_release_rejects_resumes_exports_and_browser_caches():
    for path in (
        "resume.PDF", "exports/candidates.csv", "exports/candidates.xlsx",
        "browser_profiles/default/Cookies", "logs/events.jsonl", "snapshot.har",
        "backups/config.json", "runtime/config.json", "license.cache",
    ):
        assert inspect_file(path, b""), path
    assert not inspect_file("data/.gitkeep", b"")
    assert not inspect_file("apps/console-web/public/logo.svg", b"<svg/>")


def test_talent_archive_is_opt_in(monkeypatch):
    from packages.talent_archive_policy import talent_archive_enabled

    monkeypatch.delenv("HRAGENT_TALENT_ARCHIVE_ENABLED", raising=False)
    assert not talent_archive_enabled()
    monkeypatch.setenv("HRAGENT_TALENT_ARCHIVE_ENABLED", "1")
    assert talent_archive_enabled()
