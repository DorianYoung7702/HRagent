from __future__ import annotations

import sqlite3


from packages.db_maintenance import (
    PERSONAL_SQLITE_INDEXES,
    backup_sqlite_database,
    collect_sanitized_diagnostics,
    ensure_personal_sqlite_indexes,
    sqlite_integrity_check,
)


def _create_minimal_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE recruiting_workflows (
            id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT,
            error_message TEXT
        );
        CREATE TABLE candidate_snapshots (
            id TEXT PRIMARY KEY,
            workflow_id TEXT,
            captured_at TEXT,
            raw_text TEXT
        );
        CREATE TABLE candidate_screening_results (
            id TEXT PRIMARY KEY,
            workflow_id TEXT,
            candidate_snapshot_id TEXT,
            screening_round INTEGER
        );
        CREATE TABLE shortlist_candidates (
            id TEXT PRIMARY KEY,
            shortlist_id TEXT,
            rank INTEGER
        );
        CREATE TABLE outreach_conversations (
            id TEXT PRIMARY KEY,
            workflow_id TEXT,
            status TEXT,
            updated_at TEXT
        );
        CREATE TABLE outreach_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            message_text TEXT,
            created_at TEXT
        );
        INSERT INTO recruiting_workflows
            (id, name, status, created_at, updated_at, error_message)
            VALUES ('wf1', '任务', 'FAILED', '2026-06-10', '2026-06-10', 'Page closed');
        INSERT INTO candidate_snapshots
            (id, workflow_id, captured_at, raw_text)
            VALUES ('s1', 'wf1', '2026-06-10', '敏感简历原文');
        INSERT INTO outreach_messages
            (id, conversation_id, message_text, created_at)
            VALUES ('m1', 'c1', '敏感 IM 全文', '2026-06-10');
        """
    )
    con.commit()
    con.close()


def test_ensure_personal_sqlite_indexes_creates_expected_indexes(tmp_path):
    db_path = tmp_path / "recruiting.db"
    _create_minimal_db(db_path)

    ensure_personal_sqlite_indexes(db_path)

    con = sqlite3.connect(db_path)
    index_names = {
        row[1]
        for table in [
            "recruiting_workflows",
            "candidate_snapshots",
            "candidate_screening_results",
            "outreach_conversations",
            "outreach_messages",
            "shortlist_candidates",
        ]
        for row in con.execute(f"PRAGMA index_list({table})")
    }
    con.close()
    assert {idx.name for idx in PERSONAL_SQLITE_INDEXES}.issubset(index_names)


def test_sqlite_integrity_check_returns_ok(tmp_path):
    db_path = tmp_path / "recruiting.db"
    _create_minimal_db(db_path)

    assert sqlite_integrity_check(db_path) == "ok"


def test_backup_sqlite_database_copies_db_wal_and_shm(tmp_path):
    db_path = tmp_path / "recruiting.db"
    _create_minimal_db(db_path)
    (tmp_path / "recruiting.db-wal").write_text("wal", encoding="utf-8")
    (tmp_path / "recruiting.db-shm").write_text("shm", encoding="utf-8")

    backup = backup_sqlite_database(db_path, tmp_path / "backups", retain=5)

    names = {p.name for p in backup.files}
    assert "recruiting.db" in names
    assert "recruiting.db-wal" in names
    assert "recruiting.db-shm" in names


def test_collect_sanitized_diagnostics_excludes_sensitive_fields(tmp_path):
    db_path = tmp_path / "recruiting.db"
    _create_minimal_db(db_path)

    summary = collect_sanitized_diagnostics(db_path)
    rendered = repr(summary)

    assert summary["integrity_check"] == "ok"
    assert "敏感简历原文" not in rendered
    assert "敏感 IM 全文" not in rendered
    assert "raw_text" not in rendered
    assert "message_text" not in rendered
