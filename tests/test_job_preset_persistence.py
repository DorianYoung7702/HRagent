from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_persists_full_preset_snapshot_after_start():
    source = (ROOT / "apps/console-web/src/App.vue").read_text(encoding="utf-8")

    assert "persistJobPreset" in source
    assert "if (inputs.preset_id)" in source
    assert "wizardState: inputs.wizard_state" in source
    assert "inputMode: inputs.input_mode" in source
    assert "preferenceResult.saveToPreset" not in source


def test_search_form_restores_and_syncs_preset_fields():
    source = (ROOT / "apps/console-web/src/components/SearchForm.vue").read_text(encoding="utf-8")

    assert "wizardState: preset.wizardState" in source
    assert "buildActivePresetSnapshot" in source
    assert "syncActivePresetFromForm" in source
    assert "persistActivePresetFields" in source
    assert "resolvePositionName" in source
    assert "commitPresetRename" in source
    assert "startPresetRename" in source
    assert "chat_job_title: positionNameValue" in source
    assert "collect_parent_group: collectFolderValue" in source
    assert "resolvePresetPositionName" in source
    assert "watch(" in source and "wizard," in source


def test_job_preset_schema_supports_wizard_snapshot():
    defaults = (ROOT / "apps/console-web/src/defaults.ts").read_text(encoding="utf-8")
    wizard = (ROOT / "apps/console-web/src/utils/requirementWizard.ts").read_text(encoding="utf-8")

    assert "wizardState?" in defaults
    assert "inputMode?" in defaults
    assert "input.wizardState" in wizard
