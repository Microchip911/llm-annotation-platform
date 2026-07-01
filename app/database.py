"""Database engine, session factory, and the FastAPI session dependency.

The original prototype configured an *async* engine (``create_async_engine`` +
``AsyncSession``) but every router drove it with the *synchronous* ORM API
(``db.query(...)``, ``db.commit()``). That combination cannot work. We commit to
a fully **synchronous** stack here: it matches the router code, needs no async
test harness, and is the right call for a low-throughput, human-in-the-loop
annotation workload. FastAPI runs synchronous endpoints in a threadpool, so the
event loop is never blocked.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


# SQLite pins a connection to the thread that created it. Because FastAPI serves
# our sync endpoints from a threadpool, we relax that check for SQLite only;
# server-grade backends (e.g. Postgres) neither need nor accept this argument.
_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=settings.sql_echo,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session and guarantee it is closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
