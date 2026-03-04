"""
JobSignal — Database session management.

Provides a SQLAlchemy engine and a context-manager-based session
factory so every caller safely acquires and releases connections.
"""

from contextlib import contextmanager
from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from jobsignal.config.settings import get_settings

# Build the engine once at import time.  `pool_pre_ping=True` ensures
# stale connections are automatically recycled.
_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    echo=False,  # Set to True to log all SQL statements during debugging.
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy Session inside a transaction.

    Always use this context manager instead of creating a session
    directly.  It guarantees that:
    - The session is committed on clean exit.
    - The session is rolled back on any exception.
    - The connection is returned to the pool in all cases.

    Example::

        from jobsignal.database.session import get_session
        with get_session() as session:
            session.add(some_model_instance)
    """
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> bool:
    """Return True if the database is reachable, False otherwise.

    Useful for startup health checks and the `status` CLI command.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Database connection failed: {exc}")
        return False
