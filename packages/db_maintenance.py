from __future__ import annotations

import json
import os
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from packages.settings import get_settings


@dataclass(frozen=True)
class SqliteIndexSpec:
    name: str
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class BackupResult:
    directory: Path
    files: list[Path]


PERSONAL_SQLITE_INDEXES: tuple[SqliteIndexSpec, ...] = (
    SqliteIndexSpec(
        "ix_personal_workflows_status_created_at",
        "recruiting_workflows",
        ("status", "created_at"),
    ),
    SqliteIndexSpec(
        "ix_personal_candidate_snapshots_workflow_captured",
        "candidate_snapshots",
        ("workflow_id", "captured_at"),
    ),
    SqliteIndexSpec(
        "ix_personal_screening_latest",
        "candidate_screening_results",
        ("workflow_id", "candidate_snapshot_id", "screening_round"),
    ),
    SqliteIndexSpec(
        "ix_personal_conversations_workflow_status_updated",
        "outreach_conversations",
        ("workflow_id", "status", "updated_at"),
    ),
    SqliteIndexSpec(
        "ix_personal_messages_conversation_created",
        "outreach_messages",
        ("conversation_id", "created_at"),
    ),
    SqliteIndexSpec(
        "ix_personal_shortlist_candidates_rank",
        "shortlist_candidates",
        ("shortlist_id", "rank"),
    ),
)

_KNOWN_TABLES = (
    "recruiting_workflows",
    "candidate_snapshots",
    "candidate_screening_results",
    "shortlists",
    "shortlist_candidates",
    "outreach_conversations",
    "outreach_messages",
    "candidate_profiles_current",
    "candidate_supplemental_info",
)

_ACTIVE_WORKFLOW_STATUSES = {"FETCHING", "SCREENING", "CONVERSATIONS_STARTED"}


def database_path_from_url(database_url: str | None = None) -> Path | None:
    url_text = database_url or os.environ.get("DATABASE_URL") or get_settings().database_url
    if not url_text.startswith("sqlite"):
        return None
    url = make_url(url_text)
    if not url.database:
        return None
    return Path(url.database).expanduser()


def _coerce_db_path(value: str | Path | None) -> Path | None:
    if value is None:
        return database_path_from_url()
    text = str(value)
    if text.startswith("sqlite"):
        return database_path_from_url(text)
    return Path(value)


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def ensure_personal_sqlite_indexes(db_path: str | Path | None = None) -> list[str]:
    path = _coerce_db_path(db_path)
    if path is None or not path.exists():
        return []

    created_or_present: list[str] = []
    con = sqlite3.connect(path)
    try:
        for spec in PERSONAL_SQLITE_INDEXES:
            if not _table_exists(con, spec.table):
                continue
            columns = _table_columns(con, spec.table)
            if not set(spec.columns).issubset(columns):
                continue
            cols_sql = ", ".join(spec.columns)
            con.execute(f"CREATE INDEX IF NOT EXISTS {spec.name} ON {spec.table} ({cols_sql})")
            created_or_present.append(spec.name)
        con.execute("PRAGMA optimize")
        con.commit()
    finally:
        con.close()
    return created_or_present


def sqlite_integrity_check(db_path: str | Path | None = None) -> str:
    path = _coerce_db_path(db_path)
    if path is None or not path.exists():
        return "missing"
    con = sqlite3.connect(path)
    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"
    finally:
        con.close()


def backup_sqlite_database(
    db_path: str | Path | None = None,
    backup_root: str | Path | None = None,
    *,
    retain: int = 5,
) -> BackupResult:
    path = _coerce_db_path(db_path)
    if path is None or not path.exists():
        raise FileNotFoundError("SQLite database not found")

    root = Path(backup_root) if backup_root else path.parent / "backups"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = root / f"backup-{stamp}"
    directory.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    for source in [path, Path(f"{path}-wal"), Path(f"{path}-shm")]:
        if source.exists():
            dest = directory / source.name
            shutil.copy2(source, dest)
            files.append(dest)

    _prune_backups(root, retain)
    return BackupResult(directory=directory, files=files)


def _prune_backups(root: Path, retain: int) -> None:
    if retain <= 0 or not root.exists():
        return
    backups = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    for old in backups[retain:]:
        shutil.rmtree(old, ignore_errors=True)


def active_workflow_count(db_path: str | Path | None = None) -> int:
    path = _coerce_db_path(db_path)
    if path is None or not path.exists():
        return 0
    con = sqlite3.connect(path)
    try:
        if not _table_exists(con, "recruiting_workflows"):
            return 0
        placeholders = ",".join("?" for _ in _ACTIVE_WORKFLOW_STATUSES)
        row = con.execute(
            f"SELECT COUNT(*) FROM recruiting_workflows WHERE status IN ({placeholders})",
            tuple(_ACTIVE_WORKFLOW_STATUSES),
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        con.close()


def compact_sqlite_database(db_path: str | Path | None = None, *, require_idle: bool = True) -> dict[str, Any]:
    path = _coerce_db_path(db_path)
    if path is None or not path.exists():
        raise FileNotFoundError("SQLite database not found")
    active = active_workflow_count(path)
    if require_idle and active:
        return {"ok": False, "reason": "active_workflows", "active_workflows": active}
    before = path.stat().st_size
    con = sqlite3.connect(path)
    try:
        con.execute("VACUUM")
        con.execute("PRAGMA optimize")
    finally:
        con.close()
    after = path.stat().st_size
    return {"ok": True, "before_bytes": before, "after_bytes": after}


def collect_sanitized_diagnostics(db_path: str | Path | None = None) -> dict[str, Any]:
    path = _coerce_db_path(db_path)
    summary: dict[str, Any] = {
        "database": {
            "exists": bool(path and path.exists()),
            "path_name": path.name if path else None,
            "size_bytes": path.stat().st_size if path and path.exists() else 0,
        },
        "integrity_check": sqlite_integrity_check(path) if path else "missing",
        "tables": {},
        "workflow_statuses": {},
        "recent_errors": [],
        "indexes": ensure_personal_sqlite_indexes(path) if path and path.exists() else [],
    }
    if path is None or not path.exists():
        return summary

    con = sqlite3.connect(path)
    try:
        for table in _KNOWN_TABLES:
            if _table_exists(con, table):
                count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                summary["tables"][table] = int(count)
        if _table_exists(con, "recruiting_workflows"):
            summary["workflow_statuses"] = {
                str(status): int(count)
                for status, count in con.execute(
                    "SELECT status, COUNT(*) FROM recruiting_workflows GROUP BY status"
                )
            }
            rows = con.execute(
                """
                SELECT status, substr(COALESCE(error_message, ''), 1, 180), updated_at
                FROM recruiting_workflows
                WHERE COALESCE(error_message, '') != ''
                ORDER BY updated_at DESC
                LIMIT 10
                """
            ).fetchall()
            summary["recent_errors"] = [
                {"status": str(status), "error": str(error), "updated_at": str(updated_at)}
                for status, error, updated_at in rows
            ]
    finally:
        con.close()
    return summary


def export_diagnostics_zip(
    output_dir: str | Path,
    *,
    db_path: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = out / f"hragent-diagnostics-{stamp}.zip"
    summary = collect_sanitized_diagnostics(db_path)
    if extra:
        summary["system"] = extra
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "diagnostics.json",
            json.dumps(summary, ensure_ascii=False, indent=2),
        )
    return zip_path
