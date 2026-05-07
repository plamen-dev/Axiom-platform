"""Database engine and session management for Axiom platform.

Provides SQLite-backed persistence with WAL mode for concurrent
read/write performance. Uses SQLAlchemy ORM with a clean interface
that can be swapped to PostgreSQL or other backends later.
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from axiom_core.models import Base

DEFAULT_DB_DIR = Path.home() / ".axiom"
DEFAULT_DB_NAME = "axiom.db"


def _enable_wal(dbapi_connection, connection_record):
    """Enable WAL mode and tuning pragmas on each new SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_database_url(db_path: str | None = None) -> str:
    """Build a SQLAlchemy database URL for SQLite.

    Args:
        db_path: Explicit path to the database file. If None, uses
                 the AXIOM_DB_PATH env var or falls back to
                 ~/.axiom/axiom.db.
    """
    if db_path is None:
        db_path = os.environ.get("AXIOM_DB_PATH")

    if db_path is None:
        db_dir = DEFAULT_DB_DIR
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / DEFAULT_DB_NAME)

    return f"sqlite:///{db_path}"


def create_db_engine(db_path: str | None = None, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine with WAL-mode SQLite.

    Args:
        db_path: Explicit path to the database file.
        echo: If True, log all SQL statements.
    """
    url = get_database_url(db_path)
    engine = create_engine(url, echo=echo)

    event.listen(engine, "connect", _enable_wal)

    return engine


def init_db(engine: Engine) -> None:
    """Create all tables if they do not already exist."""
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker:
    """Return a configured session factory bound to *engine*."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session(session_factory: sessionmaker) -> Generator[Session, None, None]:
    """Context manager that yields a session and handles commit/rollback."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
