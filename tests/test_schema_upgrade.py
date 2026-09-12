from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from packages.db.models import Base


@pytest.mark.asyncio
async def test_schema_upgrade_initializes_missing_alembic_version(monkeypatch, tmp_path):
    from packages.db import schema_upgrade

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'new.db').as_posix()}")
    monkeypatch.setattr(schema_upgrade, "engine", engine)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        await schema_upgrade.ensure_schema_upgrades()

        async with engine.connect() as conn:
            version = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            assert version.scalar_one() == "002"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_schema_upgrade_adds_resume_raw_text_to_existing_talent_archive(monkeypatch, tmp_path):
    from packages.db import schema_upgrade

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'legacy-archive.db').as_posix()}")
    monkeypatch.setattr(schema_upgrade, "engine", engine)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("DROP TABLE talent_archive_profiles"))
            await conn.execute(
                text(
                    """
                    CREATE TABLE talent_archive_profiles (
                        id VARCHAR PRIMARY KEY,
                        identity_key VARCHAR NOT NULL UNIQUE,
                        platform VARCHAR NOT NULL,
                        source_snapshot_id VARCHAR NOT NULL,
                        latest_workflow_id VARCHAR NOT NULL,
                        source_url VARCHAR,
                        display_name VARCHAR NOT NULL,
                        current_title VARCHAR,
                        current_company VARCHAR,
                        work_years NUMERIC,
                        education TEXT,
                        city VARCHAR,
                        skills JSON NOT NULL,
                        summary TEXT,
                        experience_summary TEXT,
                        project_summary TEXT,
                        profile_data JSON NOT NULL,
                        best_score NUMERIC,
                        last_score NUMERIC,
                        last_level VARCHAR,
                        source_workflow_ids JSON NOT NULL,
                        first_archived_at DATETIME NOT NULL,
                        last_archived_at DATETIME NOT NULL
                    )
                    """
                )
            )

        await schema_upgrade.ensure_schema_upgrades()

        async with engine.connect() as conn:
            columns = await conn.execute(text("PRAGMA table_info(talent_archive_profiles)"))
            assert "resume_raw_text" in {row[1] for row in columns.fetchall()}
    finally:
        await engine.dispose()
