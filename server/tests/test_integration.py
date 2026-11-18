"""통합 테스트 (작업 10, 로컬): 시나리오 9개를 가짜 Pi → 서버 수신기 → 매칭 → 차량 조회 API로 돌린다.

브로커 대신 함수로 직접 잇는다 (가짜 Pi 발행 → MessageHandler.handle, 서버 crop_request → 가짜 Pi).
시나리오의 wait는 가짜 시계로 건너뛰고, 그때마다 서버의 보류 점검(tick)을 부른다.
실제 브로커·PostgreSQL을 거치는 확인은 README의 '로컬 통합 실행'을 따른다.
"""
import json
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest

import tools.fake_pi as fake_pi_module
from app.models import EntrySession, ParkingEvent, ReviewQueue, SlotAssignment
from app.mqtt_listener import MessageHandler
from tools.fake_pi import FakePi
from tools.scenario import all_scenarios, load_scenario


def run_scenario(app_client, sc, monkeypatch):
    clock = [datetime.now(ZoneInfo("Asia/Seoul"))]
    results = []
    fp_box = []

    def server_publish(topic, payload):  # 서버 → Pi (crop_request)
        camera_id = topic.split("/")[1]
        fp_box[0].handle_crop_request(camera_id, json.dumps(payload).encode())

    handler = MessageHandler(app_client.app.state.settings, app_client.app.state.db, server_publish)

    def pi_publish(topic, payload, retain):  # Pi → 서버
        results.append((topic, handler.handle(topic, json.dumps(payload, ensure_ascii=False).encode(), clock[0])))

    def fake_sleep(seconds):
        clock[0] += timedelta(seconds=seconds)
        handler.tick(clock[0])

    monkeypatch.setattr(fake_pi_module.time, "sleep", fake_sleep)
    for entry in sc.get("entries", []):
        assert app_client.post("/entries", json={"plate_number": entry["plate_number"]}).status_code == 201
    fp = FakePi(sc, publish=pi_publish)
    fp_box.append(fp)
    fp.run(linger=0)
    return handler, results


@pytest.mark.parametrize("path", all_scenarios(), ids=lambda p: p.stem)
def test_scenario_end_to_end(app_client, monkeypatch, path):
    sc = load_scenario(path)
    handler, results = run_scenario(app_client, sc, monkeypatch)
    assert "error" not in [r for _, r in results]
    with app_client.app.state.db.SessionLocal() as db:
        for exp in sc["expect"]:
            r = app_client.get(f"/vehicles/{quote(exp['plate_number'])}/last-location")
            body = r.json()
            assert r.status_code == 200 and body["status"] == exp["status"], (exp, body)
            if "slot_id" in exp:
                assert body["slot_id"] == exp["slot_id"]
            if "method" in exp:
                session = db.query(EntrySession).filter_by(plate_norm=exp["plate_number"], state="ACTIVE").one()
                a = db.query(SlotAssignment).filter_by(session_id=session.session_id, ended_at=None).one()
                assert a.method == exp["method"]

        name = sc["name"]
        if name == "05_no_entry":
            assert body["source"] == "event"
        if name == "06_duplicate_event_id":
            assert [r for t, r in results if t.endswith("/event")] == ["assigned", "duplicate"]
            assert db.query(ParkingEvent).count() == 1
        if name == "07_slot_new_car":
            assert db.query(SlotAssignment).filter(SlotAssignment.ended_at.isnot(None)).count() == 1
        if name == "08_lwt":
            assert handler.camera_status["CAM-B2-01"]["state"] == "online"  # LWT는 브로커가 냄 (실제 브로커 테스트)
        if name == "09_crop_request":
            review = db.query(ReviewQueue).one()
            assert review.status == "OPEN" and review.crop_path, "crop_request → 가짜 Pi crop → 저장"
            assert review.candidates[0]["plate_number"] == "78라1234"
            assert "crop_saved" in [r for _, r in results]
        if name in ("03_edit1_low_votes", "04_two_similar"):
            assert db.query(ReviewQueue).count() == 0  # 120초 전이므로 아직 보류
