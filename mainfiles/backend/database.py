"""
database.py — async SQLAlchemy engine, session factory, and the Base
declarative class that models.py builds ORM tables from.
"""
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from .config import settings

_engine = None


def _create_engine():
    """Create the async engine with current settings.

    This is a function (not a module-level constant) so tests can control
    when the engine is created by setting DATABASE_URL in settings before
    the first call.
    """
    _connect_args = {}
    _pool_class = None
    if str(settings.DATABASE_URL).startswith("sqlite"):
        _connect_args = {"timeout": 30, "check_same_thread": False}
        _pool_class = NullPool

    _engine_kwargs = {
        "echo": settings.DEBUG,
        "future": True,
        "connect_args": _connect_args,
    }
    if _pool_class is not None:
        _engine_kwargs["poolclass"] = _pool_class

    return create_async_engine(settings.DATABASE_URL, **_engine_kwargs)


def get_engine():
    """Get or create the async engine (lazy initialization)."""
    global _engine
    if _engine is None:
        _engine = _create_engine()

        @event.listens_for(_engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.close()
    return _engine


class _EngineProxy:
    """Proxy that lazily initializes the engine on first attribute access."""

    def __getattr__(self, name):
        return getattr(get_engine(), name)


engine = _EngineProxy()


class _SessionFactoryProxy:
    """Proxy that lazily binds to the engine on first use."""

    def __call__(self, **kwargs):
        return async_sessionmaker(bind=get_engine(), class_=AsyncSession, expire_on_commit=False)(**kwargs)

    def __getattr__(self, name):
        return getattr(async_sessionmaker(bind=get_engine(), class_=AsyncSession, expire_on_commit=False), name)


AsyncSessionLocal = _SessionFactoryProxy()


class Base(DeclarativeBase):
    pass


async def _add_missing_columns(conn: Any) -> None:
    """Idempotently add columns introduced after a table already exists.

    create_all won't alter existing tables, so lightweight ALTERs keep
    existing local SQLite databases in sync without a full Alembic run.
    """
    from sqlalchemy import text

    needed: dict[str, dict[str, str]] = {
        # A3 (perfect-flow Projects): scoping columns on existing
        # tables — NULL means unscoped/legacy, so old rows are valid.
        "chats": {
            "project_id":
                "ALTER TABLE chats ADD COLUMN project_id VARCHAR(32)",
        },
        "tasks": {
            "project_id":
                "ALTER TABLE tasks ADD COLUMN project_id VARCHAR(32)",
        },
        "custom_agents": {
            "approval_policy":
                "ALTER TABLE custom_agents ADD COLUMN approval_policy VARCHAR(20) DEFAULT 'default'",
            "cost_budget":
                "ALTER TABLE custom_agents ADD COLUMN cost_budget FLOAT DEFAULT 0.0",
        },
        # Deep-read Wave-2: message-evidence persistence + graph hardening.
        # (New tables — goals, pending_pairings, note_link_index — are
        # covered by create_all; only new columns on existing tables
        # need rows here.)
        "messages": {
            "tool_calls_json":
                "ALTER TABLE messages ADD COLUMN tool_calls_json TEXT",
            "citations_json":
                "ALTER TABLE messages ADD COLUMN citations_json TEXT",
            "artifacts_json":
                "ALTER TABLE messages ADD COLUMN artifacts_json TEXT",
        },
        "memory_relations": {
            "confidence":
                "ALTER TABLE memory_relations ADD COLUMN confidence FLOAT DEFAULT 1.0",
            "source_ref":
                "ALTER TABLE memory_relations ADD COLUMN source_ref VARCHAR(512) DEFAULT ''",
        },
    }
    for table, cols in needed.items():
        try:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result.fetchall()}
        except Exception:
            continue
        for col, ddl in cols.items():
            if col not in existing:
                try:
                    await conn.execute(text(ddl))
                except Exception:
                    pass


async def init_db() -> None:
    """Create tables on startup. For anything beyond SQLite-for-a-resume-project,
    replace this with Alembic migrations."""
    # Import models to register them with Base.metadata
    from . import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


async def reset_db() -> None:
    """Drop and recreate all tables (for testing)."""
    # Import models to register them with Base.metadata
    from . import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency — yields a request-scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session


def reset_engine_for_testing():
    """Reset the engine for testing (creates new engine with current settings)."""
    global _engine
    if _engine is not None:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_engine.dispose())
        except RuntimeError:
            asyncio.run(_engine.dispose())
    _engine = None
