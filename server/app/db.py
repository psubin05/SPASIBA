"""DB 연결. 운영은 PostgreSQL, 로컬 개발·테스트는 SQLite도 가능.

테이블: 우리 표는 app/models.py, 지도 표(수빈 담당) 미러는 app/models_map.py.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


# PostgreSQL에서는 JSONB, SQLite에서는 JSON(텍스트)
JsonType = JSON().with_variant(JSONB(), "postgresql")
# 목록 열: append 등 리스트 안쪽 변경도 저장되게 한다 (기본 JSON 열은 다시 대입할 때만 감지)
JsonList = MutableList.as_mutable(JsonType)


class UtcDateTime(TypeDecorator):
    """시간대가 있는 시각만 받는다. UTC로 바꿔 저장하고, 꺼낼 때 항상 UTC 시간대를 붙인다.

    PostgreSQL은 TIMESTAMPTZ, SQLite는 시간대를 저장하지 못하므로 UTC 기준 문자열로 둔다.
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("시간대가 없는 시각은 저장하지 않음 (ISO 8601 +09:00 형식 필요)")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _sqlite_foreign_keys(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")  # SQLite는 기본으로 FK를 검사하지 않음
    cur.close()


def make_engine(url: str) -> Engine:
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_foreign_keys)
    return engine


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        from . import models  # noqa: F401  (표 정의를 metadata에 등록)
        Base.metadata.create_all(self.engine)  # 이미 있는 표(수빈 SQL로 만든 지도 표 등)는 건너뜀

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def session(self) -> Iterator[Session]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
