# 수인 매칭 서버 + 수빈 지도·경로 통합

## 기준과 합친 내용

- 기준 브랜치: server/matching, 원본 9ddf153.
- 수빈 코드: subin_server d36f941.
- 인터페이스: server/matching의 **v0.4**를 유지한다.
- 수인의 입출차·매칭·MQTT·DB 서비스는 유지하고 지도 stub만 실제 API로 교체한다.
- 이전 로컬 demo_parking 어댑터는 이력/회귀 테스트용으로 남겨두고 통합 앱에서는 사용하지 않는다.

## 하나의 DB와 앱

정식 실행 진입점은 `server.app.main:app` (루트 실행) 또는 `app.main:app` (server 폴더 실행)이다.
지도 6개 테이블과 수인의 이벤트·세션·배정 테이블을 같은 SQLAlchemy DB에서 읽는다.
QR·지도·경로 API는 DB를 읽고, 수신·매칭과 동일한 parking_slot/node_id를 사용한다.
입차→실제 MessageHandler→매칭→차량 검색→QR→경로→출차를 통합 테스트한다.

로컬 시연은 `server.app.demo_main:app`이다. 이 진입점은 샘플 지도 초기화와
`POST /simulator/events`를 켠다. 이 입력은 수인의 **실제 handle_event**를 호출한다.
상태 결과는 assigned/refreshed/pending/invalid/duplicate/stale/rejected를 따른다.
MQTT를 흉내 내는 HTTP 경로는 로컬 시연용이며 실제 Pi는 MQTT 토픽을 사용한다.

정식 main에서는 SIMULATOR_ENABLED=false가 기본이며 로컬 관측 주입을 허용하지 않는다.
샘플 지도는 SEED_SAMPLE_MAP=true일 때 지도 표 6개가 모두 비어 있어야만 넣는다.
기존 지도가 하나라도 있으면 자동 갱신/삭제하지 않는다.

## v0.4 반영

- 샘플 카메라: CAM-B2-01 / CAM-B2-02.
- 토픽: spasiba/{camera_id}/event, status, crop, crop_request.
- zone_id는 주차면 등록 정보에서 찾는다. 시뮬레이터의 이전 zone_id는 호환 입력으로 무시된다.
- 카메라가 다른 구역의 칸을 관측할 수 있으므로 지도 검증에서 카메라 소속 구역과
  주차면 구역이 같아야 한다는 이전 제한을 제거했다. slot.camera_id 등록은 여전히 검증한다.
- 지도 JSON, SQL 사본, 가짜 Pi 시나리오와 테스트 ID를 함께 맞췄다.

## 실행

루트에서:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn server.app.demo_main:app --host 127.0.0.1 --port 8000
```

http://127.0.0.1:8000/simulator

DATABASE_URL 기본값은 실행 폴더의 spasiba_dev.db(SQLite)다.
수인의 기존 개발 DB를 자동 변환하지 않으며, 예전 카메라 ID가 있는 지도에는
sample 자동 seed가 적용되지 않는다. 기존 DB는 보존하고 필요하면 다른 DATABASE_URL로
별도 개발 DB를 만든 뒤 시연한다. 구형 `.local/demo.sqlite3`는 통합 앱에서 사용하지 않는다.

Docker는 `cd server; docker compose up --build`를 유지하되 빌드 컨텍스트를
저장소 루트로 바꿔 map/와 simulator/도 이미지에 포함했다.
Docker 자체 실행은 환경이 없어 검증하지 못했다.

## 테스트와 남은 범위

2026-11-18 통합 검증:

- 기존 수빈 unittest 29개 통과, Node 화면 동작 테스트 통과.
- 수인 pytest 및 새 통합 테스트 175개 통과, 21개 skip.
- skip 사유: 실제 브로커 없음 2개, 실제 PostgreSQL 없음 19개.
- 새 통합 테스트 8개에는 실제 MessageHandler→DB 매칭→차량조회→QR→경로→출차,
  로컬 관측 주입 기본 차단, 중복 이벤트, 기존 지도 보존, 구역을 넘는 카메라 등록,
  잘못된 카메라 이벤트 보존, 누락 입력, 모든 주차면 경로가 포함된다.
- 통합 Uvicorn 앱의 /health, /simulator/layout, /map, /qr, /route 실제 HTTP 응답 확인.
- Docker 빌드·모바일·픽셀 렌더링·실제 장비 검증은 아직 수행하지 않았다.

`python -m tools.verify`는 기존 수빈 회귀 테스트, Node 화면 코드 테스트,
수인 서버 pytest와 새 통합 테스트를 별도 프로세스에서 실행한다.
관리자 REST API는 수인 원본의 501을 유지한다. 내부 처리 함수만 준비된 상태다.
실제 PostgreSQL·브로커 연결 테스트는 해당 환경이 없으면 skip되므로
로컬 SQLite/함수 기반 MQTT 통과와 구분한다.
휴대폰·실제 QR 스캔·실물 OCR·브라우저 시각 검증도 별도로 진행해야 한다.

## 파일 구조 변경

`server/app.py`와 새 `server/app/` 패키지의 이름 충돌을 피하려고 과거 독립 앱을
`server/legacy_app.py`로 옮겼다. 과거 테스트는 이 앱을 명시적으로 참조한다.
최단 경로 구현 원본은 `server/app/map_route.py`, 기존 `server/route.py`는 호환 import다.
docs/의 v0.3.x 대조 문서들은 통합 이전 이력이며 현재 기준은 이 문서와 v0.4 명세다.
