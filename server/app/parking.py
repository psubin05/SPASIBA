"""입·출차, 이벤트 처리·매칭, 보류 → 관리자 확인, crop, 차량 조회 (작업 5~9의 서비스 층).

API(app/routers/)와 MQTT 수신기(app/mqtt_listener.py)가 이 함수들을 부른다.
시각은 호출하는 쪽이 now로 넘긴다 (테스트에서 시계를 고정하기 위해).
규칙: docs/server_interface.md v0.4 2~4장.
"""
from __future__ import annotations

import base64
import binascii
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .matching import Candidate, decide
from .models import EntrySession, MatchPending, ParkingEvent, ReviewQueue, SlotAssignment
from .models_map import ParkingSlot, Zone
from .plates import edit_distance, is_valid, normalize

log = logging.getLogger("spasiba.parking")

REQUIRED = ("plate_number", "camera_id", "slot_id", "recognized_at")
KINDS = ("confirm", "recheck")
CROP_MAX_BYTES = 200_000  # 인터페이스는 100KB 이하. 여유를 두고 그보다 크면 버림


class ParkingError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- 공통 ----
def iso(dt: datetime | None, cfg: Settings) -> str | None:
    return None if dt is None else dt.astimezone(ZoneInfo(cfg.timezone)).isoformat(timespec="seconds")


def parse_time(value) -> datetime | None:
    """시간대가 있는 ISO 8601만 받는다 (밀리초·Z 허용)."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None and dt.utcoffset() is not None else None


def _require_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ParkingError(422, "INVALID_TIME", "시각에는 시간대가 있어야 합니다 (예: 2026-11-18T14:00:00+09:00).")
    return dt


def _active_session(db: Session, plate_norm: str) -> EntrySession | None:
    return db.scalars(select(EntrySession).where(EntrySession.plate_norm == plate_norm,
                                                 EntrySession.state == "ACTIVE")).first()


def _open_by_slot(db: Session, slot_id: str) -> SlotAssignment | None:
    return db.scalars(select(SlotAssignment).where(SlotAssignment.slot_id == slot_id,
                                                   SlotAssignment.ended_at.is_(None))).first()


def _open_by_session(db: Session, session_id: uuid.UUID) -> SlotAssignment | None:
    return db.scalars(select(SlotAssignment).where(SlotAssignment.session_id == session_id,
                                                   SlotAssignment.ended_at.is_(None))).first()


def _candidates(db: Session, cfg: Settings) -> list[Candidate]:
    rows = db.scalars(select(EntrySession).where(EntrySession.state == "ACTIVE")).all()
    return [Candidate(s.session_id, s.plate_norm, s.plate_number, iso(s.entered_at, cfg)) for s in rows]


def _assign(db: Session, session_id: uuid.UUID, slot_id: str, method: str, event_ids: list[str],
            at: datetime, force: bool = False) -> bool:
    """칸 배정. 그 칸의 이전 차, 그 차의 이전 칸 배정은 종료한다. 더 새 관측이 있으면 False (stale)."""
    slot_open, sess_open = _open_by_slot(db, slot_id), _open_by_session(db, session_id)
    if slot_open is not None and slot_open.session_id == session_id:
        if at > slot_open.last_seen_at:
            slot_open.last_seen_at = at
        slot_open.event_ids.extend(e for e in event_ids if e not in slot_open.event_ids)
        return True
    if not force and any(a is not None and a.last_seen_at > at for a in (slot_open, sess_open)):
        return False
    for a in (slot_open, sess_open):
        if a is not None:
            a.ended_at = at
    db.flush()  # 부분 유니크 인덱스: 이전 배정을 먼저 끝낸다
    db.add(SlotAssignment(session_id=session_id, slot_id=slot_id, method=method, event_ids=list(event_ids),
                          assigned_at=at, last_seen_at=at))
    pending = db.get(MatchPending, slot_id)
    if pending is not None:
        db.delete(pending)
    db.flush()
    return True


# ---- 입·출차 (작업 5) ----
def create_entry(db: Session, cfg: Settings, plate_number: str, entered_at: datetime | None,
                 now: datetime) -> EntrySession:
    norm = normalize(plate_number)
    if not is_valid(norm):
        raise ParkingError(422, "INVALID_PLATE", f"번호판 형식이 아닙니다: {plate_number!r}")
    entered_at = _require_aware(entered_at) if entered_at is not None else now
    if _active_session(db, norm) is not None:
        raise ParkingError(409, "CONFLICT", "같은 번호의 진행 중 입차 기록이 이미 있습니다.")
    session = EntrySession(session_id=uuid.uuid4(), plate_number=norm, plate_norm=norm,
                           entered_at=entered_at, state="ACTIVE")
    db.add(session)
    try:
        db.flush()
    except IntegrityError:  # 동시에 같은 번호 입차
        db.rollback()
        raise ParkingError(409, "CONFLICT", "같은 번호의 진행 중 입차 기록이 이미 있습니다.") from None
    retry_pending(db, cfg)
    db.commit()
    return session


def exit_session(db: Session, cfg: Settings, now: datetime, plate_number: str | None = None,
                 session_id: uuid.UUID | None = None) -> EntrySession:
    if session_id is not None:
        session = db.get(EntrySession, session_id)
        session = session if session is not None and session.state == "ACTIVE" else None
    else:
        session = _active_session(db, normalize(plate_number))
    if session is None:
        raise ParkingError(404, "NOT_FOUND", "진행 중인 입차 기록이 없습니다.")
    session.state, session.exited_at = "EXITED", now
    open_a = _open_by_session(db, session.session_id)
    if open_a is not None:
        open_a.ended_at = now
    sid = str(session.session_id)
    for review in db.scalars(select(ReviewQueue).where(ReviewQueue.status == "OPEN")):
        if any(c.get("session_id") == sid for c in review.candidates):
            review.candidates = [c for c in review.candidates if c.get("session_id") != sid]
    db.commit()
    return session


def list_entries(db: Session, cfg: Settings, state: str | None) -> list[dict]:
    q = select(EntrySession).order_by(EntrySession.entered_at.desc())
    if state:
        q = q.where(EntrySession.state == state)
    out = []
    for s in db.scalars(q):
        a = _open_by_session(db, s.session_id)
        out.append({"session_id": str(s.session_id), "plate_number": s.plate_number,
                    "entered_at": iso(s.entered_at, cfg), "exited_at": iso(s.exited_at, cfg),
                    "state": s.state, "slot_id": a.slot_id if a else None})
    return out


# ---- 이벤트 처리 (작업 6·7) ----
def handle_event(db: Session, cfg: Settings, topic_camera_id: str, payload, now: datetime) -> str:
    """결과: rejected | duplicate | invalid | assigned | refreshed | stale | pending"""
    if not isinstance(payload, dict) or not isinstance(payload.get("event_id"), str) \
            or not 1 <= len(payload["event_id"]) <= 128:
        log.warning("event_id 없는 이벤트, 저장 안 함 (%s): %r", topic_camera_id, payload)
        return "rejected"
    event_id = payload["event_id"]
    if db.get(ParkingEvent, event_id) is not None:
        return "duplicate"

    reasons = []
    missing = [k for k in REQUIRED if payload.get(k) in (None, "")]
    if missing:
        reasons.append("필수 필드 없음: " + ", ".join(missing))
    plate_number = payload.get("plate_number") if isinstance(payload.get("plate_number"), str) else ""
    norm = normalize(plate_number)
    camera_id = payload.get("camera_id") if isinstance(payload.get("camera_id"), str) else topic_camera_id
    slot_id = payload.get("slot_id") if isinstance(payload.get("slot_id"), str) else ""
    recognized_at = parse_time(payload.get("recognized_at"))
    if recognized_at is None:
        if "recognized_at" not in missing:
            reasons.append("시각 형식 오류 (시간대 포함 ISO 8601 필요)")
        recognized_at = now
    if camera_id != topic_camera_id:
        reasons.append(f"토픽 camera_id({topic_camera_id})와 본문({camera_id})이 다름")
    votes, frames = (payload.get(k) for k in ("votes", "frames"))
    for name, value in (("votes", votes), ("frames", frames)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            reasons.append(f"{name} 형식 오류")
    votes = votes if isinstance(votes, int) and not isinstance(votes, bool) and votes >= 0 else None
    frames = frames if isinstance(frames, int) and not isinstance(frames, bool) and frames >= 0 else None
    kind = payload.get("kind") or "confirm"
    if kind not in KINDS:
        reasons.append(f"kind 오류: {kind!r}")
        kind = str(kind)[:32]
    slot = db.get(ParkingSlot, slot_id) if slot_id else None
    if slot_id and slot is None:
        reasons.append(f"등록 안 된 칸: {slot_id}")
    elif slot is not None and slot.camera_id != camera_id:
        reasons.append(f"카메라에 등록 안 된 칸: {slot_id}는 {slot.camera_id} 담당")
    if plate_number and not is_valid(norm):
        reasons.append(f"번호 형식 오류: {plate_number!r}")

    event = ParkingEvent(event_id=event_id, plate_number=plate_number, plate_norm=norm, camera_id=camera_id,
                         zone_id=slot.zone_id if slot else None, slot_id=slot_id, recognized_at=recognized_at,
                         kind=kind, votes=votes, frames=frames, valid=not reasons,
                         invalid_reason="; ".join(reasons) or None)
    db.add(event)
    try:
        db.flush()
    except IntegrityError:  # 같은 event_id가 동시에 들어옴
        db.rollback()
        return "duplicate"
    if reasons:
        log.warning("잘못된 이벤트 %s: %s", event_id, event.invalid_reason)
        db.commit()
        return "invalid"

    result = _match_event(db, cfg, event, now)
    db.commit()
    return result


def _match_event(db: Session, cfg: Settings, event: ParkingEvent, now: datetime) -> str:
    current = _open_by_slot(db, event.slot_id)
    if current is not None:
        session = db.get(EntrySession, current.session_id)
        if session.plate_norm == event.plate_norm:  # 같은 칸·같은 차: last_seen_at만 갱신
            _assign(db, session.session_id, event.slot_id, current.method, [event.event_id], event.recognized_at)
            pending = db.get(MatchPending, event.slot_id)
            if pending is not None:
                db.delete(pending)
            return "refreshed"
    decision = decide(event.plate_norm, event.votes, _candidates(db, cfg), cfg.match_min_votes)
    if decision.method:
        ok = _assign(db, decision.session_id, event.slot_id, decision.method, [event.event_id],
                     event.recognized_at)
        return "assigned" if ok else "stale"
    read = {"event_id": event.event_id, "plate_number": event.plate_number, "plate_norm": event.plate_norm,
            "votes": event.votes, "recognized_at": event.recognized_at.isoformat()}
    pending = db.get(MatchPending, event.slot_id)
    if pending is None:
        db.add(MatchPending(slot_id=event.slot_id, first_event_at=now, reads=[read]))
    else:
        pending.reads.append(read)
    db.flush()
    return "pending"


def retry_pending(db: Session, cfg: Settings) -> None:
    """입차가 새로 생기면 보류 중인 칸을 다시 판단한다 (최근 읽기부터)."""
    candidates = _candidates(db, cfg)
    for pending in list(db.scalars(select(MatchPending))):
        for read in reversed(pending.reads):
            decision = decide(read["plate_norm"], read.get("votes"), candidates, cfg.match_min_votes)
            if decision.method:
                _assign(db, decision.session_id, pending.slot_id, decision.method, [read["event_id"]],
                        datetime.fromisoformat(read["recognized_at"]))
                break


# ---- 보류 120초 → 관리자 확인 + crop 요청 (규칙 ④) ----
def request_id_for(review_id: uuid.UUID) -> str:
    return f"r-{review_id.hex}"


def check_timeouts(db: Session, cfg: Settings, now: datetime) -> list[tuple[str, dict]]:
    """오래된 보류를 review_queue로 넘기고, 보낼 crop_request 목록 (camera_id, payload)을 돌려준다."""
    deadline = now - timedelta(seconds=cfg.match_pending_seconds)
    due = db.scalars(select(MatchPending).where(MatchPending.first_event_at <= deadline)).all()
    if not due:
        return []
    candidates = _candidates(db, cfg)
    requests = []
    for pending in due:
        nearby: dict[str, dict] = {}
        for read in pending.reads:
            for c in decide(read["plate_norm"], None, candidates, cfg.match_min_votes).nearby:
                if c["session_id"] not in nearby or c["distance"] < nearby[c["session_id"]]["distance"]:
                    nearby[c["session_id"]] = c
        review = ReviewQueue(review_id=uuid.uuid4(), slot_id=pending.slot_id, read_plates=list(pending.reads),
                             candidates=sorted(nearby.values(), key=lambda c: (c["distance"], c["plate_norm"])),
                             status="OPEN", created_at=now)
        db.add(review)
        db.delete(pending)
        latest = db.scalars(select(ParkingEvent).where(ParkingEvent.slot_id == pending.slot_id)
                            .order_by(ParkingEvent.recognized_at.desc())).first()
        slot = db.get(ParkingSlot, pending.slot_id)
        requests.append((slot.camera_id, {"request_id": request_id_for(review.review_id),
                                          "slot_id": pending.slot_id,
                                          "event_id": latest.event_id if latest else None,
                                          "reason": "unmatched"}))
    db.commit()
    return requests


def handle_crop(db: Session, cfg: Settings, camera_id: str, payload) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("request_id"), str):
        return False
    rid = payload["request_id"]
    try:
        review_id = uuid.UUID(rid[2:]) if rid.startswith("r-") else None
    except ValueError:
        review_id = None
    review = db.get(ReviewQueue, review_id) if review_id else None
    if review is None or review.status != "OPEN":
        log.warning("모르는·끝난 crop 응답 무시: %s", rid)
        return False
    slot = db.get(ParkingSlot, review.slot_id)
    if slot is None or slot.camera_id != camera_id:
        log.warning("다른 카메라의 crop 응답 무시: %s from %s", rid, camera_id)
        return False
    data = payload.get("image_jpeg_base64")
    if not isinstance(data, str) or len(data) > CROP_MAX_BYTES * 4 // 3 + 8:
        return False
    try:
        image = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return False
    if not image.startswith(b"\xff\xd8") or len(image) > CROP_MAX_BYTES:
        log.warning("JPEG가 아니거나 너무 큰 crop 무시: %s (%d bytes)", rid, len(image))
        return False
    folder = Path(cfg.crop_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{review.review_id}.jpg"
    path.write_bytes(image)
    review.crop_path = str(path)
    db.commit()
    return True


def _delete_crop(review: ReviewQueue) -> None:
    if review.crop_path:
        Path(review.crop_path).unlink(missing_ok=True)
        review.crop_path = None


# ---- 관리자 확인 (작업 9) ----
def list_reviews(db: Session, cfg: Settings, status: str | None) -> list[dict]:
    q = select(ReviewQueue).order_by(ReviewQueue.created_at)
    if status:
        q = q.where(ReviewQueue.status == status)
    return [{"review_id": str(r.review_id), "slot_id": r.slot_id, "status": r.status,
             "read_plates": r.read_plates, "candidates": r.candidates, "created_at": iso(r.created_at, cfg),
             "has_crop": bool(r.crop_path), "resolved_at": iso(r.resolved_at, cfg),
             "resolved_session_id": str(r.resolved_session_id) if r.resolved_session_id else None}
            for r in db.scalars(q)]


def review_crop_path(db: Session, review_id: uuid.UUID) -> Path:
    review = db.get(ReviewQueue, review_id)
    if review is None or not review.crop_path or not Path(review.crop_path).is_file():
        raise ParkingError(404, "NOT_FOUND", "사진이 없습니다.")
    return Path(review.crop_path)


def resolve_review(db: Session, cfg: Settings, review_id: uuid.UUID, action: str,
                   session_id: uuid.UUID | None, now: datetime) -> dict:
    review = db.get(ReviewQueue, review_id)
    if review is None:
        raise ParkingError(404, "NOT_FOUND", "확인 항목이 없습니다.")
    if review.status != "OPEN":
        raise ParkingError(409, "CONFLICT", "이미 처리된 확인 항목입니다.")
    if action == "assign":
        session = db.get(EntrySession, session_id) if session_id else None
        if session is None or session.state != "ACTIVE":
            raise ParkingError(409, "CONFLICT", "진행 중인 입차 기록이 아닙니다.")
        _assign(db, session.session_id, review.slot_id, "ADMIN",
                [r["event_id"] for r in review.read_plates], now, force=True)
        review.status, review.resolved_session_id = "RESOLVED", session.session_id
    elif action == "dismiss":
        review.status = "DISMISSED"
    else:
        raise ParkingError(422, "INVALID_REQUEST", "action은 assign 또는 dismiss입니다.")
    review.resolved_at = now
    _delete_crop(review)
    db.commit()
    return {"review_id": str(review.review_id), "status": review.status,
            "resolved_session_id": str(review.resolved_session_id) if review.resolved_session_id else None}


def list_auto_assignments(db: Session, cfg: Settings) -> list[dict]:
    """한 글자 차이로 자동 확정된(EDIT1) 진행 중 배정: 관리자 화면 '자동 확정 · 검토 권장'."""
    rows = db.execute(select(SlotAssignment, EntrySession)
                      .join(EntrySession, EntrySession.session_id == SlotAssignment.session_id)
                      .where(SlotAssignment.method == "EDIT1", SlotAssignment.ended_at.is_(None))
                      .order_by(SlotAssignment.assigned_at)).all()
    out = []
    for a, s in rows:
        reads = db.scalars(select(ParkingEvent.plate_number).where(ParkingEvent.event_id.in_(a.event_ids))).all()
        out.append({"slot_id": a.slot_id, "session_id": str(s.session_id), "plate_number": s.plate_number,
                    "read_plates": sorted(set(reads)), "assigned_at": iso(a.assigned_at, cfg)})
    return out


# ---- 차량 조회 (작업 8) ----
def _slot_info(db: Session, slot_id: str) -> dict:
    slot = db.get(ParkingSlot, slot_id)
    zone = db.get(Zone, slot.zone_id) if slot else None
    return {"slot_id": slot_id, "slot_name": slot.name if slot else None,
            "floor": zone.floor if zone else None, "zone_id": slot.zone_id if slot else None,
            "node_id": slot.node_id if slot else None}


def _pending_zone(db: Session, session: EntrySession) -> str | None:
    """보류·관리자 확인 중인 칸 가운데 이 차와 한 글자 이내로 읽힌 칸의 구역."""
    slots = [p.slot_id for p in db.scalars(select(MatchPending))
             if any(edit_distance(r["plate_norm"], session.plate_norm) <= 1 for r in p.reads)]
    sid = str(session.session_id)
    slots += [r.slot_id for r in db.scalars(select(ReviewQueue).where(ReviewQueue.status == "OPEN"))
              if any(c.get("session_id") == sid for c in r.candidates)]
    zones = {db.get(ParkingSlot, s).zone_id for s in slots if db.get(ParkingSlot, s) is not None}
    return zones.pop() if len(zones) == 1 else None


def last_location(db: Session, cfg: Settings, plate: str) -> dict:
    norm = normalize(plate)
    session = _active_session(db, norm)
    if session is not None:
        a = _open_by_session(db, session.session_id)
        if a is not None:
            return {"plate_number": session.plate_number, "status": "CONFIRMED", **_slot_info(db, a.slot_id),
                    "last_seen_at": iso(a.last_seen_at, cfg), "confirmed_at": iso(a.assigned_at, cfg),
                    "source": "session"}
        out = {"plate_number": session.plate_number, "status": "PENDING"}
        zone_id = _pending_zone(db, session)
        if zone_id:
            zone = db.get(Zone, zone_id)
            out.update(zone_id=zone_id, floor=zone.floor if zone else None)
        out["message"] = "주차 위치를 확인하고 있습니다."
        return out
    # 진행 중 세션 없음 → 정확히 일치하는 최근 이벤트 (명세서 v1.2 방식)
    event = db.scalars(select(ParkingEvent).where(ParkingEvent.plate_norm == norm, ParkingEvent.valid.is_(True))
                       .order_by(ParkingEvent.recognized_at.desc())).first()
    if event is not None and not _event_superseded(db, event):
        return {"plate_number": event.plate_number, "status": "CONFIRMED", **_slot_info(db, event.slot_id),
                "last_seen_at": iso(event.recognized_at, cfg), "confirmed_at": iso(event.recognized_at, cfg),
                "source": "event"}
    raise ParkingError(404, "NOT_FOUND", "해당 차량의 주차 기록이 없습니다.")


def _event_superseded(db: Session, event: ParkingEvent) -> bool:
    """출차했거나, 그 칸에 나중에 다른 차가 보였으면 이벤트 기준 위치는 쓰지 않는다."""
    exited = db.scalars(select(EntrySession).where(EntrySession.plate_norm == event.plate_norm,
                                                   EntrySession.state == "EXITED",
                                                   EntrySession.exited_at >= event.recognized_at)).first()
    if exited is not None:
        return True
    later_other = db.scalars(select(ParkingEvent).where(ParkingEvent.slot_id == event.slot_id,
                                                        ParkingEvent.valid.is_(True),
                                                        ParkingEvent.plate_norm != event.plate_norm,
                                                        ParkingEvent.recognized_at > event.recognized_at)).first()
    return later_other is not None
