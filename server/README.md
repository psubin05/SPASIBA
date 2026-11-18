# SPASIBA Cloud 서버

명세서 v1.2의 **Cloud Layer**(MQTT 브로커 + API 서버 + DB)입니다. 인터페이스는 `docs/server_interface.md` **v0.4**를 따릅니다.

| 담당 | 범위 |
|---|---|
| 수꽝 | MQTT 수신, DB, 입차 세션 매칭, 입·출차 API, 차량 조회, 관리자 확인 |
| 떵개 | 지도 데이터, QR 해석, 최단 경로, 지도 API |

> 통합 브랜치의 [실행 가이드](../docs/RUN_INTEGRATION.md), [계약](../docs/INTERFACE_CONTRACT.md), [검증 결과](../docs/INTEGRATION_REPORT.md).

## 만든 것 (2026-11-18, 수꽝)

Pi가 MQTT로 보낸 "이 칸에 이 번호" 이벤트를 받아 **입차 기록과 매칭해 차의 칸을 확정**하고, 차량번호로 위치를 조회하는 서버입니다.

| 구성 | 파일 | 하는 일 |
|---|---|---|
| DB 스키마 | `app/models.py`, `app/models_map.py`, `app/db.py` | 우리 표 5개(`parking_event`, `entry_session`, `slot_assignment`, `match_pending`, `review_queue`) + 수빈 지도 표 6개 미러. "같은 번호 진행 중 세션 1개 / 세션당 현재 칸 1개 / 칸당 현재 차 1대"를 DB가 직접 막음. 시각은 시간대 필수·UTC 저장 |
| 번호 규칙 | `app/plates.py` | 정규화(공백·하이픈·가운뎃점·전각 숫자), 형식 검사(지역명 17개 + 용도 문자 40자, Pi와 동일), 편집 거리(지역명은 1글자) |
| 매칭 판단 | `app/matching.py` | ① 정확히 일치 → `EXACT` ② 한 글자 차이 후보 딱 1대 + votes ≥ 5 → `EDIT1` ③ 그 외 보류 |
| 처리 서비스 | `app/parking.py` | 이벤트 검증·저장(잘못된 이벤트도 `valid=false`로 보관)·중복 제거, 칸 배정(이전 차·이전 칸 종료, 오래된 관측 무시), 보류 120초 → 관리자 확인 목록 및 선택적 crop 요청·저장, 입·출차, 차량 조회 |
| MQTT 수신기 | `app/mqtt_listener.py` | `spasiba/+/event·status·crop` 구독, 5초마다 보류 점검 → `spasiba/{camera_id}/crop_request` 발행, 카메라 online/offline(LWT) 기록 |
| REST API | `app/routers/parking.py` | `POST /entries`, `POST /exits`, `GET /entries`, `GET /vehicles/{plate}/last-location` |
| 가짜 Pi | `tools/` | 시나리오 9개(JSON)로 event·status를 발행, crop 요청에 더미 사진 응답 (v0.4 토픽) |
| 테스트 | `tests/` | 단위·API·MQTT 처리·통합(시나리오 9개) 및 실제 PostgreSQL·Mosquitto |

**API 요약** (상세: `docs/server_interface.md` 3장)

| 요청 | 응답 |
|---|---|
| `POST /entries {"plate_number", "entered_at"?}` | 201 세션 / 409 이미 입차 중 / 422 형식 오류 |
| `POST /exits {"plate_number"}` 또는 `{"session_id"}` | 200 `EXITED` (칸 배정 종료) / 404 |
| `GET /entries?state=ACTIVE` | 세션 목록 + 현재 칸 |
| `GET /vehicles/{plate}/last-location` | `CONFIRMED`(칸·층·구역·`node_id`, `source` session/event) / `PENDING`(알면 구역) / 404 |

## 폴더

```
server/
├── app/
│   ├── main.py            # FastAPI 앱, /health, 오류 형식
│   ├── config.py          # 환경변수 설정 (.env.example)
│   ├── db.py              # DB 연결 (PostgreSQL / 개발용 SQLite), 시각·JSON 타입
│   ├── models.py          # 수꽝 표 5개 (인터페이스 5.1)
│   ├── models_map.py      # 지도 표 6개 미러 (원본은 수빈의 db/map_schema.sql, 고치지 않음)
│   ├── plates.py          # 번호 정규화·형식 검사(용도 문자 목록)·편집 거리
│   ├── matching.py        # 매칭 판단 EXACT / EDIT1 / 보류 (DB 없는 순수 함수)
│   ├── parking.py         # 입·출차, 이벤트 처리·매칭, 보류 → 관리자 확인·crop, 차량 조회
│   ├── mqtt_listener.py   # MQTT 수신 (event·status·crop), 5초마다 보류 점검 → crop_request
│   └── routers/
│       ├── parking.py     # POST /entries, POST /exits, GET /entries, GET /vehicles/{plate}/last-location
│       └── stubs.py       # 아직 안 만든 API 자리 (501): 관리자 확인(작업 9), 떵개 지도 API
├── db/                    # 수빈의 지도 SQL 사본: map_schema.sql(표), map_seed.sql(샘플 지도 데이터)
├── tools/                 # 가짜 Pi (fake_pi.py, scenarios/)
├── tests/                 # pytest
├── mosquitto/mosquitto.conf
├── docker-compose.yml     # broker + db + api
├── Dockerfile
└── requirements.txt
```

## 실행

**도커로 한 번에 (브로커·DB·API):**

```bash
cd server
cp .env.example .env
docker compose up --build
# http://localhost:8000/health , http://localhost:8000/docs
```

**도커 없이 API만 (SQLite, MQTT 끔):**

```bash
cd server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**테스트:**

```bash
python -m pytest -q
```

`tests/test_models.py`는 같은 검사를 SQLite와 PostgreSQL에서 돌립니다. PostgreSQL 쪽은 `docker compose up -d`로 DB가 떠 있을 때만 돌고(기본 `localhost:5432`, 다른 곳은 `TEST_DATABASE_URL`), 아니면 건너뜁니다. 테스트마다 임시 스키마를 만들어 수빈의 `db/map_schema.sql` → 우리 표 순으로 만들고 끝나면 지우므로 개발 DB 데이터는 건드리지 않습니다.

## 구현 상태 (2026-11-18)

| 작업 | 상태 |
|---|---|
| 4 DB 스키마 | ✅ SQLite·PostgreSQL 테스트 통과 |
| 5 가상 입·출차 API | ✅ |
| 6 MQTT 수신기 | ✅ 토픽 v0.4 `spasiba/+/event·status·crop`, 클라이언트 이름 `spasiba-cloud` |
| 7 매칭 엔진 v1 | ✅ EXACT / EDIT1(votes ≥ `MATCH_MIN_VOTES`) / 보류 → `MATCH_PENDING_SECONDS` 뒤 관리자 확인 및 선택적 crop_request |
| 8 차량 조회 | ✅ CONFIRMED(session·event) / PENDING(보이는 구역 포함) / 404 |
| 9 관리자 확인 API·페이지 | ⏸ 나중에. 처리 함수(`app/parking.py`의 `list_reviews`, `resolve_review` 등)는 준비됨, 경로는 501 |
| 10 통합 테스트 | `tests/test_integration.py` 및 실제 브로커·PostgreSQL용 `tests/test_live_integration.py` |

매칭·조회의 세부 규칙 (인터페이스 문서에 없는 부분, 구현하며 정함):
- 같은 칸·같은 차 이벤트는 `last_seen_at`만 갱신합니다. 더 오래된 관측(`recognized_at`)이 새 배정을 덮어쓰지 않습니다(`stale`).
- 보류 중인 칸은 새 입차가 등록되면 다시 판단합니다 (Pi가 입차 등록보다 먼저 본 경우).
- 보류 120초가 지나면 crop을 기다리지 않고 바로 관리자 확인 목록에 올리고, crop은 도착하면 붙입니다. Crop을 활성화하면 요청의 `event_id`는 확인 항목에 포함된 가장 최근 유효 관측입니다 (Pi는 일치할 때만 응답).
- PENDING 응답의 `zone_id`: 보류·확인 중인 칸 가운데 그 차와 한 글자 이내로 읽힌 칸의 구역이 하나로 정해질 때만 넣습니다.
- 세션 없는 이벤트 기준 위치(`source: "event"`)는 그 뒤에 출차했거나 같은 칸에 다른 차가 보였으면 쓰지 않습니다(404).
- 카메라 status는 메모리에만 기록하고 로그로 남깁니다 (`ts` 없는 offline = LWT).

## DB 표

- 지도 표 6개(`zone`, `camera`, `map_node`, `parking_slot`, `map_edge`, `qr_location`)는 **수빈 담당**이고 원본은 수빈의 `db/map_schema.sql`입니다. `app/models_map.py`는 FK와 SQLite 테스트를 위한 미러이며, 원본이 바뀌면 같이 맞춥니다.
- 운영 DB에서는 수빈의 SQL을 먼저 실행해도 되고, API가 먼저 떠서 표를 만들어도 됩니다 (이미 있는 표는 건너뜀).
- `parking_event`는 칸·카메라에 FK를 걸지 않습니다. 등록 안 된 칸의 이벤트도 `valid=false`로 남깁니다.
- 시각은 시간대가 있는 값만 받아 UTC로 저장합니다. 시간대 없는 시각은 오류입니다.
- `create_all`은 기존 표를 변경하지 않습니다. 스키마 변경 검증에는 별도의 테스트 DB를 사용합니다.

## 로컬 및 LAN 실행

[실행 가이드](../docs/RUN_INTEGRATION.md)를 참고하세요.

## 가짜 Pi

Pi 대신 인터페이스 v0.4 2장 형식으로 MQTT 메시지를 보내는 도구입니다. 서버 개발·테스트용이며 실제 번호판 이미지는 쓰지 않습니다(crop은 16×16 회색 더미). crop 요청에는 실제 Pi처럼 그 칸의 마지막 `event_id`와 같을 때만 응답합니다. 카메라·칸 ID는 수빈의 샘플 지도(`db/map_seed.sql`)와 같습니다.

옵션: `--host --port --username --password --tls`, `--linger 초`(끝난 뒤 crop_request 기다림, 기본 2), `--entries-url http://localhost:8000/entries`(시나리오의 입차를 먼저 등록). 브로커에 연결 못 하면 5초 안에 종료 코드 2로 끝납니다.

| 시나리오 | 확인하는 것 |
|---|---|
| `01_exact` | 정확히 같은 번호 → EXACT 확정 |
| `02_edit1_high_votes` | 한 글자 차이, 후보 1대, votes 8 → EDIT1 확정 |
| `03_edit1_low_votes` | 한 글자 차이지만 votes 3 → 보류 |
| `04_two_similar` | 한 글자 차이 후보 2대 → 보류 (두 차 모두 PENDING, 구역 B2-A) |
| `05_no_entry` | 입차 기록 없는 차 → 이벤트 기준 확정 (`source: "event"`) |
| `06_duplicate_event_id` | 같은 `event_id` 재전송 → 1건만 저장 |
| `07_slot_new_car` | 같은 칸에 다른 차 → 이전 배정 종료, 새 차 확정 |
| `08_lwt` | 연결 시 online, 비정상 끊김 시 LWT offline(`ts` 없음). 정상 종료는 `ts` 있는 offline |
| `09_crop_request` | votes 2로 보류 → 120초 뒤 관리자 확인 + crop_request → 더미 crop 저장 |

시나리오 형식과 기대값(`expect`)은 `tools/scenarios/*.json`을 보세요. `tests/test_integration.py`가 9개 모두를 브로커 없이 서버 처리까지 돌려 `expect`를 확인합니다.

## 작업 규칙

- API 경로·응답 형식을 바꾸려면 `docs/server_interface.md`를 먼저 고치고 서로 알린다.
- 브랜치: `server/main`(통합) ← `server/matching`(수꽝), `server/map-route`(떵개)
- `.env`, DB 파일, crop 사진은 커밋하지 않는다.
- 클라우드 배포 시 브로커는 TLS 8883만 열고 계정·ACL을 켠다 (`compose.tls.yml` 및 `mosquitto/acl.example`).
