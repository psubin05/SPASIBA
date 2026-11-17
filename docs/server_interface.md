<aside>
📝

**초안 · 합의 필요.** 서버 파트(수꽝)가 제안하는 인터페이스입니다. 6장 체크리스트의 ☐ 항목은 아직 확정되지 않았으니 의견을 댓글로 남겨 주세요. 특히 AI·IoT 파트는 1장(식별자·번호 형식)과 2장(MQTT)을 봐 주세요.

</aside>

> 버전: 0.3.1 초안 · 작성: 2026-11-12 · 수정: 2026-11-17 (매칭 기준 votes 5로 통일, 정상 종료 offline에 ts) · 작성자: 수꽝 · 검토: 떵개 → 확정 후 AI·IoT 파트, Web 파트에 정리해서 전달
기준: 소프트웨어 아키텍처 명세서 **v1.2**(11/02). 명세서에 없는 내용은 **[추가]** 로 표시했고, 합의되면 명세서 v1.3에 반영합니다.
이 문서의 이름·형식이 바뀌면 **문서를 먼저 고치고** 관련 파트에 알린 뒤 코드를 고칩니다.
>

---

## 0. 명세서 v1.2 대비 바뀌는 점

| 구분 | v1.2 | 이 문서 | 영향받는 파트 |
| --- | --- | --- | --- |
| 입·출차 | 없음 (기존 시스템 연동 없음) | **[추가]** 가상 입·출차 세션 (`entry_session`) | 서버 |
| 위치 확정 | Pi가 확정한 이벤트 중 가장 최근 것 | **[추가]** 이벤트를 입차 세션과 매칭해 확정 (`slot_assignment`). 매칭 전에는 v1.2 방식으로 대체 | 서버 |
| 매칭 실패 | 해당 없음 | **[추가]** 관리자 확인 (`review_queue`, 관리자 페이지) | 서버, Web |
| Pi → 서버 사진 | 보내지 않음 | **[추가]** 매칭 실패 시 서버가 요청한 경우에만 crop 1장 | AI·IoT, 서버 |
| Pi 재발행 | 확정 시 1회 | **변경 없음** (v1.2 그대로). 재확인 이벤트는 나중 과제 (4.1) | - |
| 조회 응답 | slot_id·이름·층·시각 | **[추가]** `status` 필드 (확정 / 확인 중 / 없음) | Web |
| 지도 API | 없음 | **[추가 제안]** `GET /map?floor=` | 떵개, Web |

---

## 1. 식별자와 번호 규칙

| 이름 | 형식 | 예 | 누가 정함 |
| --- | --- | --- | --- |
| `zone_id` | `{층}-{구역}` | `B2-A` | 지도 데이터 (떵개) |
| `camera_id` | `CAM-{zone_id}-{번호2자리}` | `CAM-B2-A-01` | 지도 데이터 + Pi 설정 |
| `slot_id` | `{zone_id}-{번호2자리}` | `B2-A-03` | 지도 데이터 |
| `location_id` (QR) | `QR-{층}-{이름}` | `QR-B2-ENT1` | 지도 데이터 |
| `event_id` | Pi가 만드는 UUID v4 문자열. **재발행 시 같은 값 유지** | `3f2c…` | Pi |
| `session_id` | 서버가 만드는 UUID v4 | `a91e…` | 서버 |
| 시각 | ISO 8601, 시간대 포함 | `2026-11-12T14:03:21+09:00` | 보내는 쪽 |

### 1.1 번호판 표기 (`plate_number`)

- 저장·전송은 **지역명 포함 전체 문자열**, 공백·하이픈 없이: `12가3456`, `123가4567`, `서울12가3456`, `경기71아3535`
- 서버는 받은 번호를 **정규화**해 `plate_norm`으로 따로 저장한다 (공백·`-`·`·` 제거, 전각 숫자 → 반각).
- 비교(편집 거리)는 **글자 단위**로 하되 **지역명 17개는 1글자로 센다** (`서울`, `부산`, `대구`, `인천`, `광주`, `대전`, `울산`, `세종`, `경기`, `강원`, `충북`, `충남`, `전북`, `전남`, `경북`, `경남`, `제주`).
- 형식 검사(정규식)는 Pi와 서버가 같은 규칙을 쓴다: `^(지역명)?\d{2,3}[가-힣]\d{4}$` (지역명 = 위 17개 중 하나)

---

## 2. MQTT (Edge ↔ Cloud)

공통: Mosquitto, **TLS 8883**, 노드별 계정, **QoS 1**, JSON(UTF-8).

| 토픽 | 방향 | 용도 | 명세서 |
| --- | --- | --- | --- |
| `spasiba/{zone_id}/{camera_id}/event` | Pi → 서버 | 주차면 확정 이벤트 | v1.2 |
| `spasiba/{zone_id}/{camera_id}/status` | Pi → 서버 | online/offline (retained, LWT) | v1.2 |
| `spasiba/{zone_id}/{camera_id}/crop_request` | 서버 → Pi | crop 사진 요청 | **[추가]** |
| `spasiba/{zone_id}/{camera_id}/crop` | Pi → 서버 | crop 사진 응답 | **[추가]** |

ACL: 각 Pi 계정은 자기 `spasiba/{zone_id}/{camera_id}/#` 에 **event·status·crop 발행**, **crop_request 구독**만 허용. 서버 계정은 `spasiba/+/+/event|status|crop` 구독, `crop_request` 발행.

### 2.1 event (v1.2 필드 + 선택 필드)

```json
{
  "event_id": "3f2c9a1e-5b7d-4c1a-9f0e-2d8b6a4c1e77",
  "plate_number": "12가3456",
  "camera_id": "CAM-B2-A-01",
  "zone_id": "B2-A",
  "slot_id": "B2-A-03",
  "recognized_at": "2026-11-12T14:03:21+09:00",

  "votes": 5,
  "frames": 7,
  "kind": "confirm"
}
```

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `event_id` ~ `recognized_at` | ✅ | 명세서 v1.2 그대로 |
| `votes`, `frames` | **권장** [추가] | 발행 시점 track의 최근 읽기(최대 10개) 중 `votes` = 1등 번호가 나온 횟수, `frames` = 형식이 맞는 읽기 횟수. 매칭 규칙 ②와 관리자 화면에 사용 (없으면 ② 미적용) |
| `kind` | 선택 [추가] | `confirm` = 처음 확정, `recheck` = 주차 중 재확인 (4.1). 없으면 `confirm` |

서버 검증: 필수 필드 존재, `slot_id`가 `camera_id`에 등록된 칸인지(`parking_slot.camera_id`), 번호 형식. 실패하면 `valid=false`로 **저장은 하되 매칭에 쓰지 않는다** (디버깅용).

### 2.2 Pi 발행 규칙 [추가 · AI·IoT 합의 필요]

- 주차면 확정 이벤트는 **칸에 차가 새로 서서 정지했을 때 한 번** 발행한다 (명세서 v1.2).
- Pi는 **칸별로 마지막에 발행한 번호를 기억**하고, 다음 경우에만 다시 발행한다 (새 `event_id`).
    - 칸이 비었다가 다시 찼을 때
    - 같은 칸의 확정 번호가 바뀌었을 때 (정정)
- 번호판이 잠깐 가려졌다 다시 보여 같은 번호가 나오면 **발행하지 않는다**.
- 네트워크 단절 후 재발행은 **같은 `event_id`** (명세서 v1.2).
- 출차는 Pi가 알리지 않는다. 서버도 같은 칸·같은 번호 이벤트가 다시 오면 `last_seen_at`만 갱신하므로 중복 발행에 안전하다.

### 2.3 status (v1.2 그대로)

연결 시 `{"state":"online","ts":"…"}` retained 발행, LWT로 `{"state":"offline"}`, 정상 종료 시 직접 `{"state":"offline","ts":"…"}` 발행 (`ts` 유무로 LWT와 정상 종료를 구분).

### 2.4 crop_request / crop [추가]

```json
// 서버 → Pi : crop_request
{ "request_id": "r-7c1e…", "slot_id": "B2-A-03", "event_id": "3f2c…", "reason": "unmatched" }

// Pi → 서버 : crop
{ "request_id": "r-7c1e…", "slot_id": "B2-A-03", "event_id": "3f2c…",
  "captured_at": "2026-11-12T14:05:02+09:00",
  "image_jpeg_base64": "/9j/4AAQ…" }
```

- Pi는 **칸별로 가장 최근 번호판 crop 1장**을 메모리에 들고 있다가 요청이 오면 보낸다 (새로 찍어도 됨).
- crop은 번호판 + 약간의 차체, **긴 변 640px 이하, 100KB 이하** JPEG.
- 서버는 관리자 확인이 끝나거나 출차하면 crop을 삭제한다.

---

## 3. REST API (Client ↔ Cloud)

공통: HTTPS, JSON, 오류는 `{"error": {"code": "NOT_FOUND", "message": "…"}}`. 시각은 ISO 8601.

| 메서드 · 경로 | 담당 | 용도 | 명세서 |
| --- | --- | --- | --- |
| `GET /qr/{location_id}` | 떵개 | QR → 출발 노드 | v1.2 |
| `GET /vehicles/{plate}/last-location` | 수꽝 | 차량 위치 조회 | v1.2 (+status) |
| `GET /route?from={location_id}&to={slot_id}` | 떵개 | 최단 경로 | v1.2 |
| `GET /map?floor={floor}` | 떵개 | 지도 그리기용 좌표 | **[추가 제안]** |
| `POST /entries` · `POST /exits` · `GET /entries` | 수꽝 | 가상 입·출차 | **[추가]** |
| `GET /admin/reviews` 외 | 수꽝 | 관리자 확인 | **[추가]** |
| `GET /health` | 공동 | 헬스체크 | - |

### 3.1 `GET /vehicles/{plate}/last-location`

```json
// 200 — 위치 확정
{
  "plate_number": "12가3456",
  "status": "CONFIRMED",
  "slot_id": "B2-A-03", "slot_name": "A-03", "floor": "B2", "zone_id": "B2-A",
  "node_id": "N-A03",
  "last_seen_at": "2026-11-12T14:20:05+09:00",
  "confirmed_at": "2026-11-12T14:03:40+09:00",
  "source": "session"
}

// 200 — 입차는 했지만 아직 칸을 못 정함
{
  "plate_number": "12가3456",
  "status": "PENDING",
  "zone_id": "B2-A", "floor": "B2",
  "message": "주차 위치를 확인하고 있습니다."
}

// 404 — 기록 없음 (입차 기록도, 인식 기록도 없음 / 출차함)
{ "error": { "code": "NOT_FOUND", "message": "해당 차량의 주차 기록이 없습니다." } }
```

| `status` | 조건 | 웹 표시 |
| --- | --- | --- |
| `CONFIRMED` | 진행 중 세션에 칸이 확정됨 (`source: "session"`), 또는 세션은 없지만 이벤트가 정확히 일치 (`source: "event"`, v1.2 방식) | 칸 · 층 · 확인 시각 + 경로 버튼 |
| `PENDING` | 진행 중 세션은 있는데 칸 미확정 (매칭 보류·관리자 확인 대기). 차가 보인 구역을 알면 `zone_id` 포함 | "위치 확인 중" + (있으면) 구역까지 안내 |
| 404 | 진행 중 세션도 일치 이벤트도 없음, 또는 출차함 | "기록 없음" |
- `{plate}`는 URL 인코딩된 한글 그대로 받고 서버가 정규화한다.
- `node_id`는 떵개의 `GET /route`에 넘길 도착 노드 (웹은 `to=slot_id`로 보내도 됨).

### 3.2 가상 입·출차 [추가]

```json
// POST /entries   요청
{ "plate_number": "12가3456", "entered_at": "2026-11-12T14:00:00+09:00" }   // entered_at 생략 시 서버 시각
// 201 응답
{ "session_id": "a91e…", "plate_number": "12가3456", "entered_at": "…", "state": "ACTIVE" }
// 409: 같은 번호의 진행 중 세션이 이미 있음

// POST /exits   요청 (둘 중 하나)
{ "plate_number": "12가3456" }      또는      { "session_id": "a91e…" }
// 200 응답: 세션 종료, 칸 배정 종료
{ "session_id": "a91e…", "exited_at": "…", "state": "EXITED" }

// GET /entries?state=ACTIVE  → 세션 목록 (시연 관리용)
```

- **입·출차 기록의 원본은 주차관제 시스템**이다 (시연에서는 이 API로 가상 기록을 넣는다). 서버는 받은 기록을 `entry_session`에 **자체 보관**하고, 실제 관제 API가 생기면 이 API 대신 가져오는 부분만 바꾼다.
- 출차 처리 시 서버가 하는 일: 세션 `EXITED` → 진행 중인 `slot_assignment` 종료 → 그 차의 보류·확인 항목 정리, crop 삭제 → 이후 `last-location`은 404.

### 3.3 관리자 확인 [추가]

| 메서드 · 경로 | 설명 |
| --- | --- |
| `GET /admin/reviews?status=OPEN` | 확인 필요 목록: review_id, slot_id, 읽은 번호, 후보 세션(번호·입차 시각·편집 거리), 생성 시각, crop 유무 |
| `GET /admin/reviews/{review_id}/crop` | crop JPEG |
| `POST /admin/reviews/{review_id}/resolve` | `{"action":"assign","session_id":"a91e…"}` 또는 `{"action":"dismiss"}` (해당 차 없음) |
- 인증: 시연에서는 `Authorization: Bearer {ADMIN_TOKEN}` 헤더(환경변수로 설정). 이용자용 API는 명세서대로 공개·읽기 전용.

### 3.4 떵개 API 응답 (요약, 상세는 지도·경로 문서)

- `GET /qr/{location_id}` → `{ "location_id", "name", "floor", "node_id" }`, 없으면 404
- `GET /route?from=&to=` → `{ "from", "to_slot", "floor", "distance_m", "path": [{"node","x","y"}], "steps": ["…"] }`
- `GET /map?floor=` → `{ "floor", "nodes": [...], "edges": [...], "slots": [{"slot_id","name","polygon","node_id"}] }`

---

## 4. 매칭 규칙 (수꽝 내부, 다른 파트는 참고용)

1. 이벤트 수신 → 검증 → `parking_event` 저장 (같은 `event_id`면 무시).
2. 후보 = `state = ACTIVE`인 입차 세션 전체.
3. 판단:

| 순서 | 조건 | 결과 (`method`) |
| --- | --- | --- |
| ① | `plate_norm`이 후보 하나와 **정확히 일치** | 즉시 확정 (`EXACT`) |
| ② | 정확히 일치는 없고, **편집 거리 1**인 후보가 **딱 한 대**, 이벤트의 `votes`가 **기준 이상**(기본 5) | 확정 (`EDIT1`) + 관리자 화면에 **“자동 확정 · 검토 권장”** 표시 |
| ③ | 그 외 | 보류. 칸별 보류 상태에 이벤트 누적 |
| ④ | 보류가 **120초** 넘음 | `review_queue` 등록 + `crop_request` 발행 → 관리자 확인 (`ADMIN`) |
1. 확정 시 `slot_assignment` 기록. 그 칸에 다른 세션이 배정돼 있었으면 **이전 배정 종료** (차가 빠지고 다른 차가 섬). 같은 세션이 다른 칸에 배정돼 있었으면 **이전 배정 종료** (차가 옮김).
2. 숫자(`votes` 5, 120초)는 시연 리허설에서 조정한다. `votes`가 없는 이벤트는 ②를 적용하지 않고 보류한다.

### 4.1 반복 확인을 서버에서 하지 않는 이유 (결정 2026-11-12)

- Pi가 이미 여러 프레임 투표로 **우연한 오류**를 거른다. 서버가 같은 일을 다시 할 필요가 없다.
- **같은 실수를 반복하는 오류**(빛 반사로 매번 8→6)는 다시 읽어도 똑같이 틀리므로 반복 확인으로 막을 수 없다.
- 규칙 ②의 안전장치는 “한 글자 차이 후보가 주차장에 **딱 한 대**”라는 조건이다. 남는 위험(입차 기록 없는 차 + 한 글자 차이 차량 존재)은 **관리자 검토 표시**로 대응한다.
- Pi의 주기적 재확인 이벤트(`kind: "recheck"`)는 “아직 그 칸에 있는지” 알고 싶을 때 쓰는 **나중 과제**로 둔다. 명세서도 마지막 확인 이후 점유 상태는 보장하지 않는다.

---

## 5. DB 테이블

### 5.1 수꽝 담당

```sql
-- 인식 기록 (명세서 v1.2)
parking_event (
  event_id      TEXT PRIMARY KEY,           -- 재발행 중복 제거
  plate_number  TEXT NOT NULL,
  plate_norm    TEXT NOT NULL,
  camera_id     TEXT NOT NULL REFERENCES camera,
  zone_id       TEXT NOT NULL REFERENCES zone,
  slot_id       TEXT NOT NULL REFERENCES parking_slot,
  recognized_at TIMESTAMPTZ NOT NULL,
  received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  kind          TEXT NOT NULL DEFAULT 'confirm',
  votes INT, frames INT,
  valid         BOOLEAN NOT NULL DEFAULT true,
  invalid_reason TEXT
)
INDEX (plate_norm, recognized_at DESC)

-- [추가] 입차 세션
entry_session (
  session_id   UUID PRIMARY KEY,
  plate_number TEXT NOT NULL,
  plate_norm   TEXT NOT NULL,
  entered_at   TIMESTAMPTZ NOT NULL,
  exited_at    TIMESTAMPTZ,
  state        TEXT NOT NULL CHECK (state IN ('ACTIVE','EXITED'))
)
UNIQUE (plate_norm) WHERE state = 'ACTIVE'      -- 같은 번호 진행 중 세션 1개

-- [추가] 세션 ↔ 칸 배정 (이력 보존)
slot_assignment (
  id           BIGSERIAL PRIMARY KEY,
  session_id   UUID NOT NULL REFERENCES entry_session,
  slot_id      TEXT NOT NULL REFERENCES parking_slot,
  method       TEXT NOT NULL CHECK (method IN ('EXACT','EDIT1','ADMIN')),
  event_ids    TEXT[] NOT NULL,                -- 근거 이벤트
  assigned_at  TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  ended_at     TIMESTAMPTZ
)
UNIQUE (session_id) WHERE ended_at IS NULL     -- 세션당 현재 칸 1개
UNIQUE (slot_id)    WHERE ended_at IS NULL     -- 칸당 현재 차 1대

-- [추가] 칸별 보류 상태 (서버 재시작에도 유지)
match_pending (
  slot_id        TEXT PRIMARY KEY REFERENCES parking_slot,
  first_event_at TIMESTAMPTZ NOT NULL,
  reads          JSONB NOT NULL               -- [{event_id, plate_norm, recognized_at}]
)

-- [추가] 관리자 확인
review_queue (
  review_id    UUID PRIMARY KEY,
  slot_id      TEXT NOT NULL REFERENCES parking_slot,
  read_plates  JSONB NOT NULL,                -- Pi가 읽은 번호들
  candidates   JSONB NOT NULL,                -- [{session_id, plate_number, entered_at, distance}]
  crop_path    TEXT,
  status       TEXT NOT NULL CHECK (status IN ('OPEN','RESOLVED','DISMISSED')),
  created_at   TIMESTAMPTZ NOT NULL,
  resolved_at  TIMESTAMPTZ,
  resolved_session_id UUID
)
```

### 5.2 떵개 담당 (명세서 v1.2, 수꽝은 읽기만)

```sql
zone         (zone_id PK, floor, name)
camera       (camera_id PK, zone_id FK, description)
parking_slot (slot_id PK, zone_id FK, camera_id FK, name, roi JSONB, node_id FK)
map_node     (node_id PK, floor, x, y, type)        -- type: entrance/kiosk/junction/slot_front/elevator
map_edge     (from_node FK, to_node FK, length_m)   -- 양방향
qr_location  (location_id PK, node_id FK, floor, name)
```

---

## 6. 합의 체크리스트

| 항목 | 누구와 | 상태 |
| --- | --- | --- |
| 식별자 형식 (1장) | 떵개, AI·IoT | ☐ |
| 번호판 표기·형식 정규식 (1.1) | AI·IoT | ☐ |
| event 선택 필드 `votes`·`frames`·`kind` (2.1) | AI·IoT | ☐ |
| 반복 확인 방식 → Pi 변경 없음, `votes` 기준 사용 (4.1) | 수꽝·떵개 | ✅ 결정 |
| Pi 발행 규칙: 칸별 마지막 번호 기억, 새로 섰거나 번호가 바뀔 때만 (2.2) | AI·IoT | ☐ |
| crop 토픽·크기·보관 (2.4) | AI·IoT | ☐ |
| `last-location` 응답과 `status` 3가지 (3.1) | 수꽝·떵개 → Web에 전달 | ✅ 결정 |
| `GET /map` 추가 여부 (3.4) | 떵개, Web | ☐ |
| 관리자 페이지 담당 (서버 파트가 간단히 만들지) | Web | ☐ |
| 매칭 숫자: 한 글자 차이는 `votes` 5 이상이면 확정, 보류 120초 (4장) | 떵개 | ☐ |
