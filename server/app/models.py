"""수꽝 담당 표 5개 (docs/server_interface.md 5.1, v0.3.2).

- parking_event: Pi 인식 기록 원본. camera/zone/slot에 FK를 걸지 않음 (등록 안 된 칸도 valid=false로 보관)
- entry_session: 입차 세션. 같은 번호의 진행 중 세션은 1개
- slot_assignment: 세션 ↔ 칸 배정 이력. 세션당·칸당 진행 중 배정은 각각 1개
- match_pending: 칸별 보류 상태
- review_queue: 관리자 확인
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, Text, Uuid,
                        func, text, true)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, JsonList, UtcDateTime
from . import models_map  # noqa: F401  (FK 대상 지도 표를 metadata에 등록)


class ParkingEvent(Base):
    __tablename__ = "parking_event"
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)  # 재발행 중복 제거
    plate_number: Mapped[str] = mapped_column(Text, nullable=False)
    plate_norm: Mapped[str] = mapped_column(Text, nullable=False)
    camera_id: Mapped[str] = mapped_column(Text, nullable=False)
    zone_id: Mapped[str | None] = mapped_column(Text)  # parking_slot.zone_id에서 채움, 모르는 칸이면 NULL
    slot_id: Mapped[str] = mapped_column(Text, nullable=False)
    recognized_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, server_default=func.now())
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="confirm", server_default="confirm")
    votes: Mapped[int | None] = mapped_column(Integer)
    frames: Mapped[int | None] = mapped_column(Integer)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    invalid_reason: Mapped[str | None] = mapped_column(Text)


Index("ix_parking_event_plate_time", ParkingEvent.plate_norm, ParkingEvent.recognized_at.desc())


class EntrySession(Base):
    __tablename__ = "entry_session"
    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','EXITED')", name="ck_entry_session_state"),
        Index("uq_entry_session_active_plate", "plate_norm", unique=True,
              postgresql_where=text("state = 'ACTIVE'"), sqlite_where=text("state = 'ACTIVE'")),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plate_number: Mapped[str] = mapped_column(Text, nullable=False)
    plate_norm: Mapped[str] = mapped_column(Text, nullable=False)
    entered_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    exited_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    state: Mapped[str] = mapped_column(Text, nullable=False)


class SlotAssignment(Base):
    __tablename__ = "slot_assignment"
    __table_args__ = (
        CheckConstraint("method IN ('EXACT','EDIT1','ADMIN')", name="ck_slot_assignment_method"),
        Index("uq_slot_assignment_open_session", "session_id", unique=True,
              postgresql_where=text("ended_at IS NULL"), sqlite_where=text("ended_at IS NULL")),
        Index("uq_slot_assignment_open_slot", "slot_id", unique=True,
              postgresql_where=text("ended_at IS NULL"), sqlite_where=text("ended_at IS NULL")),
    )
    # PostgreSQL은 BIGSERIAL, SQLite는 자동 증가가 INTEGER PRIMARY KEY에서만 동작
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True,
                                    autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entry_session.session_id"),
                                                  nullable=False)
    slot_id: Mapped[str] = mapped_column(Text, ForeignKey("parking_slot.slot_id"), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    event_ids: Mapped[list] = mapped_column(JsonList, nullable=False)  # 근거 event_id 목록
    assigned_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class MatchPending(Base):
    __tablename__ = "match_pending"
    slot_id: Mapped[str] = mapped_column(Text, ForeignKey("parking_slot.slot_id"), primary_key=True)
    first_event_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    reads: Mapped[list] = mapped_column(JsonList, nullable=False)  # [{event_id, plate_norm, recognized_at}]


class ReviewQueue(Base):
    __tablename__ = "review_queue"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','RESOLVED','DISMISSED')", name="ck_review_queue_status"),
    )
    review_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slot_id: Mapped[str] = mapped_column(Text, ForeignKey("parking_slot.slot_id"), nullable=False)
    read_plates: Mapped[list] = mapped_column(JsonList, nullable=False)
    candidates: Mapped[list] = mapped_column(JsonList, nullable=False)  # [{session_id, plate_number, entered_at, distance}]
    crop_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    resolved_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
