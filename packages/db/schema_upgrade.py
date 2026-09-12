"""SQLite 增量补列（create_all 老库无需重跑完整 alembic）。"""

from __future__ import annotations

import logging

from sqlalchemy import text

from packages.db.session import engine
from packages.db_maintenance import ensure_personal_sqlite_indexes

logger = logging.getLogger(__name__)

_OUTREACH_PATCHES: list[tuple[str, str]] = [
    ("conversation_type", "VARCHAR NOT NULL DEFAULT 'followup'"),
    ("im_contact_key", "VARCHAR"),
    ("last_agent_reason", "TEXT"),
    ("need_resume_request", "BOOLEAN NOT NULL DEFAULT 0"),
]

_TALENT_ARCHIVE_PATCHES: list[tuple[str, str]] = [
    ("resume_raw_text", "TEXT NOT NULL DEFAULT ''"),
]


async def _sqlite_columns(conn, table: str) -> set[str]:
    rows = await conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in rows.fetchall()}


async def ensure_schema_upgrades() -> None:
    """补齐 ORM 新增字段，避免老库缺列导致 API 500。"""
    if not str(engine.url).startswith("sqlite"):
        return

    async with engine.begin() as conn:
        tables = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='outreach_conversations'")
        )
        if not tables.fetchone():
            return

        existing = await _sqlite_columns(conn, "outreach_conversations")
        for col, ddl in _OUTREACH_PATCHES:
            if col in existing:
                continue
            await conn.execute(text(f"ALTER TABLE outreach_conversations ADD COLUMN {col} {ddl}"))
            logger.info("Added column outreach_conversations.%s", col)

        archive_tables = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='talent_archive_profiles'")
        )
        if archive_tables.fetchone():
            archive_columns = await _sqlite_columns(conn, "talent_archive_profiles")
            for col, ddl in _TALENT_ARCHIVE_PATCHES:
                if col in archive_columns:
                    continue
                await conn.execute(text(f"ALTER TABLE talent_archive_profiles ADD COLUMN {col} {ddl}"))
                logger.info("Added column talent_archive_profiles.%s", col)

        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS alembic_version (
                    version_num VARCHAR(32) NOT NULL
                )
                """
            )
        )
        ver = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = ver.fetchone()
        if row is None:
            await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('002')"))
        elif row[0] not in ("002",):
            await conn.execute(text("UPDATE alembic_version SET version_num='002'"))

    ensure_personal_sqlite_indexes(str(engine.url))
