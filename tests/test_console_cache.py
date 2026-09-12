from __future__ import annotations

import re

from fastapi.testclient import TestClient

from apps.api.main import app


def test_console_index_disables_browser_cache():
    client = TestClient(app)

    res = client.get("/")

    assert res.status_code == 200
    assert "no-store" in res.headers["cache-control"]
    assert res.headers["pragma"] == "no-cache"
    assert res.headers["expires"] == "0"


def test_console_hashed_assets_are_immutable_when_available():
    client = TestClient(app)
    index = client.get("/")
    asset_match = re.search(r'src="(/assets/[^"]+\.js)"', index.text)
    assert asset_match is not None

    res = client.get(asset_match.group(1))

    assert res.status_code == 200
    assert "immutable" in res.headers["cache-control"]
