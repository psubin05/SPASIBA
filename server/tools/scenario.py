"""가짜 Pi 시나리오 파일 읽기·검사 (인터페이스 v0.4: 카메라는 구역에 묶이지 않음)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from tools.fake_pi_messages import is_valid_plate

SCENARIO_DIR = Path(__file__).parent / "scenarios"
STEP_TYPES = {"event", "wait", "status", "disconnect"}
SLOT_RE = re.compile(r"[A-Za-z0-9]+-[A-Za-z0-9]+-[0-9]{2}")  # {zone_id}-{번호2자리}


class ScenarioError(ValueError):
    pass


def all_scenarios() -> list[Path]:
    return sorted(SCENARIO_DIR.glob("*.json"))


def load_scenario(path: Path) -> dict:
    path = Path(path)
    try:
        sc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"{path.name}: 읽을 수 없음 ({exc})") from exc
    try:
        validate_scenario(sc)
    except ScenarioError as exc:
        raise ScenarioError(f"{path.name}: {exc}") from exc
    return sc


def _check_plate(plate, where: str, allow_invalid: bool = False) -> None:
    if not isinstance(plate, str) or not plate:
        raise ScenarioError(f"{where}: plate_number 없음")
    if not allow_invalid and not is_valid_plate(plate):
        raise ScenarioError(f"{where}: 번호 형식 오류 {plate!r} (일부러면 expect_invalid: true)")


def validate_scenario(sc: dict) -> None:
    if not isinstance(sc, dict):
        raise ScenarioError("시나리오는 JSON 객체여야 함")
    for key in ("name", "cameras", "steps"):
        if key not in sc:
            raise ScenarioError(f"필수 키 없음: {key}")

    cameras: set[str] = set()
    for cam in sc["cameras"]:
        if not isinstance(cam, dict) or not isinstance(cam.get("camera_id"), str):
            raise ScenarioError(f"cameras 항목에 camera_id 필요: {cam!r}")
        cameras.add(cam["camera_id"])
    if not cameras:
        raise ScenarioError("cameras가 비어 있음")

    for i, entry in enumerate(sc.get("entries", [])):
        _check_plate(entry.get("plate_number") if isinstance(entry, dict) else None,
                     f"entries[{i}]")

    refs: dict[str, str] = {}          # event_ref → camera_id
    disconnected: set[str] = set()
    for i, step in enumerate(sc["steps"]):
        where = f"steps[{i}]"
        if not isinstance(step, dict):
            raise ScenarioError(f"{where}: 객체여야 함")
        kind = step.get("type")
        if kind not in STEP_TYPES:
            raise ScenarioError(f"{where}: 모르는 type {kind!r}")

        if kind == "wait":
            seconds = step.get("seconds")
            if not isinstance(seconds, (int, float)) or seconds < 0:
                raise ScenarioError(f"{where}: seconds는 0 이상 숫자")
            continue

        if kind == "event" and "repeat_of" in step:
            if step["repeat_of"] not in refs:
                raise ScenarioError(f"{where}: repeat_of {step['repeat_of']!r}가 앞에 정의되지 않음")
            if refs[step["repeat_of"]] in disconnected:
                raise ScenarioError(f"{where}: 이미 끊긴 카메라의 이벤트 재발행")
            continue

        camera_id = step.get("camera_id")
        if camera_id not in cameras:
            raise ScenarioError(f"{where}: cameras에 없는 camera_id {camera_id!r}")
        if camera_id in disconnected:
            raise ScenarioError(f"{where}: {camera_id}는 앞에서 disconnect됨 (재연결은 지원 안 함)")
        if kind == "disconnect":
            disconnected.add(camera_id)

        if kind == "status" and step.get("state") not in ("online", "offline"):
            raise ScenarioError(f"{where}: state는 online|offline")

        if kind == "event":
            slot_id = step.get("slot_id")
            if not isinstance(slot_id, str) or not SLOT_RE.fullmatch(slot_id):
                raise ScenarioError(f"{where}: slot_id {slot_id!r} 형식 오류 ({{zone_id}}-{{번호2자리}})")
            _check_plate(step.get("plate_number"), where, bool(step.get("expect_invalid")))
            ref = step.get("event_ref")
            if ref is not None:
                if ref in refs:
                    raise ScenarioError(f"{where}: event_ref {ref!r} 중복")
                refs[ref] = camera_id
