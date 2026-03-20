"""
Database configuration module.

Provides SQLAlchemy async engine, session factory, and table
creation utilities. Uses SQLite by default (aiosqlite driver),
switchable to PostgreSQL via DATABASE_URL environment variable.
"""

import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, inspect, text
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Node, Route, MetricRecord, ClientUser, NodeType, NodeRole

# ---------------------------------------------------------------------------
# Database URL
# ---------------------------------------------------------------------------
# Default: SQLite file in project root.
# Override with env var DATABASE_URL, e.g.:
#   DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./asn_database.db",
)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Dependency for FastAPI
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an async database session for use in FastAPI dependency injection.

    Usage::

        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """
    Create all tables defined by ORM models.

    Called once during application startup via the FastAPI lifespan hook.
    """
    async with engine.begin() as conn:
        from .models import Node, Route, MetricRecord, ClientUser, NodeType, NodeRole  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

        # Migration: Add missing columns to 'nodes' table if they don't exist
        # This is a safe way to handle schema updates without full Alembic migrations.
        def migrate_nodes_table(connection):
            inspector = inspect(connection)
            columns = [c["name"] for c in inspector.get_columns("nodes")]
            
            missing_cols = {
                "allow_streaming": "BOOLEAN DEFAULT 1",
                "allow_gaming": "BOOLEAN DEFAULT 1",
                "allow_browsing": "BOOLEAN DEFAULT 1",
                "transport": "VARCHAR(32) DEFAULT 'quic'",
                "protocol": "VARCHAR(32) DEFAULT 'vless'",
                "tls_enabled": "BOOLEAN DEFAULT 1",
                "reality_public_key": "VARCHAR(256)",
                "reality_short_id": "VARCHAR(16)",
                "reality_sni": "VARCHAR(256)",
                "tls_fragment": "VARCHAR(64)"
            }
            
            for col, col_type in missing_cols.items():
                if col not in columns:
                    print(f"DEBUG: Adding column '{col}' to 'nodes' table...")
                    connection.execute(text(f"ALTER TABLE nodes ADD COLUMN {col} {col_type}"))

        await conn.run_sync(migrate_nodes_table)

    # Auto-register master node if empty
    async with async_session() as session:
        from .models import Node, NodeType, NodeRole
        import uuid
        import socket

        res = await session.execute(select(Node))
        if not res.scalars().first():
            # Get local IP
            try:
                hostname = socket.gethostname()
                ip = socket.gethostbyname(hostname)
            except:
                ip = "127.0.0.1"
            
            master = Node(
                id=str(uuid.uuid4()),
                name="Local Master",
                ip=ip,
                port=8000,
                node_type=NodeType.ENTRY,
                role=NodeRole.MASTER,
                is_active=True
            )
            session.add(master)
            await session.commit()


async def close_db() -> None:
    """Dispose of the database engine (cleanup on shutdown)."""
    await engine.dispose()
