"""서비스 층 (app/parking.py): 입·출차, 이벤트 처리·매칭, 보류 → 관리자 확인, crop.

시각은 테스트가 넘기는 now로 고정한다 (실제 시계 안 씀).
"""
import base64
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import parking as P
from app.models import MatchPending, ParkingEvent, ReviewQueue, SlotAssignment

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 11, 18, 14, 0, 0, tzinfo=KST)
CAM = "CAM-B2-A-01"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60 + b"\xff\xd9"


@pytest.fixture
def cfg(app_client):
    return app_client.app.state.settings


def ev(plate="12가3456", slot="B2-A-03", votes=9, at=T0, **kw):
    body = {"event_id": kw.pop("event_id", str(uuid.uuid4())), "plate_number": plate, "camera_id": CAM,
            "slot_id": slot, "recognized_at": at.isoformat(), "votes": votes, "frames": 10}
    body.update(kw)
    return body


def enter(db, cfg, plate, at=T0):
    return P.create_entry(db, cfg, plate, entered_at=at, now=at)


def open_assignment(db, slot):
    return db.query(SlotAssignment).filter_by(slot_id=slot, ended_at=None).one_or_none()


# ---- 입·출차 ----
def test_entry_normalizes_and_rejects_duplicate(db, cfg):
    s = enter(db, cfg, "12가 3456")
    assert s.plate_norm == "12가3456" and s.state == "ACTIVE"
    with pytest.raises(P.ParkingError) as e:
        enter(db, cfg, "12가3456")
    assert e.value.status == 409


def test_entry_rejects_bad_plate_and_naive_time(db, cfg):
    with pytest.raises(P.ParkingError) as e:
        enter(db, cfg, "12가345")
    assert e.value.status == 422
    with pytest.raises(P.ParkingError) as e:
        P.create_entry(db, cfg, "12가3456", entered_at=datetime(2026, 11, 18, 14), now=T0)
    assert e.value.status == 422


def test_exit_ends_session_and_assignment(db, cfg):
    s = enter(db, cfg, "12가3456")
    assert P.handle_event(db, cfg, CAM, ev(), now=T0) == "assigned"
    out = P.exit_session(db, cfg, plate_number="12가3456", now=T0 + timedelta(hours=1))
    assert out.state == "EXITED" and out.session_id == s.session_id
    assert open_assignment(db, "B2-A-03") is None
    with pytest.raises(P.ParkingError) as e:
        P.exit_session(db, cfg, plate_number="12가3456", now=T0)
    assert e.value.status == 404
    enter(db, cfg, "12가3456", at=T0 + timedelta(hours=2))  # 재입차 가능


def test_exit_by_session_id(db, cfg):
    s = enter(db, cfg, "12가3456")
    assert P.exit_session(db, cfg, session_id=s.session_id, now=T0).state == "EXITED"


# ---- 이벤트 처리 ----
def test_exact_event_assigns(db, cfg):
    s = enter(db, cfg, "12가3456")
    assert P.handle_event(db, cfg, CAM, ev(), now=T0) == "assigned"
    a = open_assignment(db, "B2-A-03")
    assert (a.session_id, a.method) == (s.session_id, "EXACT")
    e = db.query(ParkingEvent).one()
    assert e.valid and e.zone_id == "B2-A" and e.plate_norm == "12가3456"


def test_edit1_and_low_votes(db, cfg):
    enter(db, cfg, "12가3456")
    assert P.handle_event(db, cfg, CAM, ev("12가3458", votes=3), now=T0) == "pending"
    assert P.handle_event(db, cfg, CAM, ev("12가3458", slot="B2-A-01", votes=5), now=T0) == "assigned"
    assert open_assignment(db, "B2-A-01").method == "EDIT1"


def test_duplicate_event_id_ignored(db, cfg):
    enter(db, cfg, "12가3456")
    body = ev()
    assert P.handle_event(db, cfg, CAM, body, now=T0) == "assigned"
    assert P.handle_event(db, cfg, CAM, body, now=T0) == "duplicate"
    assert db.query(ParkingEvent).count() == 1


def test_same_car_same_slot_refreshes_last_seen(db, cfg):
    enter(db, cfg, "12가3456")
    P.handle_event(db, cfg, CAM, ev(), now=T0)
    later = T0 + timedelta(minutes=5)
    assert P.handle_event(db, cfg, CAM, ev(at=later), now=later) == "refreshed"
    a = open_assignment(db, "B2-A-03")
    assert a.last_seen_at == later and len(a.event_ids) == 2


def test_new_car_in_slot_ends_previous(db, cfg):
    a, b = enter(db, cfg, "12가3456"), enter(db, cfg, "56다7890")
    P.handle_event(db, cfg, CAM, ev("12가3456", slot="B2-A-04"), now=T0)
    t1 = T0 + timedelta(seconds=1)
    P.handle_event(db, cfg, CAM, ev("56다7890", slot="B2-A-04", at=t1), now=t1)
    assert open_assignment(db, "B2-A-04").session_id == b.session_id
    assert db.query(SlotAssignment).filter_by(session_id=a.session_id).one().ended_at == t1


def test_car_moves_to_other_slot(db, cfg):
    s = enter(db, cfg, "12가3456")
    P.handle_event(db, cfg, CAM, ev(slot="B2-A-01"), now=T0)
    t1 = T0 + timedelta(minutes=1)
    P.handle_event(db, cfg, CAM, ev(slot="B2-A-02", at=t1), now=t1)
    assert open_assignment(db, "B2-A-01") is None
    assert open_assignment(db, "B2-A-02").session_id == s.session_id


def test_older_event_does_not_override_newer(db, cfg):
    a, b = enter(db, cfg, "12가3456"), enter(db, cfg, "56다7890")
    P.handle_event(db, cfg, CAM, ev("56다7890", slot="B2-A-04", at=T0 + timedelta(minutes=1)), now=T0)
    assert P.handle_event(db, cfg, CAM, ev("12가3456", slot="B2-A-04", at=T0), now=T0) == "stale"
    assert open_assignment(db, "B2-A-04").session_id == b.session_id


def test_event_after_exit_is_not_matched(db, cfg):
    enter(db, cfg, "12가3456")
    P.exit_session(db, cfg, plate_number="12가3456", now=T0)
    assert P.handle_event(db, cfg, CAM, ev(at=T0 + timedelta(minutes=1)), now=T0) == "pending"


@pytest.mark.parametrize("change,reason", [
    ({"slot_id": "B2-Z-99"}, "등록 안 된 칸"),
    ({"slot_id": "B2-B-01"}, "카메라에 등록 안 된 칸"),
    ({"plate_number": "12가345"}, "번호 형식"),
    ({"recognized_at": "2026-11-18T14:00:00"}, "시각"),
    ({"camera_id": "CAM-B2-B-01"}, "토픽"),
    ({"kind": "explode"}, "kind"),
])
def test_invalid_events_saved_not_matched(db, cfg, change, reason):
    enter(db, cfg, "12가3456")
    assert P.handle_event(db, cfg, CAM, ev(**change), now=T0) == "invalid"
    e = db.query(ParkingEvent).one()
    assert not e.valid and reason in e.invalid_reason
    assert db.query(SlotAssignment).count() == 0


def test_missing_fields_saved_invalid(db, cfg):
    assert P.handle_event(db, cfg, CAM, {"event_id": "x1"}, now=T0) == "invalid"
    e = db.get(ParkingEvent, "x1")
    assert not e.valid and "필수" in e.invalid_reason and e.recognized_at == T0


@pytest.mark.parametrize("body", [None, [], "x", {"plate_number": "12가3456"}, {"event_id": ""}])
def test_unstorable_payload_rejected(db, cfg, body):
    assert P.handle_event(db, cfg, CAM, body, now=T0) == "rejected"
    assert db.query(ParkingEvent).count() == 0


def test_old_pi_zone_id_field_ignored(db, cfg):
    enter(db, cfg, "12가3456")
    assert P.handle_event(db, cfg, CAM, ev(zone_id="WRONG"), now=T0) == "assigned"
    assert db.query(ParkingEvent).one().zone_id == "B2-A"


def test_millisecond_timestamp(db, cfg):
    enter(db, cfg, "12가3456")
    assert P.handle_event(db, cfg, CAM, ev(recognized_at="2026-11-18T14:00:00.123+09:00"), now=T0) == "assigned"


# ---- 보류 → 입차 → 다시 매칭 ----
def test_pending_resolves_when_entry_arrives(db, cfg):
    assert P.handle_event(db, cfg, CAM, ev(), now=T0) == "pending"
    enter(db, cfg, "12가3456", at=T0 + timedelta(seconds=5))
    assert open_assignment(db, "B2-A-03").method == "EXACT"
    assert db.query(MatchPending).count() == 0


# ---- 보류 120초 → 관리자 확인 + crop_request ----
def test_timeout_creates_review_and_crop_request(db, cfg):
    s = enter(db, cfg, "12가3456")
    first = ev("12가3458", votes=2)
    P.handle_event(db, cfg, CAM, first, now=T0)
    assert P.check_timeouts(db, cfg, now=T0 + timedelta(seconds=119)) == []
    second = ev("12가3458", votes=3, at=T0 + timedelta(seconds=30))
    P.handle_event(db, cfg, CAM, second, now=T0 + timedelta(seconds=30))
    reqs = P.check_timeouts(db, cfg, now=T0 + timedelta(seconds=121))
    assert len(reqs) == 1
    camera_id, req = reqs[0]
    review = db.query(ReviewQueue).one()
    assert camera_id == CAM and req["slot_id"] == "B2-A-03" and req["reason"] == "unmatched"
    assert req["event_id"] == second["event_id"]  # 그 칸의 가장 최근 이벤트
    assert req["request_id"] == P.request_id_for(review.review_id)
    assert review.status == "OPEN" and [r["event_id"] for r in review.read_plates] == [first["event_id"], second["event_id"]]
    assert review.candidates[0]["session_id"] == str(s.session_id) and review.candidates[0]["distance"] == 1
    assert db.query(MatchPending).count() == 0
    assert P.check_timeouts(db, cfg, now=T0 + timedelta(seconds=500)) == []


def test_crop_saved_for_open_review(db, cfg):
    P.handle_event(db, cfg, CAM, ev("12가3458", votes=2), now=T0)
    (camera_id, req), = P.check_timeouts(db, cfg, now=T0 + timedelta(seconds=121))
    crop = {**req, "captured_at": T0.isoformat(), "image_jpeg_base64": base64.b64encode(JPEG).decode()}
    assert P.handle_crop(db, cfg, CAM, crop) is True
    review = db.query(ReviewQueue).one()
    assert Path(review.crop_path).read_bytes() == JPEG


@pytest.mark.parametrize("change", [
    {"request_id": "r-unknown"}, {"image_jpeg_base64": "not base64!"},
    {"image_jpeg_base64": base64.b64encode(b"GIF89a").decode()},
    {"image_jpeg_base64": base64.b64encode(b"\xff\xd8" + b"0" * 300_000).decode()},
])
def test_bad_crop_ignored(db, cfg, change):
    P.handle_event(db, cfg, CAM, ev("12가3458", votes=2), now=T0)
    (_, req), = P.check_timeouts(db, cfg, now=T0 + timedelta(seconds=121))
    crop = {**req, "image_jpeg_base64": base64.b64encode(JPEG).decode(), **change}
    assert P.handle_crop(db, cfg, CAM, crop) is False
    assert db.query(ReviewQueue).one().crop_path is None


def test_crop_from_other_camera_ignored(db, cfg):
    P.handle_event(db, cfg, CAM, ev("12가3458", votes=2), now=T0)
    (_, req), = P.check_timeouts(db, cfg, now=T0 + timedelta(seconds=121))
    crop = {**req, "image_jpeg_base64": base64.b64encode(JPEG).decode()}
    assert P.handle_crop(db, cfg, "CAM-B2-B-01", crop) is False


# ---- 관리자 확인 ----
def _review(db, cfg, plate="12가3458"):
    P.handle_event(db, cfg, CAM, ev(plate, votes=2), now=T0)
    (_, req), = P.check_timeouts(db, cfg, now=T0 + timedelta(seconds=121))
    P.handle_crop(db, cfg, CAM, {**req, "image_jpeg_base64": base64.b64encode(JPEG).decode()})
    return db.query(ReviewQueue).one()


def test_resolve_assign(db, cfg):
    s = enter(db, cfg, "12가3456")
    r = _review(db, cfg)
    crop = Path(r.crop_path)
    P.resolve_review(db, cfg, r.review_id, "assign", s.session_id, now=T0 + timedelta(minutes=3))
    db.expire_all()
    r = db.get(ReviewQueue, r.review_id)
    assert r.status == "RESOLVED" and r.resolved_session_id == s.session_id and r.crop_path is None
    assert not crop.exists()
    assert open_assignment(db, "B2-A-03").method == "ADMIN"


def test_resolve_dismiss_and_twice(db, cfg):
    r = _review(db, cfg)
    P.resolve_review(db, cfg, r.review_id, "dismiss", None, now=T0)
    assert db.get(ReviewQueue, r.review_id).status == "DISMISSED"
    with pytest.raises(P.ParkingError) as e:
        P.resolve_review(db, cfg, r.review_id, "dismiss", None, now=T0)
    assert e.value.status == 409


def test_resolve_assign_needs_active_session(db, cfg):
    s = enter(db, cfg, "12가3456")
    r = _review(db, cfg)
    P.exit_session(db, cfg, session_id=s.session_id, now=T0)
    with pytest.raises(P.ParkingError) as e:
        P.resolve_review(db, cfg, r.review_id, "assign", s.session_id, now=T0)
    assert e.value.status == 409
    with pytest.raises(P.ParkingError) as e:
        P.resolve_review(db, cfg, uuid.uuid4(), "dismiss", None, now=T0)
    assert e.value.status == 404


def test_exit_removes_session_from_open_review_candidates(db, cfg):
    s = enter(db, cfg, "12가3456")
    r = _review(db, cfg)
    assert r.candidates
    P.exit_session(db, cfg, session_id=s.session_id, now=T0)
    db.expire_all()
    assert db.get(ReviewQueue, r.review_id).candidates == []


# ---- 차량 조회 (작업 8) ----
def test_last_location_confirmed(db, cfg):
    enter(db, cfg, "12가3456")
    P.handle_event(db, cfg, CAM, ev(), now=T0)
    loc = P.last_location(db, cfg, "12가 3456")
    assert loc["status"] == "CONFIRMED" and loc["source"] == "session"
    assert (loc["slot_id"], loc["slot_name"], loc["floor"], loc["zone_id"], loc["node_id"]) == \
        ("B2-A-03", "A-03", "B2", "B2-A", "N-A03")
    assert loc["confirmed_at"] == "2026-11-18T14:00:00+09:00"


def test_last_location_pending_without_and_with_zone(db, cfg):
    enter(db, cfg, "12가3456")
    assert P.last_location(db, cfg, "12가3456") == {
        "plate_number": "12가3456", "status": "PENDING", "message": "주차 위치를 확인하고 있습니다."}
    enter(db, cfg, "12가3457")
    P.handle_event(db, cfg, CAM, ev("12가3458", slot="B2-A-02"), now=T0)  # 후보 2대 → 보류
    for plate in ("12가3456", "12가3457"):
        loc = P.last_location(db, cfg, plate)
        assert (loc["status"], loc["zone_id"], loc["floor"]) == ("PENDING", "B2-A", "B2")
    P.check_timeouts(db, cfg, now=T0 + timedelta(seconds=121))  # 관리자 확인으로 넘어가도 구역 유지
    assert P.last_location(db, cfg, "12가3456")["zone_id"] == "B2-A"


def test_last_location_from_event_without_session(db, cfg):
    P.handle_event(db, cfg, CAM, ev("34나5678", slot="B2-A-02"), now=T0)
    loc = P.last_location(db, cfg, "34나5678")
    assert loc["status"] == "CONFIRMED" and loc["source"] == "event" and loc["slot_id"] == "B2-A-02"


def test_last_location_404_cases(db, cfg):
    with pytest.raises(P.ParkingError) as e:
        P.last_location(db, cfg, "12가3456")
    assert e.value.status == 404
    enter(db, cfg, "12가3456")
    P.handle_event(db, cfg, CAM, ev(), now=T0)
    P.exit_session(db, cfg, plate_number="12가3456", now=T0 + timedelta(minutes=10))
    with pytest.raises(P.ParkingError):
        P.last_location(db, cfg, "12가3456")  # 출차 후: 이벤트가 있어도 404
    P.handle_event(db, cfg, CAM, ev(plate="34나5678", slot="B2-A-01"), now=T0)
    t1 = T0 + timedelta(minutes=1)
    P.handle_event(db, cfg, CAM, ev(plate="99하9999", slot="B2-A-01", at=t1), now=t1)
    with pytest.raises(P.ParkingError):
        P.last_location(db, cfg, "34나5678")  # 세션 없이 이벤트만 있었는데 그 칸에 나중에 다른 차가 보임
