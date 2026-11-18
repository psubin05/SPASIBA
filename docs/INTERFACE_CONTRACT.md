# Pi–Server 인터페이스 계약

기준 문서는 [서버 인터페이스 v0.4](server_interface.md)다. 아래 규칙은 통합 브랜치에서 실행하는 계약이다.

| 토픽 | 방향 | 보관 |
| --- | --- | --- |
| `spasiba/{camera_id}/event` | Pi → 서버 | 일반 메시지 |
| `spasiba/{camera_id}/status` | Pi → 서버 | retained |
| `spasiba/{camera_id}/crop_request` | 서버 → Pi | 일반 메시지 |
| `spasiba/{camera_id}/crop` | Pi → 서버 | 일반 메시지 |

MQTT는 UTF-8 JSON, QoS 1을 사용한다. Pi 클라이언트 ID는 `spasiba-{camera_id}`, 서버는 `spasiba-cloud`다. 서버 구독은 `spasiba/+/event`, `spasiba/+/status`, `spasiba/+/crop`이다. LAN 또는 클라우드 연결은 브로커 인증서를 검증하는 TLS 8883과 노드별 계정을 사용한다. ACL은 Pi별 발행/구독 대상을 자기 카메라 토픽으로 제한한다. 로컬 시뮬레이션은 루프백 바인딩의 1883을 쓴다.

## 식별자와 이벤트

| 필드 | 형식과 의미 |
| --- | --- |
| `camera_id` | `CAM-{floor}-{숫자 2자리}`, 예: `CAM-B2-01` |
| `slot_id` | `{floor}-{zone}-{숫자 2자리}`, 예: `B2-A-03` |
| `zone_id` | `{floor}-{zone}`, 예: `B2-A`. 서버가 주차면에서 조회한다. |
| `event_id` | Pi가 생성하는 UUID v4 문자열. 동일 이벤트의 재전송과 재시작 후에도 같은 ID를 쓴다. |
| `plate_number` | 선택 지역명 17개, ASCII 숫자 2~3자리, OCR `USE_CHARS` 용도 문자 1개, ASCII 숫자 4자리. NFC 정규화, 전각 숫자 변환, 공백·하이픈·가운뎃점 제거 후 전체 문자열을 검사한다. |
| `recognized_at` | 인식 시각. 오프셋 또는 Z를 포함한 ISO 8601. 밀리초 허용. |
| `votes`, `frames` | 선택. Pi가 최근 최대 10개 읽기 중 합의 번호의 표 수와 유효 읽기 수를 순서대로 보낸다. |
| `kind` | 선택. 기본값 `confirm`. 서버는 기존 `recheck` 값도 수신한다. |

```json
{
  "event_id": "3f2c9a1e-5b7d-4c1a-9f0e-2d8b6a4c1e77",
  "plate_number": "12가3456",
  "camera_id": "CAM-B2-01",
  "slot_id": "B2-A-03",
  "recognized_at": "2026-11-18T14:03:21.000+09:00",
  "votes": 5,
  "frames": 7,
  "kind": "confirm"
}
```

`parking_slot.camera_id`가 담당 카메라를 결정한다. 같은 카메라에 여러 구역의 주차면을 등록할 수 있다. `camera.zone_id`는 기존 스키마의 설치 구역 메타데이터다. 이벤트 본문의 구형 `zone_id`는 서버가 무시한다. 번호판 예시는 `12가3456`, `123가4567`, `서울12가3456`, `경기71아3535`다.

토픽과 본문의 카메라가 일치해야 하며, 등록된 주차면의 담당 카메라여야 한다. 서버는 식별·형식 검증에 실패한 이벤트를 `valid=false`와 사유로 저장한다. 식별할 수 없는 이벤트와 JSON 파싱 실패는 로그에 기록한다. PostgreSQL 기본 키가 같은 `event_id`의 중복 삽입을 막는다. Pi는 성공 PUBACK 후 SQLite Outbox에서 해당 이벤트를 제거한다. PUBACK은 브로커의 수신 확인이고, DB 저장과 매칭은 서버 로그와 조회 API에서 확인한다.

시연에서는 `publish_on_consensus=true`, `min_votes=5`로 설정한다. 유효 합의 번호와 단일 후보 주차면이 있어야 한다. 같은 칸의 복수 트랙, 겹치는 ROI로 인한 모호함, 상충하는 현재 읽기는 발행을 보류한다. 마지막으로 발행한 주차면·번호판 조합은 SQLite에서 중복 발행을 막는다. 시연 모드는 OCR의 프레임 합의를 사용하며 빈 칸·정차 상태는 판단 범위에 포함되지 않는다.

## Status와 Crop

- 연결 시 `{"state":"online","ts":"2026-11-18T14:03:21+09:00"}`, 정상 종료 때 같은 형식으로 `offline`을 발행한다. 비정상 끊김은 브로커가 retained LWT `{"state":"offline"}`을 발행한다. 서버는 마지막 상태를 메모리와 로그에 기록한다.
- 보류 120초 후 서버가 확인 항목을 생성한다. 서버 `CROP_ENABLED=true`일 때만 해당 확인 항목의 최근 유효 읽기를 지정해 `request_id`, `event_id`, `slot_id`, `reason: "unmatched"`를 보낸다.
- Pi `crop_enabled=true`일 때 해당 슬롯과 이벤트의 JPEG가 메모리에 있고 TTL(기본 600초) 안이면 세 ID, `captured_at`(시간대 포함), `image_jpeg_base64`를 보낸다. Pi는 JPEG 긴 변을 640px 이하로 제한하고 서버와 Pi 모두 100,000바이트 상한을 적용한다.
- 서버는 해당 요청의 카메라와 세 ID가 일치하는 정상 응답을 확인 항목에 첨부한다. 캐시 만료·누락·ID 불일치일 때 Pi는 무응답이며, 확인 항목은 사진 없이 바로 생긴다. 관리자 화면, 출차 연동 삭제와 명시적 오류 응답은 [결정 안건](DECISIONS_NEEDED.md)에 있다.

## REST

| 요청 | 구현 |
| --- | --- |
| `POST /entries` | 번호판과 선택 입차 시각. 201 세션, 409 진행 중 중복, 422 입력 오류 |
| `POST /exits` | 번호판 또는 세션 ID로 출차. 200 종료 및 현재 배정 종료, 404 세션 없음 |
| `GET /entries?state=ACTIVE` | 상태별 세션 및 현재 칸 조회. 상태 필터는 선택 |
| `GET /vehicles/{plate}/last-location` | 번호판 URL 인코딩. `CONFIRMED`와 칸·층·구역·노드, `PENDING` 또는 404 |
| `GET /health` | DB 상태와 MQTT 구독 준비 상태 |
| `/qr/{location_id}`, `/route`, `/map`, `/admin/reviews` 관련 경로 | 501. 경로와 응답 스펙은 서버 인터페이스 초안 참조 |

정확 일치와 단일 한 글자 차이 후보의 5표 이상 매칭 규칙을 유지한다. 입차 전 이벤트는 이벤트 기반으로 조회될 수 있다(`source: "event"`). 보류 중이라면 입차 등록 시 재매칭하며, 세션 기반 결과(`source: "session"`)로 확인할 수 있다.
