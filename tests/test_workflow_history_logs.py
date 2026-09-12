from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_list_response_includes_log_summary():
    source = (ROOT / "apps/api/routes/workflows.py").read_text(encoding="utf-8")
    schema = (ROOT / "packages/schemas/workflow.py").read_text(encoding="utf-8")

    assert "get_workflow_log_summary" in source
    assert "log_summary" in schema


def test_history_panel_shows_bound_log_preview():
    source = (ROOT / "apps/console-web/src/App.vue").read_text(encoding="utf-8")

    assert "historyLogPreview" in source
    assert "log_summary" in source
    assert "history-log" in source
