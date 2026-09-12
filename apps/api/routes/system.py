from __future__ import annotations

import os
import platform
from pathlib import Path

from fastapi import APIRouter, HTTPException

from packages.db_maintenance import (
    backup_sqlite_database,
    collect_sanitized_diagnostics,
    compact_sqlite_database,
    export_diagnostics_zip,
)
from packages.settings import get_settings

router = APIRouter(prefix="/system", tags=["system"])


def _runtime_summary() -> dict:
    settings = get_settings()
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "api_host": settings.api_host,
        "api_port": settings.api_port,
        "deepseek_configured": bool(settings.deepseek_api_key),
        "browser_profile_configured": bool(settings.browser_profile_dir),
    }


@router.get("/diagnostics")
async def system_diagnostics():
    return {
        "runtime": _runtime_summary(),
        "database": collect_sanitized_diagnostics(),
    }


@router.post("/diagnostics/export")
async def system_diagnostics_export():
    log_dir = Path(os.environ.get("HRAGENT_LOG_DIR") or "data/debug")
    try:
        zip_path = export_diagnostics_zip(log_dir, extra=_runtime_summary())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "path": str(zip_path), "file_name": zip_path.name}


@router.post("/db/backup")
async def system_db_backup():
    try:
        result = backup_sqlite_database()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "ok": True,
        "directory": str(result.directory),
        "files": [p.name for p in result.files],
    }


@router.post("/db/compact")
async def system_db_compact():
    try:
        return compact_sqlite_database(require_idle=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
