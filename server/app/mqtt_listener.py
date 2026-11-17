"""MQTT 수신기 (작업 6). 토픽은 docs/server_interface.md v0.4 2장: spasiba/{camera_id}/{kind}.

- MessageHandler: 메시지 한 건 처리 + 주기 점검(보류 120초 → crop_request). paho 없이 테스트한다.
- MqttListener: paho 연결·구독·재연결, 점검 스레드. MQTT_ENABLED=false 이면 아무것도 하지 않는다.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from . import parking
from .config import Settings
from .db import Database

log = logging.getLogger("spasiba.mqtt")

SUBSCRIPTIONS = [
    ("spasiba/+/event", 1),
    ("spasiba/+/status", 1),
    ("spasiba/+/crop", 1),
]
CLIENT_ID = "spasiba-cloud"   # Pi는 spasiba-{camera_id} → 겹치지 않음
TICK_SECONDS = 5.0


class MessageHandler:
    def __init__(self, settings: Settings, database: Database, publish: Callable[[str, dict], None]):
        self.settings, self.database, self.publish = settings, database, publish
        self.camera_status: dict[str, dict] = {}  # 카메라별 마지막 status (메모리, 재시작하면 retained로 다시 받음)

    def handle(self, topic: str, payload: bytes, now: datetime) -> str:
        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "spasiba" or parts[2] not in ("event", "status", "crop"):
            log.warning("모르는 토픽 무시: %s", topic)
            return "ignored"
        camera_id, kind = parts[1], parts[2]
        try:
            body = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            log.warning("JSON이 아닌 메시지 무시: %s %r", topic, payload[:80])
            return "rejected" if kind == "event" else "ignored"
        try:
            if kind == "status":
                return self._status(camera_id, body, now)
            with self.database.SessionLocal() as db:
                if kind == "event":
                    result = parking.handle_event(db, self.settings, camera_id, body, now)
                    log.info("이벤트 %s %s → %s", camera_id, body.get("event_id") if isinstance(body, dict) else "?",
                             result)
                    return result
                return "crop_saved" if parking.handle_crop(db, self.settings, camera_id, body) else "crop_ignored"
        except Exception:
            log.exception("메시지 처리 중 오류: %s", topic)
            return "error"

    def _status(self, camera_id: str, body, now: datetime) -> str:
        if not isinstance(body, dict) or body.get("state") not in ("online", "offline"):
            return "ignored"
        ts = body.get("ts")
        self.camera_status[camera_id] = {
            "state": body["state"], "ts": ts if isinstance(ts, str) else None,
            "lwt": body["state"] == "offline" and "ts" not in body,  # ts 없는 offline = 비정상 끊김(LWT)
            "received_at": parking.iso(now, self.settings)}
        level = logging.WARNING if self.camera_status[camera_id]["lwt"] else logging.INFO
        log.log(level, "카메라 %s %s%s", camera_id, body["state"], " (LWT)" if self.camera_status[camera_id]["lwt"] else "")
        return "status"

    def tick(self, now: datetime) -> int:
        """보류 시간이 지난 칸을 관리자 확인으로 넘기고 crop_request를 보낸다. 보낸 개수."""
        try:
            with self.database.SessionLocal() as db:
                requests = parking.check_timeouts(db, self.settings, now)
        except Exception:
            log.exception("보류 점검 중 오류")
            return 0
        for camera_id, payload in requests:
            self.publish(f"spasiba/{camera_id}/crop_request", payload)
            log.info("crop_request %s %s", camera_id, payload["request_id"])
        return len(requests)


class MqttListener:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.client = None
        self.connected = False
        self.handler = MessageHandler(settings, database, self._publish)
        self._stop = threading.Event()
        self._ticker: threading.Thread | None = None

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self.settings.timezone))

    def start(self) -> None:
        if not self.settings.mqtt_enabled:
            log.info("MQTT 비활성화 (MQTT_ENABLED=false)")
            return
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, clean_session=False)
        if self.settings.mqtt_username:
            client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)
        if self.settings.mqtt_tls:
            client.tls_set()
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.suppress_exceptions = True
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
        client.loop_start()
        self.client = client
        self._ticker = threading.Thread(target=self._tick_loop, name="spasiba-match-tick", daemon=True)
        self._ticker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ticker is not None:
            self._ticker.join(timeout=2)
        if self.client is not None:
            self.client.disconnect()
            self.client.loop_stop()

    def _tick_loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            if self.connected:
                self.handler.tick(self._now())

    def _publish(self, topic: str, payload: dict) -> None:
        if self.client is None:
            log.warning("MQTT 클라이언트 없음, 발행 못 함: %s", topic)
            return
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=False)

    # --- 콜백 ---
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if self.connected:
            client.subscribe(SUBSCRIPTIONS)
            log.info("MQTT 연결, 구독: %s", [t for t, _ in SUBSCRIPTIONS])
        else:
            log.warning("MQTT 연결 실패: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        log.warning("MQTT 연결 끊김: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        log.info("수신 %s (%d bytes)", msg.topic, len(msg.payload))
        self.handler.handle(msg.topic, msg.payload, self._now())
