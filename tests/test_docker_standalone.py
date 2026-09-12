from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_standalone_image_builds_console_and_playwright_runtime():
    dockerfile = (ROOT / "infra" / "Dockerfile.standalone").read_text(encoding="utf-8")

    assert "node:22-bookworm-slim AS console-build" in dockerfile
    assert "npm ci" in dockerfile
    assert "registry.npmjs.org" in dockerfile
    assert "mcr.microsoft.com/playwright/python:v1.49.0-noble" in dockerfile
    assert "constraints.docker.txt" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "DATABASE_URL=sqlite+aiosqlite:////data/recruiting.db" in dockerfile
    assert "HRAGENT_FORCE_HEADLESS=1" in dockerfile
    assert "https://pypi.org/simple" in dockerfile
    assert "COPY --from=console-build" in dockerfile
    assert "USER hragent" in dockerfile
    assert "HRAGENT_LICENSE" not in dockerfile


def test_standalone_compose_persists_sqlite_and_forces_headless():
    compose = (ROOT / "infra" / "docker-compose.standalone.yml").read_text(encoding="utf-8")

    assert "sqlite+aiosqlite:////data/recruiting.db" in compose
    assert "BROWSER_PROFILE_DIR: /data/browser_profiles/hr_default" in compose
    assert 'HRAGENT_FORCE_HEADLESS: "1"' in compose
    assert "hragent_data:/data" in compose
    assert "/health" in compose
    assert "HRAGENT_LICENSE" not in compose


def test_standalone_deployment_documents_linux_profile_boundary():
    guide = (ROOT / "docs" / "DOCKER_STANDALONE.md").read_text(encoding="utf-8")

    assert "Windows" in guide
    assert "VNC" in guide
