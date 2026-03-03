"""Database connection and session management."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

Base = declarative_base()


class Database:
    """Database connection manager.
    
    Manages SQLAlchemy engine and session creation.
    Supports both PostgreSQL and SQLite.
    """
    
    def __init__(self, database_url: str, echo: bool = False):
        """Initialize database.
        
        Args:
            database_url: Database URL
                - SQLite: sqlite+aiosqlite:///path/to/db.sqlite
                - PostgreSQL: postgresql+asyncpg://user:pass@host/db
            echo: Enable SQL logging
        """
        self.database_url = database_url
        self.echo = echo

        engine_kwargs: dict[str, object] = {"echo": echo}
        if database_url.startswith("sqlite"):
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["poolclass"] = AsyncAdaptedQueuePool
            engine_kwargs["pool_size"] = 10
            engine_kwargs["max_overflow"] = 20

        # Create engine
        self.engine = create_async_engine(database_url, **engine_kwargs)
        
        # Create session factory
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    
    async def create_tables(self) -> None:
        """Create all tables."""
        from core.storage import models  # noqa: F401
        
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def drop_tables(self) -> None:
        """Drop all tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session context manager.
        
        Yields:
            AsyncSession: Database session
        """
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    async def close(self) -> None:
        """Close database connections."""
        await self.engine.dispose()


def create_database(
    database_url: str | None = None,
    echo: bool = False,
) -> Database:
    """Create database instance.
    
    Args:
        database_url: Database URL (defaults to SQLite in memory)
        echo: Enable SQL logging
        
    Returns:
        Database instance
    """
    if database_url is None:
        # Default to SQLite in current directory
        database_url = "sqlite+aiosqlite:///./nexusdev.db"
    
    return Database(database_url, echo=echo)
