from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app


def test_license_endpoints_are_removed(monkeypatch, tmp_path):
    monkeypatch.setenv("HRAGENT_LICENSE_CACHE", str(tmp_path / "license.cache"))
    client = TestClient(app)

    assert client.get("/license/status").status_code == 404
    # The optional SPA mount rejects POST with 405; neither response is an activation API.
    assert client.post("/license/activate", json={"license_key": "unused"}).status_code in (404, 405)
    assert not any(path.startswith("/license") for path in app.openapi()["paths"])


def test_system_diagnostics_route_excludes_sensitive_data(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{(tmp_path / 'missing.db').as_posix()}",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    client = TestClient(app)

    res = client.get("/system/diagnostics")

    assert res.status_code == 200
    rendered = repr(res.json())
    assert "license" not in res.json()
    assert "secret-key" not in rendered
    assert "raw_text" not in rendered
    assert "message_text" not in rendered
