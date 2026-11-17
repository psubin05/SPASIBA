import base64
import uuid

import pytest

from tools.fake_pi_messages import (
    REGIONS,
    build_crop,
    build_event,
    build_status,
    is_valid_plate,
    topic,
)


@pytest.mark.parametrize("plate", ["12가3456", "123가4567", "서울12가3456", "경기71아3535"])
def test_valid_plates(plate):
    assert is_valid_plate(plate)


@pytest.mark.parametrize("plate", ["12가345", "ab가3456", "뉴욕12가3456", "12 가3456", "", "12각3456"])
def test_invalid_plates(plate):
    assert not is_valid_plate(plate)


def test_regions_count():
    assert len(REGIONS) == 17


def test_topic():
    assert topic("CAM-B2-A-01", "event") == "spasiba/CAM-B2-A-01/event"  # v0.4: 구역 없음


def test_build_event_required_and_optional():
    e = build_event(camera_id="CAM-B2-A-01", slot_id="B2-A-03",
                    plate_number="12가3456")
    for key in ("event_id", "plate_number", "camera_id", "slot_id", "recognized_at"):
        assert key in e
    assert "zone_id" not in e  # v0.4
    assert e["recognized_at"].endswith("+09:00")
    assert "votes" not in e and "frames" not in e and "kind" not in e
    assert uuid.UUID(e["event_id"]).version == 4

    e2 = build_event(camera_id="CAM-B2-A-01", slot_id="B2-A-03",
                     plate_number="12가3456", votes=9, frames=10, kind="confirm")
    assert (e2["votes"], e2["frames"], e2["kind"]) == (9, 10, "confirm")


def test_build_event_keeps_given_event_id():
    eid = str(uuid.uuid4())
    e = build_event(camera_id="CAM-B2-A-01", slot_id="B2-A-03",
                    plate_number="12가3456", event_id=eid)
    assert e["event_id"] == eid


def test_build_status():
    on = build_status("online")
    assert on["state"] == "online" and on["ts"].endswith("+09:00")
    assert build_status("offline") == {"state": "offline"}


def test_build_crop_echoes_request():
    req = {"request_id": "r1", "slot_id": "B2-A-03", "event_id": "e1", "reason": "unmatched"}
    c = build_crop(req)
    assert (c["request_id"], c["slot_id"], c["event_id"]) == ("r1", "B2-A-03", "e1")
    assert c["captured_at"].endswith("+09:00")
    raw = base64.b64decode(c["image_jpeg_base64"])
    assert raw.startswith(b"\xff\xd8")
    assert len(raw) <= 100_000
