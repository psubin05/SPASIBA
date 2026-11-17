"""수꽝 API: 가상 입·출차(작업 5), 차량 조회(작업 8). 인터페이스 3.1·3.2."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import parking as P

router = APIRouter(tags=["수꽝: 입·출차 · 조회 · 관리자"])


def get_db(request: Request):
    with request.app.state.db.SessionLocal() as db:
        yield db


def now(request: Request) -> datetime:
    return datetime.now(ZoneInfo(request.app.state.settings.timezone))


class EntryIn(BaseModel):
    plate_number: str
    entered_at: str | None = None


class ExitIn(BaseModel):
    plate_number: str | None = None
    session_id: str | None = None


def _session_out(s, cfg) -> dict:
    return {"session_id": str(s.session_id), "plate_number": s.plate_number,
            "entered_at": P.iso(s.entered_at, cfg), "exited_at": P.iso(s.exited_at, cfg), "state": s.state}


@router.post("/entries", status_code=201)
def create_entry(body: EntryIn, request: Request, db: Session = Depends(get_db)):
    cfg = request.app.state.settings
    entered_at = None
    if body.entered_at is not None:
        entered_at = P.parse_time(body.entered_at)
        if entered_at is None:
            raise P.ParkingError(422, "INVALID_TIME", "entered_at은 시간대 포함 ISO 8601이어야 합니다.")
    s = P.create_entry(db, cfg, body.plate_number, entered_at, now(request))
    out = _session_out(s, cfg)
    out.pop("exited_at")
    return out


@router.post("/exits")
def create_exit(body: ExitIn, request: Request, db: Session = Depends(get_db)):
    if (body.plate_number is None) == (body.session_id is None):
        raise P.ParkingError(422, "INVALID_REQUEST", "plate_number와 session_id 중 하나만 보내세요.")
    session_id = None
    if body.session_id is not None:
        try:
            session_id = uuid.UUID(body.session_id)
        except ValueError:
            raise P.ParkingError(404, "NOT_FOUND", "진행 중인 입차 기록이 없습니다.") from None
    s = P.exit_session(db, request.app.state.settings, now(request), plate_number=body.plate_number,
                       session_id=session_id)
    return {"session_id": str(s.session_id), "exited_at": P.iso(s.exited_at, request.app.state.settings),
            "state": s.state}


@router.get("/entries")
def list_entries(request: Request, state: Literal["ACTIVE", "EXITED"] | None = None,
                 db: Session = Depends(get_db)):
    return P.list_entries(db, request.app.state.settings, state)


@router.get("/vehicles/{plate}/last-location")
def last_location(plate: str, request: Request, db: Session = Depends(get_db)):
    return P.last_location(db, request.app.state.settings, plate)
