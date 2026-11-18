"""MQTT 메시지 처리 (작업 6). paho 없이 MessageHandler를 직접 부른다. 토픽은 v0.4 spasiba/{camera_id}/{kind}."""
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

from app.models import ParkingEvent, ReviewQueue
from app.mqtt_listener import SUBSCRIPTIONS, MessageHandler

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 11, 18, 14, 0, 0, tzinfo=KST)
CAM = "CAM-B2-A-01"


def _handler(app_client):
    sent = []
    h = MessageHandler(app_client.app.state.settings, app_client.app.state.db,
                       publish=lambda topic, payload: sent.append((topic, payload)))
    return h, sent


def _event(plate="12가3456", votes=9):
    return json.dumps({"event_id": str(uuid.uuid4()), "plate_number": plate, "camera_id": CAM,
                       "slot_id": "B2-A-03", "recognized_at": T0.isoformat(), "votes": votes},
                      ensure_ascii=False).encode()


def test_subscriptions_use_v04_topics():
    assert [t for t, _ in SUBSCRIPTIONS] == ["spasiba/+/event", "spasiba/+/status", "spasiba/+/crop"]


def test_event_message_saved_and_matched(app_client):
    h, _ = _handler(app_client)
    app_client.post("/entries", json={"plate_number": "12가3456"})
    assert h.handle(f"spasiba/{CAM}/event", _event(), now=T0) == "assigned"
    body = app_client.get("/vehicles/12가3456/last-location").json()
    assert body["status"] == "CONFIRMED" and body["slot_id"] == "B2-A-03"


def test_bad_messages_do_not_raise(app_client):
    h, _ = _handler(app_client)
    assert h.handle(f"spasiba/{CAM}/event", b"{not json", now=T0) == "rejected"
    assert h.handle(f"spasiba/{CAM}/event", "한글".encode("euc-kr"), now=T0) == "rejected"
    assert h.handle("spasiba/B2-A/CAM-B2-A-01/event", _event(), now=T0) == "ignored"  # v0.3 토픽
    assert h.handle(f"spasiba/{CAM}/unknown", b"{}", now=T0) == "ignored"
    with app_client.app.state.db.SessionLocal() as db:
        assert db.query(ParkingEvent).count() == 0


def test_handler_survives_db_error(app_client, monkeypatch):
    h, _ = _handler(app_client)
    from app import parking
    monkeypatch.setattr(parking, "handle_event", lambda *a, **k: 1 / 0)
    assert h.handle(f"spasiba/{CAM}/event", _event(), now=T0) == "error"


def test_status_messages_tracked(app_client):
    h, _ = _handler(app_client)
    h.handle(f"spasiba/{CAM}/status", b'{"state":"online","ts":"2026-11-18T14:00:00+09:00"}', now=T0)
    assert h.camera_status[CAM]["state"] == "online"
    h.handle(f"spasiba/{CAM}/status", b'{"state":"offline"}', now=T0)
    assert h.camera_status[CAM] | {} == {"state": "offline", "ts": None, "lwt": True,
                                         "received_at": "2026-11-18T14:00:00+09:00"}
    h.handle(f"spasiba/{CAM}/status", b'{"state":"offline","ts":"2026-11-18T14:01:00+09:00"}', now=T0)
    assert h.camera_status[CAM]["lwt"] is False
    assert h.handle(f"spasiba/{CAM}/status", b'{"state":"sleepy"}', now=T0) == "ignored"


def test_tick_publishes_crop_request_and_crop_reply_saved(app_client):
    h, sent = _handler(app_client)
    h.handle(f"spasiba/{CAM}/event", _event("12가3458", votes=2), now=T0)
    assert h.tick(now=T0 + timedelta(seconds=60)) == 0 and sent == []
    assert h.tick(now=T0 + timedelta(seconds=121)) == 1
    (topic, req), = sent
    assert topic == f"spasiba/{CAM}/crop_request" and req["reason"] == "unmatched"
    crop = json.dumps({**req, "captured_at": T0.isoformat(),
                       "image_jpeg_base64": base64.b64encode(b"\xff\xd8\xff\xd9").decode()}).encode()
    assert h.handle(f"spasiba/{CAM}/crop", crop, now=T0) == "crop_saved"
    assert h.handle(f"spasiba/{CAM}/crop", crop.replace(b"r-", b"x-"), now=T0) == "crop_ignored"
    with app_client.app.state.db.SessionLocal() as db:
        assert db.query(ReviewQueue).one().crop_path


def test_tick_survives_errors(app_client, monkeypatch):
    h, _ = _handler(app_client)
    from app import parking
    monkeypatch.setattr(parking, "check_timeouts", lambda *a, **k: 1 / 0)
    assert h.tick(now=T0) == 0
