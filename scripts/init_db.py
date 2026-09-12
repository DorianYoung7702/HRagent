"""初始化数据库 — 支持 SQLite（同步，无需 aiosqlite）和 PostgreSQL。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def init_sqlite_sync(db_path: Path) -> None:
    from sqlalchemy import create_engine, event

    from packages.db.models import Base

    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(engine)
    print(f"SQLite tables created: {db_path}")


async def init_async() -> None:
    from packages.db.session import init_db
    from packages.settings import get_settings

    settings = get_settings()
    print(f"Initializing database: {settings.database_url}")
    await init_db()
    print("Database tables created successfully.")


def main() -> None:
    from packages.settings import get_settings

    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        db_file = ROOT / "data" / "recruiting.db"
        init_sqlite_sync(db_file)
    else:
        import asyncio

        asyncio.run(init_async())


if __name__ == "__main__":
    main()
