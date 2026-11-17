"""가짜 Pi 메시지 만들기 (인터페이스 v0.4 2장). 네트워크·DB 없음."""
from __future__ import annotations

import base64
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

from app.plates import REGIONS, is_valid  # 번호 형식은 서버와 같은 규칙 (용도 문자 목록)

# 16×16 회색 단색 JPEG (161바이트). 번호판이 없는 더미 이미지.
DUMMY_JPEG: bytes = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAALCAAQABABAREA/8QAFQAB"
    "AQAAAAAAAAAAAAAAAAAAAAH/xAAVEAEBAAAAAAAAAAAAAAAAAAAAAf/aAAgBAQAAPwAA/9k="
)


def now_kst() -> datetime:
    return datetime.now(KST)


def _iso(dt: datetime | None) -> str:
    dt = dt or now_kst()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).isoformat(timespec="seconds")


def is_valid_plate(plate: str) -> bool:
    return is_valid(plate or "")


def topic(camera_id: str, kind: str) -> str:
    return f"spasiba/{camera_id}/{kind}"


def build_event(*, camera_id: str, slot_id: str, plate_number: str,
                recognized_at: datetime | None = None, event_id: str | None = None,
                votes: int | None = None, frames: int | None = None,
                kind: str | None = None) -> dict:
    event = {
        "event_id": event_id or str(uuid.uuid4()),
        "plate_number": plate_number,
        "camera_id": camera_id,
        "slot_id": slot_id,
        "recognized_at": _iso(recognized_at),
    }
    for key, value in (("votes", votes), ("frames", frames), ("kind", kind)):
        if value is not None:
            event[key] = value
    return event


def build_status(state: str, ts: datetime | None = None) -> dict:
    """online은 항상 ts를 넣고, offline(LWT)은 ts를 줄 때만 넣는다."""
    if state == "offline" and ts is None:
        return {"state": "offline"}
    return {"state": state, "ts": _iso(ts)}


def build_crop(request: dict, jpeg: bytes = DUMMY_JPEG,
               captured_at: datetime | None = None) -> dict:
    return {
        "request_id": request["request_id"],
        "slot_id": request["slot_id"],
        "event_id": request.get("event_id"),
        "captured_at": _iso(captured_at),
        "image_jpeg_base64": base64.b64encode(jpeg).decode("ascii"),
    }
