from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

SQLITE_BUSY_TIMEOUT_MS = 5000


def apply_sqlite_pragmas(dbapi_connection: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.fetchone()
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA temp_store = MEMORY")
        cursor.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def create_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url)

    if database_url.lower().startswith("sqlite"):
        def _on_connect(dbapi_connection: Any, _record: Any) -> None:
            apply_sqlite_pragmas(dbapi_connection)

        event.listen(engine.sync_engine, "connect", _on_connect)

    return engine

