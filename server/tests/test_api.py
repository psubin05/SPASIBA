"""HTTP API: 가상 입·출차(작업 5), 차량 조회(작업 8), 인터페이스 3장. 관리자 확인(작업 9)은 나중에."""
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from app import parking as P

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 11, 18, 14, 0, 0, tzinfo=KST)
CAM = "CAM-B2-01"


def ev(plate, slot="B2-A-03", votes=9, at=T0):
    return {"event_id": str(uuid.uuid4()), "plate_number": plate, "camera_id": CAM, "slot_id": slot,
            "recognized_at": at.isoformat(), "votes": votes, "frames": 10}


# ---- 작업 5 ----
def test_entry_exit_flow(app_client):
    r = app_client.post("/entries", json={"plate_number": "12가3456", "entered_at": "2026-11-18T14:00:00+09:00"})
    assert r.status_code == 201
    body = r.json()
    assert body["plate_number"] == "12가3456" and body["state"] == "ACTIVE"
    assert body["entered_at"] == "2026-11-18T14:00:00+09:00"
    uuid.UUID(body["session_id"])
    assert app_client.post("/entries", json={"plate_number": "12가 3456"}).status_code == 409
    listed = app_client.get("/entries", params={"state": "ACTIVE"}).json()
    assert [e["plate_number"] for e in listed] == ["12가3456"]
    r = app_client.post("/exits", json={"plate_number": "12가3456"})
    assert r.status_code == 200 and r.json()["state"] == "EXITED" and r.json()["session_id"] == body["session_id"]
    assert app_client.get("/entries", params={"state": "ACTIVE"}).json() == []
    assert app_client.post("/exits", json={"session_id": body["session_id"]}).status_code == 404


def test_entry_without_time_uses_server_clock(app_client):
    r = app_client.post("/entries", json={"plate_number": "12가3456"})
    assert r.status_code == 201 and r.json()["entered_at"].endswith("+09:00")


def test_entry_validation_errors(app_client):
    for body in ({"plate_number": "12가345"}, {}, {"plate_number": "12가3456", "entered_at": "2026-11-18T14:00:00"},
                 {"plate_number": "12가3456", "entered_at": "어제"}):
        r = app_client.post("/entries", json=body)
        assert r.status_code == 422, body
        assert "code" in r.json()["error"]


def test_exit_needs_exactly_one_key(app_client):
    assert app_client.post("/exits", json={}).status_code == 422
    assert app_client.post("/exits", json={"plate_number": "12가3456", "session_id": str(uuid.uuid4())}).status_code == 422


def test_entries_state_filter_validated(app_client):
    assert app_client.get("/entries", params={"state": "WHATEVER"}).status_code == 422
    assert app_client.get("/entries").status_code == 200


# ---- 작업 8 ----
def test_last_location_states(app_client, db):
    cfg = app_client.app.state.settings
    plate = quote("12가3456")
    assert app_client.get(f"/vehicles/{plate}/last-location").status_code == 404
    assert app_client.get(f"/vehicles/{plate}/last-location").json()["error"]["code"] == "NOT_FOUND"
    app_client.post("/entries", json={"plate_number": "12가3456"})
    assert app_client.get(f"/vehicles/{plate}/last-location").json()["status"] == "PENDING"
    P.handle_event(db, cfg, CAM, ev("12가3456"), now=T0)
    body = app_client.get(f"/vehicles/{plate}/last-location").json()
    assert body["status"] == "CONFIRMED" and body["slot_id"] == "B2-A-03" and body["node_id"] == "N-A03"
