import json
import socket
import threading
import time

import pytest

from tools.fake_pi import FakePi, main
from tools.scenario import SCENARIO_DIR, load_scenario


def _scenario(name):
    return load_scenario(SCENARIO_DIR / f"{name}.json")


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, topic, payload, retain):
        self.calls.append((topic, payload, retain))

    def of(self, kind):
        return [p for t, p, _ in self.calls if t.endswith("/" + kind)]


def test_run_publishes_events_in_order():
    rec = Recorder()
    log = FakePi(_scenario("01_exact"), publish=rec).run(linger=0)
    events = rec.of("event")
    assert len(events) == 1
    assert events[0]["plate_number"] == "12가3456"
    assert events[0]["slot_id"] == "B2-A-03"
    # 처음에 online(retained), 끝에 정상 종료 offline
    assert rec.calls[0][0] == "spasiba/CAM-B2-A-01/status"
    assert rec.calls[0][1]["state"] == "online" and rec.calls[0][2] is True
    assert rec.of("status")[-1]["state"] == "offline"
    assert [m["topic"] for m in log] == [t for t, _, _ in rec.calls]


def test_repeat_of_reuses_event_id():
    rec = Recorder()
    FakePi(_scenario("06_duplicate_event_id"), publish=rec).run(linger=0)
    events = rec.of("event")
    assert len(events) == 2
    assert events[0]["event_id"] == events[1]["event_id"]


def test_abrupt_disconnect_skips_graceful_offline():
    rec = Recorder()
    FakePi(_scenario("08_lwt"), publish=rec).run(linger=0)
    # 비정상 끊김은 브로커의 LWT가 offline을 내므로 가짜 Pi가 직접 보내지 않는다
    assert [s["state"] for s in rec.of("status")] == ["online"]


def _start(fp):
    """연결된 상태로 steps만 실행 (종료하지 않음)."""
    for camera_id in fp.cameras:
        fp._connect(camera_id)
    for step in fp.scenario["steps"]:
        fp._run_step(step)


def test_crop_request_bad_json_ignored():
    fp = FakePi(_scenario("01_exact"), publish=Recorder())
    assert fp.handle_crop_request("CAM-B2-A-01", b"{not json") is None
    assert fp.handle_crop_request("CAM-B2-A-01", b"[1, 2]") is None
    assert fp.handle_crop_request("CAM-B2-A-01", json.dumps({"slot_id": "B2-A-03"}).encode()) is None


def test_crop_request_unknown_slot_ignored():
    rec = Recorder()
    fp = FakePi(_scenario("01_exact"), publish=rec)
    raw = json.dumps({"request_id": "r1", "slot_id": "B9-Z-01", "event_id": "x"}).encode()
    assert fp.handle_crop_request("CAM-B2-A-01", raw) is None
    assert fp.handle_crop_request("CAM-UNKNOWN", raw) is None
    assert rec.of("crop") == []


def test_crop_request_answered_for_latest_event():
    rec = Recorder()
    fp = FakePi(_scenario("01_exact"), publish=rec)
    _start(fp)
    latest = rec.of("event")[0]["event_id"]
    raw = json.dumps({"request_id": "r1", "slot_id": "B2-A-03", "event_id": latest,
                      "reason": "unmatched"}).encode()
    crop = fp.handle_crop_request("CAM-B2-A-01", raw)
    assert crop["request_id"] == "r1" and crop["event_id"] == latest
    assert len(rec.of("crop")) == 1


def test_crop_request_needs_matching_event_id():
    """실제 Pi(raspberrypi 브랜치)처럼 event_id가 그 칸의 마지막 이벤트와 다르거나 없으면 응답하지 않는다."""
    rec = Recorder()
    fp = FakePi(_scenario("01_exact"), publish=rec)
    _start(fp)
    for body in ({"request_id": "r2", "slot_id": "B2-A-03"},
                 {"request_id": "r3", "slot_id": "B2-A-03", "event_id": "old"}):
        assert fp.handle_crop_request("CAM-B2-A-01", json.dumps(body).encode()) is None
    assert rec.of("crop") == []


def test_connect_timeout():
    fp = FakePi(_scenario("01_exact"), port=1, connect_timeout=0.5)
    started = time.monotonic()
    with pytest.raises(ConnectionError):
        fp.run(linger=0)
    assert time.monotonic() - started < 5


def test_main_returns_2_when_broker_unreachable(capsys):
    code = main([str(SCENARIO_DIR / "01_exact.json"), "--port", "1", "--linger", "0"])
    assert code == 2


def _broker_up(host="localhost", port=1883):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def test_against_real_broker():
    if not _broker_up():
        pytest.skip("localhost:1883 브로커 없음")
    import paho.mqtt.client as mqtt

    got = []
    ready = threading.Event()
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-pi-test-sub")
    sub.on_connect = lambda c, u, f, rc, p: (c.subscribe("spasiba/#", qos=1), ready.set())
    sub.on_message = lambda c, u, m: got.append((m.topic, json.loads(m.payload)))
    sub.connect("localhost", 1883)
    sub.loop_start()
    try:
        assert ready.wait(5)
        time.sleep(0.3)
        got.clear()
        FakePi(_scenario("01_exact")).run(linger=0.5)
        time.sleep(1)
    finally:
        sub.loop_stop()
        sub.disconnect()
    topics = [t for t, _ in got]
    assert topics.count("spasiba/CAM-B2-A-01/event") == 1
    assert any(t.endswith("/status") and p.get("state") == "online" for t, p in got)


# ---- 최종 리뷰 수정 (C1, I1, I2, I4) : 실제 paho 경로를 가짜 client로 검사 ----
class FakeInfo:
    def __init__(self):
        self.waited = False

    def wait_for_publish(self, timeout=None):
        self.waited = True


class FakeClient:
    def __init__(self):
        self.published, self.infos, self.calls = [], [], []

    def publish(self, topic, payload, qos=0, retain=False):
        info = FakeInfo()
        self.published.append((topic, json.loads(payload), retain))
        self.infos.append(info)
        return info

    def disconnect(self):
        self.calls.append("disconnect")

    def loop_stop(self):
        self.calls.append("loop_stop")

    def socket(self):
        return None


def _with_fake_client(name="01_exact"):
    fp = FakePi(_scenario(name))
    client = FakeClient()
    fp._clients["CAM-B2-A-01"] = client
    fp._connected.add("CAM-B2-A-01")
    return fp, client


def test_graceful_close_publishes_offline_with_ts_then_disconnects():
    fp, client = _with_fake_client()
    fp._close("CAM-B2-A-01", abrupt=False)
    topic_, payload, retain = client.published[-1]
    assert topic_.endswith("/status") and payload["state"] == "offline" and "ts" in payload
    assert retain is True
    assert "disconnect" in client.calls
    assert all(i.waited for i in client.infos)


def test_abrupt_close_waits_for_queued_publishes():
    fp, client = _with_fake_client()
    fp._run_step({"type": "event", "camera_id": "CAM-B2-A-01", "slot_id": "B2-A-03",
                  "plate_number": "12가3456"})
    fp._close("CAM-B2-A-01", abrupt=True)
    assert client.infos and all(i.waited for i in client.infos)
    assert "disconnect" not in client.calls


def test_publish_after_client_gone_does_not_raise():
    fp, client = _with_fake_client()
    fp._close("CAM-B2-A-01", abrupt=True)
    raw = json.dumps({"request_id": "r1", "slot_id": "B2-A-03", "event_id": "x"}).encode()
    assert fp._on_crop_message("CAM-B2-A-01", raw) is None


def test_crop_message_callback_swallows_errors(monkeypatch):
    fp, _ = _with_fake_client()
    monkeypatch.setattr(fp, "handle_crop_request", lambda *a: 1 / 0)
    assert fp._on_crop_message("CAM-B2-A-01", b"{}") is None


def test_status_step_after_disconnect_skipped():
    fp, client = _with_fake_client()
    fp._close("CAM-B2-A-01", abrupt=True)
    fp._run_step({"type": "status", "camera_id": "CAM-B2-A-01", "state": "online"})


def test_real_broker_lwt_and_graceful_offline():
    if not _broker_up():
        pytest.skip("localhost:1883 브로커 없음")
    import paho.mqtt.client as mqtt

    got = []
    ready = threading.Event()
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fake-pi-test-sub2")
    sub.on_connect = lambda c, u, f, rc, p: (c.subscribe("spasiba/+/status", qos=1), ready.set())
    sub.on_message = lambda c, u, m: got.append(json.loads(m.payload))
    sub.connect("localhost", 1883)
    sub.loop_start()
    try:
        assert ready.wait(5)
        time.sleep(0.3)
        got.clear()
        FakePi(_scenario("01_exact")).run(linger=0)
        time.sleep(1)
        assert got[-1]["state"] == "offline" and "ts" in got[-1]   # 정상 종료
        got.clear()
        FakePi(_scenario("08_lwt")).run(linger=0)
        time.sleep(3)
        assert {"state": "offline"} in got                          # LWT
    finally:
        sub.loop_stop()
        sub.disconnect()
