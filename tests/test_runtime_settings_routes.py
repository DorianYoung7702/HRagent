from fastapi.testclient import TestClient
import pytest

from apps.api.main import app
from packages.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("HRAGENT_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("HR_COMPANY_NAME", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_runtime_settings_roundtrip(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("HRAGENT_PERSONAL_MODE", "1")
    monkeypatch.setenv("HRAGENT_CONFIG_PATH", str(cfg_path))

    client = TestClient(app)
    res = client.get("/settings/runtime")
    assert res.status_code == 200
    body = res.json()
    assert "personal_mode" not in body
    assert body["deepseek_configured"] is False

    put = client.put(
        "/settings/runtime",
        json={
            "deepseek_api_key": "sk-test-1234",
            "hr_company_name": "Acme HR",
        },
    )
    assert put.status_code == 200
    updated = put.json()
    assert updated["deepseek_configured"] is True
    assert updated["hr_identity_configured"] is True
    assert "1234" in updated["deepseek_api_key_masked"]
    assert "sk-test" not in updated["deepseek_api_key_masked"]


def test_runtime_settings_can_be_saved_outside_personal_mode(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.delenv("HRAGENT_PERSONAL_MODE", raising=False)
    monkeypatch.setenv("HRAGENT_CONFIG_PATH", str(cfg_path))

    client = TestClient(app)
    put = client.put("/settings/runtime", json={"deepseek_api_key": "sk-container-5678"})

    assert put.status_code == 200
    assert put.json()["deepseek_configured"] is True
    assert put.json()["deepseek_api_key_masked"].endswith("5678")


def test_runtime_settings_persists_user_recruiting_defaults(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("HRAGENT_PERSONAL_MODE", "1")
    monkeypatch.setenv("HRAGENT_CONFIG_PATH", str(cfg_path))

    client = TestClient(app)
    put = client.put(
        "/settings/runtime",
        json={
            "default_screening_criteria": "MUST: US visa",
            "default_chat_job_title": "Latam sales manager",
            "default_collect_parent_group": "Latam Sales Shenzhen",
            "default_hr_preference_memory": {
                "must_have": ["US visa"],
                "nice_to_have": [],
                "reject_rules": [],
                "followup_questions": [],
                "preference_summary": "Visa required",
                "screening_criteria": "MUST: US visa",
                "assistant_message": "",
                "ready": True,
                "criteria_version": 2,
            },
            "default_job_qa_profile": {
                "salary_range": "15-25K",
                "work_location": "Shenzhen",
            },
        },
    )

    assert put.status_code == 200
    updated = put.json()
    assert updated["default_screening_criteria"] == "MUST: US visa"
    assert updated["default_chat_job_title"] == "Latam sales manager"
    assert updated["default_collect_parent_group"] == "Latam Sales Shenzhen"
    assert updated["default_hr_preference_memory"]["must_have"] == ["US visa"]
    assert updated["default_job_qa_profile"]["salary_range"] == "15-25K"

    loaded = client.get("/settings/runtime").json()
    assert loaded["default_chat_job_title"] == "Latam sales manager"
    assert loaded["default_collect_parent_group"] == "Latam Sales Shenzhen"
    assert loaded["default_hr_preference_memory"]["criteria_version"] == 2
