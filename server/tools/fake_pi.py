"""가짜 Pi: 시나리오대로 MQTT event·status를 발행하고 crop_request에 더미 crop으로 응답한다.

    python -m tools.fake_pi tools/scenarios/01_exact.json [--host localhost --port 1883]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

import paho.mqtt.client as mqtt

from tools.fake_pi_messages import build_crop, build_event, build_status, now_kst, topic
from tools.scenario import ScenarioError, load_scenario

log = logging.getLogger("fake_pi")

PublishFn = Callable[[str, dict, bool], None]


class FakePi:
    def __init__(self, scenario: dict, *, host: str = "localhost", port: int = 1883,
                 username: str | None = None, password: str | None = None, tls: bool = False,
                 connect_timeout: float = 5.0, publish: PublishFn | None = None):
        self.scenario = scenario
        self.cameras = [c["camera_id"] for c in scenario["cameras"]]
        self.host, self.port = host, port
        self.username, self.password, self.tls = username, password, tls
        self.connect_timeout = connect_timeout
        self._publish_fn = publish
        self._clients: dict[str, mqtt.Client] = {}
        self._connected: set[str] = set()
        self._lock = threading.Lock()
        self.published: list[dict] = []
        self._events_by_ref: dict[str, tuple[str, dict]] = {}
        self._last_event_by_slot: dict[str, str] = {}
        self._pending: dict[str, list] = {}

    # ---- 발행 ----
    def _publish(self, camera_id: str, kind: str, payload: dict, retain: bool = False) -> bool:
        """발행하면 True. 이미 끊긴 카메라면 경고만 하고 False (paho 스레드에서도 호출됨)."""
        t = topic(camera_id, kind)
        with self._lock:
            if camera_id not in self._connected:
                log.warning("%s는 이미 끊김, %s 발행 건너뜀", camera_id, kind)
                return False
            if self._publish_fn is not None:
                self._publish_fn(t, payload, retain)
            else:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                info = self._clients[camera_id].publish(t, body, qos=1, retain=retain)
                self._pending.setdefault(camera_id, []).append(info)
            self.published.append({"topic": t, "payload": payload, "retain": retain})
        label = payload.get("plate_number") or payload.get("state") or payload.get("request_id", "")
        print(f"→ {t} {label}", flush=True)
        return True

    def _flush(self, camera_id: str, timeout: float = 2.0) -> None:
        """큐에 쌓인 QoS 1 메시지가 실제로 나갈 때까지 기다린다."""
        for info in self._pending.pop(camera_id, []):
            try:
                info.wait_for_publish(timeout=timeout)
            except Exception as exc:  # 연결이 이미 끊긴 경우 등
                log.warning("%s 발행 확인 실패: %s", camera_id, exc)

    # ---- 연결 ----
    def _connect(self, camera_id: str) -> None:
        if self._publish_fn is not None:
            self._connected.add(camera_id)
            return
        ok = threading.Event()
        result: dict = {}
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-{camera_id}")
        if self.username:
            client.username_pw_set(self.username, self.password)
        if self.tls:
            client.tls_set()
        client.will_set(topic(camera_id, "status"),
                        json.dumps(build_status("offline")), qos=1, retain=True)

        def on_connect(c, userdata, flags, reason_code, properties):
            result["rc"] = reason_code
            if not reason_code.is_failure:
                c.subscribe(topic(camera_id, "crop_request"), qos=1)
            ok.set()

        def on_message(c, userdata, msg):
            self._on_crop_message(camera_id, msg.payload)

        client.on_connect = on_connect
        client.on_message = on_message
        client.suppress_exceptions = True  # 콜백 예외로 네트워크 스레드가 죽지 않게
        client.connect_timeout = self.connect_timeout
        try:
            client.connect(self.host, self.port, keepalive=30)
        except OSError as exc:
            raise ConnectionError(f"{self.host}:{self.port} 연결 실패 ({exc})") from exc
        client.loop_start()
        if not ok.wait(self.connect_timeout) or result["rc"].is_failure:
            client.loop_stop()
            client.disconnect()
            reason = result.get("rc", f"{self.connect_timeout}초 동안 응답 없음")
            raise ConnectionError(f"{self.host}:{self.port} 연결 실패 ({reason})")
        self._clients[camera_id] = client
        self._connected.add(camera_id)

    def _close(self, camera_id: str, abrupt: bool) -> None:
        if camera_id not in self._connected:
            return
        if not abrupt:
            self._publish(camera_id, "status", build_status("offline", ts=now_kst()), retain=True)
        self._flush(camera_id)
        with self._lock:
            self._connected.discard(camera_id)
            client = self._clients.pop(camera_id, None)
        if abrupt:
            # DISCONNECT 패킷 없이 소켓만 닫는다 → 브로커가 LWT(offline)를 발행
            print(f"✕ {camera_id} 비정상 끊김 (LWT 기대)", flush=True)
            if client is not None:
                client.loop_stop()
                sock = client.socket()
                if sock is not None:
                    sock.close()
        elif client is not None:
            client.disconnect()
            client.loop_stop()

    # ---- crop 응답 ----
    def handle_crop_request(self, camera_id: str, raw: bytes) -> dict | None:
        try:
            req = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            log.warning("crop_request JSON 오류, 무시: %r", raw[:80])
            return None
        if not isinstance(req, dict) or not req.get("request_id") or not req.get("slot_id"):
            log.warning("crop_request 필드 부족, 무시: %r", req)
            return None
        if camera_id not in self.cameras:
            log.warning("모르는 카메라의 crop_request, 무시: %s", camera_id)
            return None
        # 실제 Pi처럼: 요청 event_id가 그 칸의 마지막 이벤트와 같을 때만 응답 (다르거나 없으면 무응답)
        latest = self._last_event_by_slot.get(req["slot_id"])
        if latest is None or req.get("event_id") != latest:
            log.warning("crop_request event_id 불일치, 응답 안 함: %s %s", req["slot_id"], req.get("event_id"))
            return None
        crop = build_crop(req)
        return crop if self._publish(camera_id, "crop", crop) else None

    def _on_crop_message(self, camera_id: str, raw: bytes) -> dict | None:
        """paho 콜백용: 어떤 예외도 밖으로 내보내지 않는다."""
        try:
            return self.handle_crop_request(camera_id, raw)
        except Exception:
            log.exception("crop_request 처리 중 오류, 무시")
            return None

    # ---- 실행 ----
    def _run_step(self, step: dict) -> None:
        kind = step["type"]
        if kind == "wait":
            time.sleep(step["seconds"])
        elif kind == "event":
            if "repeat_of" in step:
                camera_id, payload = self._events_by_ref[step["repeat_of"]]
            else:
                camera_id = step["camera_id"]
                payload = build_event(
                    camera_id=camera_id, slot_id=step["slot_id"],
                    plate_number=step["plate_number"], votes=step.get("votes"),
                    frames=step.get("frames"), kind=step.get("kind"))
                if step.get("event_ref"):
                    self._events_by_ref[step["event_ref"]] = (camera_id, payload)
                self._last_event_by_slot[payload["slot_id"]] = payload["event_id"]
            self._publish(camera_id, "event", payload)
        elif kind == "status":
            self._publish(step["camera_id"], "status", build_status(step["state"]), retain=True)
        elif kind == "disconnect":
            self._close(step["camera_id"], abrupt=bool(step.get("abrupt")))

    def run(self, linger: float = 2.0) -> list[dict]:
        try:
            for camera_id in self.cameras:
                self._connect(camera_id)
                self._publish(camera_id, "status", build_status("online"), retain=True)
            for step in self.scenario["steps"]:
                self._run_step(step)
            if linger > 0 and self._connected:
                time.sleep(linger)  # 이 동안 crop_request 응답
        finally:
            for camera_id in list(self._connected):
                self._close(camera_id, abrupt=False)
        return self.published


def _post_entries(url: str, entries: list[dict]) -> None:
    for entry in entries:
        body = json.dumps({"plate_number": entry["plate_number"]}, ensure_ascii=False).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"입차 {entry['plate_number']} → {resp.status}", flush=True)
        except urllib.error.HTTPError as exc:
            log.warning("입차 %s → HTTP %s (무시)", entry["plate_number"], exc.code)
        except OSError as exc:
            log.warning("입차 API 연결 실패 (무시): %s", exc)
            return


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.fake_pi", description=__doc__.splitlines()[0])
    p.add_argument("scenario")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--username")
    p.add_argument("--password")
    p.add_argument("--tls", action="store_true")
    p.add_argument("--linger", type=float, default=2.0, help="끝난 뒤 crop_request 기다리는 초")
    p.add_argument("--entries-url", help="예: http://localhost:8000/entries")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        sc = load_scenario(args.scenario)
    except ScenarioError as exc:
        print(f"시나리오 오류: {exc}", file=sys.stderr)
        return 1
    print(f"# {sc['name']}: {sc.get('description', '')}", flush=True)
    if args.entries_url:
        _post_entries(args.entries_url, sc.get("entries", []))
    try:
        FakePi(sc, host=args.host, port=args.port, username=args.username,
               password=args.password, tls=args.tls).run(linger=args.linger)
    except ConnectionError as exc:
        print(f"브로커 연결 실패: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
