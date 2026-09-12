import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from packages.settings import Settings


def test_default_database_is_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite+aiosqlite:///./data/recruiting.db"
    assert "license_server_url" not in Settings.model_fields


@pytest.mark.asyncio
async def test_first_start_creates_database_parent(tmp_path, monkeypatch):
    from packages.db import session

    database = tmp_path / "new" / "data" / "recruiting.db"
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    engine = create_async_engine(url)
    monkeypatch.setattr(session, "engine", engine)
    monkeypatch.setattr(session, "settings", SimpleNamespace(database_url=url))
    try:
        await session.init_db()
        assert database.is_file()
        async with engine.connect() as connection:
            assert (await connection.execute(text("PRAGMA integrity_check"))).scalar() == "ok"
            assert (await connection.execute(text(
                "SELECT name FROM sqlite_master WHERE name='recruiting_workflows'"
            ))).scalar() == "recruiting_workflows"
    finally:
        await engine.dispose()


def test_api_lifespan_starts_without_product_activation(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(root),
        "DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'new' / 'app.db').as_posix()}",
        "HRAGENT_DATA_DIR": str(tmp_path / "data"),
        "HRAGENT_CONFIG_PATH": str(tmp_path / "data" / "runtime.json"),
        "HRAGENT_EVENT_LOG_DIR": str(tmp_path / "logs"),
        "BROWSER_PROFILE_DIR": str(tmp_path / "browser_profiles" / "hr_default"),
        "HRAGENT_CONSOLE_DIST": str(root / "apps" / "console-web" / "dist"),
        "HRAGENT_TALENT_ARCHIVE_ENABLED": "0",
        "HRAGENT_LICENSE_REQUIRED": "1",
        "HRAGENT_PERSONAL_MODE": "1",
        "LICENSE_SERVER_URL": "http://127.0.0.1:1",
        "DEEPSEEK_API_KEY": "",
        "HR_COMPANY_NAME": "",
    }
    code = '''
from fastapi.testclient import TestClient
from apps.api.main import app
with TestClient(app) as client:
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/').status_code == 200
    assert client.get('/settings/runtime').json()['deepseek_configured'] is False
    assert 'license' not in client.get('/system/diagnostics').json()
    assert not any(p.startswith('/license') for p in app.openapi()['paths'])
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr
