# 가짜 Pi (`tools/fake_pi.py`) 설계

작성: 2026-11-15 · HANDOFF_server.md 작업 3 · 기준: `docs/server_interface.md` v0.3 2장

## 왜

Pi에는 아직 ROI(slot_id), 정지 확인, MQTT 발행이 없다. 서버 작업 4~7(DB·수신기·매칭)을 실제 메시지로 개발·테스트하려면 인터페이스 2장 형식 그대로 발행하는 대체물이 필요하다.

## 목표 / 하지 않는 것

- 목표: event·status·crop 발행, crop_request 자동 응답, 시나리오 파일 재사용(테스트 포함)
- 하지 않음: 번호판 인식, 실제 이미지 사용(개인정보), 매칭 판단(서버 몫), 입·출차 API 호출 검증(작업 5 이후 연결)
- 실패로 보는 것: 인터페이스 문서와 다른 필드·토픽을 쓰는 것

## 방식 (검토한 것)

| 방식 | 장단점 | 결정 |
|---|---|---|
| 시나리오 JSON + 실행 스크립트 1개 | 테스트에서 같은 파일 재사용, 추가 패키지 없음 | **채택** |
| 시나리오를 파이썬 코드에 직접 | 빠르지만 테스트 재사용 어려움 | 제외 |
| YAML | 읽기 쉬우나 PyYAML 추가 필요 | 제외 |

## 구성

- `tools/fake_pi_messages.py`: 순수 함수. 토픽 만들기, event/status/crop payload 만들기, 번호 형식 검사(지역명 17개 + `\d{2,3}[가-힣]\d{4}`). DB·MQTT 없이 테스트.
- `tools/fake_pi.py`: CLI. 시나리오를 읽어 카메라별 MQTT 클라이언트(LWT=offline, 연결 시 online retained)를 만들고 steps를 순서대로 실행. 끝날 때까지 crop_request 구독 → 더미 JPEG로 crop 응답.
- `tools/scenarios/*.json`: 9개 (HANDOFF 3장 목록. 최종 리뷰 후 08을 `08_lwt`·`09_crop_request`로 나눔: crop_request는 120초 보류 뒤에 오므로 LWT 확인과 한 시나리오에 둘 수 없음).

### 시나리오 형식

```json
{
  "name": "...", "description": "...",
  "cameras": [{"camera_id": "CAM-B2-A-01", "zone_id": "B2-A"}],
  "entries": [{"plate_number": "12가3456"}],
  "steps": [
    {"type": "event", "camera_id": "CAM-B2-A-01", "slot_id": "B2-A-03", "plate_number": "12가3456", "votes": 9, "frames": 10, "event_ref": "e1"},
    {"type": "event", "repeat_of": "e1"},
    {"type": "wait", "seconds": 1},
    {"type": "status", "camera_id": "CAM-B2-A-01", "state": "offline"},
    {"type": "disconnect", "camera_id": "CAM-B2-A-01", "abrupt": true}
  ],
  "expect": [{"plate_number": "12가3456", "status": "CONFIRMED", "slot_id": "B2-A-03", "method": "EXACT"}]
}
```

- `event_ref`/`repeat_of`: 같은 `event_id` 재발행.
- `entries`, `expect`는 fake_pi가 쓰지 않는다(작업 5·10 테스트용 기대값). `--entries-url`을 주면 POST /entries를 시도하고 501이면 경고만.
- 기대값의 숫자 기준은 인터페이스 4장(`votes` ≥ 5, 보류 120초)을 따른다. 6장 체크리스트의 "이벤트 2번"과 다르며 4장을 우선했다.

## 직접 정한 것 (빌더 판단)

- 식별자는 1장 예시(`B2-A`, `CAM-B2-A-01`, `B2-A-03`)를 쓴다. 아직 합의 전.
- 더미 crop: 코드에 넣은 작은 회색 JPEG(번호판 없음).
- 브로커 기본값 `localhost:1883` 익명(개발용 compose와 동일), `--host/--port/--username/--password/--tls` 옵션.
- 실제 브로커 테스트는 1883에 연결 안 되면 skip.
