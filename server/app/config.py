"""환경변수로 읽는 서버 설정. 값은 .env.example 참고."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    mqtt_enabled: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    mqtt_tls: bool
    admin_token: str | None
    timezone: str
    match_min_votes: int = 5           # 매칭 규칙 ②: 한 글자 차이 확정에 필요한 votes
    match_pending_seconds: float = 120  # 매칭 규칙 ④: 보류 → 관리자 확인까지
    crop_dir: str = "crops"             # crop JPEG 저장 폴더 (커밋 금지, .gitignore)
    crop_enabled: bool = False
    mqtt_ca: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./spasiba_dev.db"),
            mqtt_enabled=_bool(os.getenv("MQTT_ENABLED"), False),
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_username=os.getenv("MQTT_USERNAME") or None,
            mqtt_password=os.getenv("MQTT_PASSWORD") or None,
            mqtt_tls=_bool(os.getenv("MQTT_TLS"), False),
            admin_token=os.getenv("ADMIN_TOKEN") or None,
            timezone=os.getenv("TIMEZONE", "Asia/Seoul"),
            match_min_votes=int(os.getenv("MATCH_MIN_VOTES", "5")),
            match_pending_seconds=float(os.getenv("MATCH_PENDING_SECONDS", "120")),
            crop_dir=os.getenv("CROP_DIR", "crops"),
            crop_enabled=_bool(os.getenv("CROP_ENABLED"), False),
            mqtt_ca=os.getenv("MQTT_CA") or None,
        )
