from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_search_form_binds_job_qa_profile_to_active_preset_not_runtime_global():
    source = (ROOT / "apps/console-web/src/components/SearchForm.vue").read_text(
        encoding="utf-8"
    )

    assert "runtime.default_job_qa_profile" not in source
    assert "updateJobPreset" in source
    assert "watch(" in source and "jobQaProfile" in source
    assert "jobQaProfile: normalizeJobQaProfile(profile)" in source


def test_app_does_not_write_job_qa_profile_as_global_runtime_default():
    source = (ROOT / "apps/console-web/src/App.vue").read_text(encoding="utf-8")

    assert "default_job_qa_profile:" not in source
