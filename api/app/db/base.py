"""Database engine, session factory, and portable column types.

The same models run on SQLite (local prototype default) and PostgreSQL (later
deployment). Where the two differ in a way that would damage an invariant --
notably 78-digit integer amounts -- the type here adapts per dialect rather than
letting the weaker dialect silently win.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, Numeric, String, create_engine, event, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings

#: Width of the zero-padded decimal string used on dialects without NUMERIC(78,0).
#: 78 digits holds a uint256 (~1.16e77).
AMOUNT_TEXT_WIDTH = 78

#: JSON that becomes JSONB on PostgreSQL and plain JSON elsewhere.
JSONColumn = JSON().with_variant(JSONB(), "postgresql")


class BaseUnits(types.TypeDecorator[int]):
    """An integer amount in base units, exact on every dialect (D004).

    PostgreSQL stores ``NUMERIC(78,0)``. SQLite has no such type -- its NUMERIC
    affinity would hand back a float and destroy precision well below a uint256 --
    so there the value is a zero-padded decimal string.

    Because the SQLite representation is text, never ``ORDER BY`` an amount column
    on a mixed-sign range; sort amounts in Python. Non-negative amounts do sort
    correctly, which is what the zero padding is for.
    """

    impl = Numeric(78, 0)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Numeric(78, 0))
        return dialect.type_descriptor(String(AMOUNT_TEXT_WIDTH + 2))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"amount must be an int in base units, got {type(value).__name__}")
        if dialect.name == "postgresql":
            return Decimal(value)
        if value < 0:
            return "-" + str(-value).rjust(AMOUNT_TEXT_WIDTH, "0")
        return str(value).rjust(AMOUNT_TEXT_WIDTH, "0")

    def process_result_value(self, value: Any, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, str):
            return int(value)
        return int(value)


class UtcDateTime(types.TypeDecorator[dt.datetime]):
    """A timezone-aware UTC timestamp on every dialect.

    SQLite has no timestamp type and hands back naive datetimes, which would
    silently break every chronological comparison the tracer makes. Values are
    normalized to UTC going in and re-tagged as UTC coming out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, dt.datetime):
            raise TypeError(f"expected datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; supply an aware UTC datetime")
        return value.astimezone(dt.UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)


class Base(DeclarativeBase):
    pass


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def make_engine(url: str) -> Any:
    """Build an engine with the per-dialect settings the prototype needs."""
    if url.startswith("sqlite"):
        engine = create_engine(
            url,
            future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_connection: Any, _record: Any) -> None:
            # SQLite ignores foreign keys unless asked. Without this, the
            # authorization and identity constraints are decorative.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            # Local-disk prototype: readers must not prevent the companion
            # worker committing. In-memory test databases keep their own mode.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
            # pysqlite suppresses BEGIN and manages transactions itself, which
            # breaks SAVEPOINT and leaves "transactions" that never roll back.
            # Hand control back to SQLAlchemy (documented pysqlite workaround).
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _emit_begin(conn: Any) -> None:
            conn.exec_driver_sql("BEGIN")

        return engine
    return create_engine(url, pool_pre_ping=True, future=True)


_settings = get_settings()
engine = make_engine(_settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
