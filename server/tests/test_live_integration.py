"""Real Mosquitto, PostgreSQL, subscriber and FastAPI routes. No OCR models."""
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import paho.mqtt.client as mqtt
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app import plates
from app.main import create_app
from app.models import MatchPending, ParkingEvent, ReviewQueue, SlotAssignment
from tools.fake_pi import FakePi
from tools.fake_pi_messages import build_event
from tools.scenario import load_scenario

SERVER = Path(__file__).resolve().parents[1]
CAMERA = "CAM-B2-01"
PLATE = "12가3456"
SLOT = "B2-A-03"


def wait_for(predicate: Callable, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    pytest.fail("Timed out waiting for " + predicate.__name__)


@pytest.fixture
def broker(tmp_path):
    executable = os.environ.get("SPASIBA_TEST_MOSQUITTO") or shutil.which("mosquitto")
    if not executable:
        pytest.skip("Mosquitto executable needed")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = tmp_path / "mosquitto.conf"
    config.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n")
    log_path = tmp_path / "broker.log"
    with log_path.open("w") as log:
        process = subprocess.Popen([executable, "-c", str(config)], stdout=log, stderr=log)
        try:
            def broker_accepts_connections():
                if process.poll() is not None:
                    pytest.fail(log_path.read_text())
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        return True
                except OSError:
                    return False

            wait_for(broker_accepts_connections)
            yield port
        finally:
            process.terminate()
            process.wait(timeout=5)


@pytest.fixture
def pg_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    schema = "integration_" + uuid.uuid4().hex
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        # The seed has its own BEGIN/COMMIT, so strip those transaction markers.
        seed = (SERVER / "db" / "map_seed.sql").read_text(encoding="utf-8")
        seed = "\n".join(line for line in seed.splitlines() if line.strip() not in {"BEGIN;", "COMMIT;"})
        conn.exec_driver_sql(seed)
    try:
        yield make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(
            hide_password=False
        )
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.fixture
def live_api(settings, pg_url, broker, request):
    crop_enabled = getattr(request, "param", False)
    api = create_app(replace(settings, database_url=pg_url, mqtt_enabled=True, mqtt_host="127.0.0.1",
                             mqtt_port=broker, crop_enabled=crop_enabled,
                             match_pending_seconds=0.1 if crop_enabled else 120))
    with TestClient(api) as client:
        wait_for(lambda: client.get("/health").json() == {"status": "ok", "db": True, "mqtt": "connected"})
        yield client
    api.state.db.engine.dispose()


def entry(api, plate=PLATE):
    assert api.post("/entries", json={"plate_number": plate}).status_code == 201


def location(api, plate=PLATE):
    response = api.get(f"/vehicles/{plate}/last-location")
    assert response.status_code == 200, response.text
    return response.json()


def assert_location(api, plate=PLATE, slot=SLOT):
    body = location(api, plate)
    assert (body["plate_number"], body["status"], body["slot_id"]) == (plate, "CONFIRMED", slot)


def rows(api, model):
    with api.app.state.db.SessionLocal() as db:
        return db.scalars(select(model)).all()


def test_fake_pi_persists_event_once_and_matches(live_api, broker, caplog):
    caplog.set_level(logging.INFO, logger="spasiba.mqtt")
    entry(live_api)
    scenario = load_scenario(SERVER / "tools/scenarios/06_duplicate_event_id.json")
    pi = FakePi(scenario, host="127.0.0.1", port=broker)
    events = [msg["payload"] for msg in pi.run(linger=0) if msg["topic"].endswith("/event")]
    assert len(events) == 2 and events[0]["event_id"] == events[1]["event_id"]
    wait_for(lambda: "→ duplicate" in caplog.text)
    assert [(e.event_id, e.valid) for e in rows(live_api, ParkingEvent)] == [(events[0]["event_id"], True)]
    assert rows(live_api, SlotAssignment)[0].method == "EXACT"
    assert_location(live_api)


def test_subscriber_receives_broker_lwt(live_api, broker):
    scenario = load_scenario(SERVER / "tools/scenarios/08_lwt.json")
    entry(live_api, "78라1234")
    FakePi(scenario, host="127.0.0.1", port=broker).run(linger=0)
    status = live_api.app.state.mqtt.handler.camera_status
    wait_for(lambda: status.get(CAMERA, {}).get("lwt"))
    assert (status[CAMERA]["state"], status[CAMERA]["ts"]) == ("offline", None)
    assert_location(live_api, "78라1234", "B2-A-04")


def pair(plate, bbox=(10, 10, 50, 30), count=5, **result):
    return ({"bbox": bbox, "plate_text": plate, "format_valid": True, **result},
            SimpleNamespace(readings=[(plate, 0.9)] * count))


def runtime_for(tmp_path, port, **settings):
    from edge_cloud.config import Config
    from edge_cloud.runtime import EdgeRuntime

    return EdgeRuntime(Config(camera_id=CAMERA, host="127.0.0.1", port=port, tls=False,
                              database=str(tmp_path / "edge.sqlite3"), publish_on_consensus=True, **settings))


def test_subscriber_replays_qos1_after_reconnect(live_api, broker, tmp_path):
    entry(live_api)
    listener = live_api.app.state.mqtt
    listener.client.disconnect()
    listener.client.loop_stop()
    wait_for(lambda: live_api.get("/health").json()["mqtt"] == "disconnected")
    with closing(runtime_for(tmp_path, broker, single_slot=SLOT)) as edge:
        wait_for(edge.transport.connected.is_set)
        event, = edge.observe([pair(PLATE)])
        wait_for(lambda: edge.store.count() == 0)
        assert not rows(live_api, ParkingEvent)
    listener.client.reconnect()
    listener.client.loop_start()
    wait_for(lambda: listener.connected)
    wait_for(lambda: len(rows(live_api, SlotAssignment)) == 1)
    assert_location(live_api)
    assert rows(live_api, ParkingEvent)[0].event_id == event["event_id"]


def test_real_edge_persists_and_matches_across_two_zones(live_api, broker, tmp_path):
    second_plate = "서울123나4567"
    entry(live_api)
    entry(live_api, second_plate)
    rois = {SLOT: [[0, 0], [100, 0], [100, 100], [0, 100]],
            "B2-B-03": [[100, 0], [200, 0], [200, 100], [100, 100]]}
    with closing(runtime_for(tmp_path, broker, rois=rois)) as edge:
        wait_for(edge.transport.connected.is_set)
        status = live_api.app.state.mqtt.handler.camera_status
        wait_for(lambda: status.get(CAMERA, {}).get("state") == "online")
        assert edge.observe([pair(PLATE, count=4)]) == []
        assert edge.observe([pair(PLATE), pair("34나5678")]) == []
        observation = [pair(PLATE), pair(second_plate, (110, 10, 150, 30))]
        events = edge.observe(observation)
        assert [event["slot_id"] for event in events] == [SLOT, "B2-B-03"]
        assert all("zone_id" not in event for event in events)
        assert edge.observe(observation) == []
        wait_for(lambda: edge.store.count() == 0)  # Broker PUBACK removed both rows.
        wait_for(lambda: len(rows(live_api, SlotAssignment)) == 2)
        assert_location(live_api)
        assert_location(live_api, second_plate, "B2-B-03")
        assert {event.slot_id: event.zone_id for event in rows(live_api, ParkingEvent)} == {
            SLOT: "B2-A", "B2-B-03": "B2-B"
        }
        # Reproduce the documented same-slot re-entry limitation.
        assert live_api.post("/exits", json={"plate_number": PLATE}).status_code == 200
        assert live_api.get(f"/vehicles/{PLATE}/last-location").status_code == 404
        entry(live_api)
        assert edge.observe([pair(PLATE)]) == []
        assert location(live_api)["status"] == "PENDING"
    wait_for(lambda: status[CAMERA]["state"] == "offline")
    assert not status[CAMERA]["lwt"]


def test_invalid_messages_and_event_before_entry(live_api, broker):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect("127.0.0.1", broker)
    client.loop_start()
    try:
        invalid = [("12뷁3456", CAMERA, SLOT), (PLATE, "CAM-B2-A-01", SLOT), (PLATE, CAMERA, "B2-Z-99")]
        for plate, camera_id, slot_id in [*invalid, (PLATE, CAMERA, SLOT)]:
            event = build_event(camera_id=camera_id, slot_id=slot_id, plate_number=plate, votes=5, frames=5)
            info = client.publish(f"spasiba/{camera_id}/event", json.dumps(event), qos=1)
            info.wait_for_publish(timeout=3)
            assert info.is_published()
        wait_for(lambda: len(rows(live_api, ParkingEvent)) == 4)
        assert sum(event.valid for event in rows(live_api, ParkingEvent)) == 1
        assert location(live_api)["source"] == "event"
        assert not rows(live_api, SlotAssignment)
        entry(live_api)
        assert_location(live_api)
        assert rows(live_api, SlotAssignment)[0].method == "EXACT"
    finally:
        client.disconnect()
        client.loop_stop()


@pytest.mark.parametrize("live_api", [True], indirect=True)
@pytest.mark.parametrize("crop_ttl,expect_image", [(600, True), (0.05, False)])
def test_real_edge_crop_and_expiry(live_api, broker, tmp_path, crop_ttl, expect_image, caplog):
    import cv2
    import numpy as np

    caplog.set_level(logging.INFO, logger="edge_cloud.transport")
    with closing(runtime_for(tmp_path, broker, single_slot=SLOT, crop_enabled=True, crop_ttl=crop_ttl)) as edge:
        wait_for(edge.transport.connected.is_set)
        event, = edge.observe([pair(PLATE, crop=np.zeros((40, 120, 3), dtype=np.uint8))])
        wait_for(lambda: "crop response queued" in caplog.text if expect_image
                 else "crop unavailable/expired/event mismatch" in caplog.text)
        if expect_image:
            wait_for(lambda: any(review.crop_path for review in rows(live_api, ReviewQueue)))
        review, = rows(live_api, ReviewQueue)
        assert review.status == "OPEN" and review.read_plates[0]["event_id"] == event["event_id"]
        assert not rows(live_api, MatchPending)
        assert not rows(live_api, SlotAssignment)
        assert bool(review.crop_path) == expect_image
        if expect_image:
            jpeg = Path(review.crop_path)
            assert jpeg.stat().st_size <= 100_000
            assert cv2.imread(str(jpeg)).shape == (40, 120, 3)


def test_edge_and_server_plate_validation_agree():
    from edge_cloud.events import PATTERN, normalize_plate
    from postprocessing import REGIONS, USE_CHARS, extract_plate

    assert (REGIONS, USE_CHARS) == (plates.REGIONS, plates.USE_CHARS)
    accepted = ("12가3456", "123가4567", "서울12가3456", "경기71아3535", "서울 １２-가·３４５６")
    rejected = ("12뷁3456", "서울12가345", "경북1가3456", "오류12가3456", "x12가3456", "")
    for expected, values in ((True, accepted), (False, rejected)):
        for raw in values:
            norm = normalize_plate(raw)
            assert norm == plates.normalize(raw)
            assert bool(PATTERN.fullmatch(norm)) == plates.is_valid(norm) == expected, raw
    assert extract_plate(accepted[-1]) == ("서울12가3456", True)
