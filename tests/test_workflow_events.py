"""Tests for workflow event bus."""

from packages.workflow_events import clear_workflow, emit, get_events, workflow_context


def test_emit_and_buffer():
    clear_workflow("wf_test")
    emit("info", "hello", workflow_id="wf_test", category="system")
    emit("success", "done", workflow_id="wf_test", category="extract")
    events = get_events("wf_test")
    assert len(events) == 2
    assert events[0]["message"] == "hello"
    assert events[1]["level"] == "success"


def test_workflow_context():
    clear_workflow("wf_ctx")
    with workflow_context("wf_ctx"):
        emit("info", "in context", category="search")
    events = get_events("wf_ctx")
    assert len(events) == 1
    assert events[0]["category"] == "search"


def test_since_id_filter():
    clear_workflow("wf_since")
    for i in range(3):
        emit("info", f"msg{i}", workflow_id="wf_since")
    all_events = get_events("wf_since")
    assert len(all_events) == 3
    filtered = get_events("wf_since", since_id=1)
    assert len(filtered) == 2
    assert filtered[0]["message"] == "msg1"


def test_events_persist_to_default_data_dir_without_personal_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("HRAGENT_PERSONAL_MODE", raising=False)
    monkeypatch.delenv("HRAGENT_EVENT_LOG_DIR", raising=False)
    monkeypatch.setenv("HRAGENT_DATA_DIR", str(tmp_path / "data"))
    clear_workflow("wf_default_log")

    emit("info", "dev mode log", workflow_id="wf_default_log", category="system")
    clear_workflow("wf_default_log", clear_persisted=False)

    recovered = get_events("wf_default_log")
    assert [event["message"] for event in recovered] == ["dev mode log"]


def test_workflow_log_summary_from_persisted_events(monkeypatch, tmp_path):
    monkeypatch.setenv("HRAGENT_EVENT_LOG_DIR", str(tmp_path))
    clear_workflow("wf_summary")

    emit("info", "started", workflow_id="wf_summary", category="system")
    emit("success", "screening done", workflow_id="wf_summary", category="screen")

    from packages.workflow_events import get_workflow_log_summary

    summary = get_workflow_log_summary("wf_summary")
    assert summary["event_count"] == 2
    assert summary["last_message"] == "screening done"
    assert summary["last_level"] == "success"
    assert summary["persisted"] is True


def test_events_recover_from_persisted_log_after_memory_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("HRAGENT_EVENT_LOG_DIR", str(tmp_path))
    clear_workflow("wf_persist")

    emit("info", "first persisted", workflow_id="wf_persist", category="system")
    emit("success", "second persisted", workflow_id="wf_persist", category="screen")
    clear_workflow("wf_persist", clear_persisted=False)

    recovered = get_events("wf_persist")
    assert [event["message"] for event in recovered] == ["first persisted", "second persisted"]
    assert recovered[0]["id"] == 1
    assert recovered[1]["id"] == 2
