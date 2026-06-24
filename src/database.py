"""
Database connection and session management for Work Wrapped.

Uses SQLAlchemy so the same code runs on SQLite (zero-config, default for local
development) or PostgreSQL in production. Pick the backend with the DATABASE_URL
environment variable, e.g.:

    # Local (default) – SQLite file under data/
    DATABASE_URL=sqlite:///<project>/data/app.db

    # Production – PostgreSQL
    DATABASE_URL=postgresql+psycopg2://user:pass@db:5432/work_wrapped
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_SQLITE = "sqlite:///" + os.path.join(_ROOT, "data", "app.db")

DATABASE_URL = os.environ.get("DATABASE_URL") or _DEFAULT_SQLITE

# SQLite + a threaded server (uvicorn workers, ThreadPoolExecutor) needs this flag.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def init_db():
    """Create tables if they don't exist."""
    from models import User, ServiceCache, Credential  # noqa: F401  (register models on Base)

    if DATABASE_URL.startswith("sqlite"):
        os.makedirs(os.path.join(_ROOT, "data"), exist_ok=True)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
