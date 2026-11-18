# Raspberry Pi–Server 통합 결과

작업 브랜치는 `integration/pi-server`다. 원격에서 확인한 기준점은 `raspberrypi` `816b608`, `server/matching` `9ddf153`, `subin_server` `d36f941`이다. 시작 시 로컬 작업 트리는 깨끗했다. `server/matching`에서는 `server/`와 v0.4 계약 문서만 가져왔고 가져오기 커밋은 `568d8db`다. Pi의 `src/`, `config/`, 모델 파일과 실행 스크립트는 저장소 루트에 두어 기존 가상환경과 경로를 사용할 수 있게 했다. 원본 브랜치와 `subin_server` 지도 소스의 커밋은 보존했다.

## 변경과 결과

| 기존 문제 | 수정 파일 | 수정 내용과 이유 | 검증 | 결과 |
| --- | --- | --- | --- | --- |
| Pi 4단계 토픽 / 서버 3단계 구독 | `src/edge_cloud/{config,transport,events}.py`, `server/app/mqtt_listener.py` | v0.4 카메라 토픽, 이벤트 zone 필드 생략, canonical retained Status/LWT. 서버는 SUBACK 후 연결 준비를 보고한다. | 실제 Mosquitto / PostgreSQL / 서버 Status·LWT 및 조회 | PASS |
| 카메라와 칸을 구역 하나로 제한 | `src/edge_cloud/{config,slots,runtime}.py`, `server/app/{identifiers,parking}.py`, `server/db/map_seed.sql`, Fake Pi와 테스트 데이터 | `CAM-B2-01`이 `B2-A-03`과 `B2-B-03`에 연결된다. `camera.zone_id`는 기존 지도 스키마의 설치 메타데이터로 두고, 칸 소유는 `parking_slot.camera_id`만 사용한다. 스키마 DDL은 기존 정의를 사용한다. | 단일 카메라·서로 다른 구역 두 칸이 각각 올바른 zone으로 DB에 저장·매칭 | PASS |
| Edge 전체 한글 허용 | `src/edge_cloud/events.py`, `src/postprocessing.py`, `server/tests/test_live_integration.py` | OCR 용도 문자 목록을 Edge 송신 검증에 적용하고 전각 숫자를 복원한다. 서버 기존 정규화와 대조한다. | 지역명, 2/3자리, 전각, 구분자, 허용 외 한글·문자, invalid 이벤트 | PASS |
| OCR 성공 후 발행 보류 | `config/edge.demo.example.json`, `src/edge_cloud/{slots,runtime}.py` | 기본값은 보류. 시연 설정은 5표 이상 합의, 슬롯 하나, 동일 칸 복수 트랙 및 겹치는 ROI 억제. 실행 시 시연 모드를 로그로 표시한다. | 네 표/복수 트랙 보류, 중복 관측 억제, UNKNOWN에서 정상 발행 | PASS |
| 평문 로컬과 Pi TLS 불일치 | `server/{docker-compose.yml,compose.tls.yml,.env.example}`, `server/mosquitto/`, `server/app/{config,mqtt_listener}.py` | 루프백 1883 개발 구성과 8883 TLS LAN 구성. 서버와 Pi에서 CA·호스트 이름을 검증하고 계정별 ACL을 적용한다. | 실제 브로커와 임시 CA의 TLS HTTP 경로, 타 카메라 발행 차단, 잘못된 계정·신뢰되지 않은 CA 거부, Compose 병합 | PASS |
| 정전·연결 끊김·중복 | `src/edge_cloud/transport.py`, `tests/test_mqtt_integration.py`, `server/tests/test_live_integration.py` | QoS 1, PUBACK 후 SQLite 제거, 재연결·재시작 후 같은 이벤트 ID 재전송 유지. 새 기본 SQLite 경로를 사용하며 다른 카메라 소유의 기존 대기 이벤트를 발행하지 않는다. | 실제 브로커 중단·복구 및 Pi 재시작, 서버 구독 재접속 후 QoS 1 재생, PostgreSQL 중복 한 행 | PASS |
| 동일 차량·동일 칸 재입차 | `server/tests/test_live_integration.py`, `docs/DECISIONS_NEEDED.md` | 출차 후 재입차에서 Pi가 같은 조합을 억제해 새 세션이 PENDING에 남는 현상을 재현했다. 명시적 EMPTY 뒤 재발행은 기존 Edge 단위 테스트로 확인했다. | 실시간 통합 재현과 기존 단위 테스트 | PASS (재현) |
| Crop 상관관계 및 크기 | `src/edge_cloud/crops.py`, `server/app/parking.py`, `server/tests/{test_parking,test_live_integration}.py` | 서버 요청은 보류 읽기 중 최근 유효 이벤트를 지정한다. 응답 카메라·세 ID·시각·JPEG 마커·100,000바이트를 검사한다. Pi는 TTL 내 최신 슬롯 이미지만 보낸다. 기본 Crop은 양쪽 꺼짐이다. | 실제 요청→Edge 이미지→저장, TTL 만료 무응답, 틀린 ID·큰 JPEG 거부 | PASS |
| 기존 API 회귀 | `server/tests/` | 입·출차, 조회, 건강 상태, 파일럿 매칭 규칙 및 501 경로를 확인한다. | SQLite/PostgreSQL 스키마 회귀, 9개 시나리오, MQTT/HTTP 통합 | PASS |
| 실제 장비·배포 | `docs/RUN_INTEGRATION.md` | 기존 Pi 카메라 명령과 LAN TLS 설치 절차를 제공한다. | Pi 센서·실제 LAN·클라우드, Docker Engine 컨테이너 기동 | 미실행 |

## 실행 증거

- 실제 Mosquitto 2.0.21, PostgreSQL 17.12, Uvicorn을 테스트용 루프백에서 실행했다. Fake Pi `12가3456`은 `CONFIRMED B2-A-03`을 반환했다. 실제 EdgeRuntime의 합성 OCR `서울123나4567`은 `CONFIRMED B2-B-03`을 반환했다. 두 결과 모두 `source=session`이었고 PostgreSQL에서 유효한 `EXACT` 행을 확인했다.
- 임시 CA·계정과 저장소 ACL을 사용한 TLS 시험에서 실제 EdgeRuntime `12가3456`이 HTTP 조회에서 `CONFIRMED B2-A-03`을 반환했다. `CAM-B2-01` 계정이 `CAM-B2-02` 이벤트를 발행하는 시험은 브로커가 `Not authorized`로 거부했다. 첫 임시 CA의 키 사용 누락은 문서 예시를 고쳐 재실행했다.
- `server/pytest.ini`의 테스트 경로로 서버 테스트 198개가 통과했다. 모델 테스트는 별도 PostgreSQL DB와 임시 스키마를 사용했다. 실시간 통합 테스트에는 Crop 활성·만료, 입차 전 이벤트의 재매칭, 잘못된 카메라·칸·번호, 중복, 서버 재접속, LWT, 다중 구역, 동일 칸 재입차 재현이 포함된다.
- `python -m unittest discover -s tests`의 Pi 회귀 및 실제 TLS 브로커 테스트 31개가 통과했다. `sha256sum -c MODEL_SHA256SUMS.txt`는 `models/detector/plate_v3.pt: OK`를 반환했다.
- Compose 2.26.1의 `config`에서 평문 프로필의 루프백 1883과 TLS 프로필의 8883 단독 노출, 인증서·ACL 마운트를 확인했다. Docker Engine과 카메라 장치가 없어 컨테이너 기동 및 실물 카메라를 실행할 수 없었다.

## 지도·웹 인수인계

원격 `subin_server` 원본을 별도 임시 경로에 풀어 기존 Python 테스트 29개를 통과시켰다. 시뮬레이터의 브라우저 및 Node 테스트는 이번 파이프라인 검증 범위에서 실행하지 않았다.

`subin_server`의 `server/app.py`에는 JSON 지도 기반 `/qr`, `/map`, `/route`가 있다. `server/map_store.py`의 지도 검증·캐시와 `server/route.py`의 그래프 검증·최단 경로·안내문은 추후 연결할 때 재사용할 수 있다. 현재 브랜치의 차량 위치 조회는 정식 매칭·PostgreSQL을 사용한다. 지도 브랜치의 `server/demo_parking.py`와 `server/demo_app.py`는 SQLite 시뮬레이션 어댑터이고 `simulator/`는 시연 UI다. 이 브랜치의 QR·지도·경로 및 관리자 REST는 501이다.

지도 담당자는 원본 `map/b2.json`의 카메라 ID, 칸별 소유 참조 및 SQL 내보내기를 함께 검토한다. 설치 구역 메타데이터를 IoT 토픽이나 칸 소유 판단에 사용하지 않고, 지도 위치는 `node_id`로 연결한다. 웹은 위치 조회에서 `CONFIRMED`일 때 칸과 노드를 얻고, 지도 API가 연결된 뒤 QR과 경로를 조회할 수 있다. 실측 배치, 지도 라우터 결합, 운영 Outbox·DB 전환, 빈 칸 자동 판단 및 관리자 사진 수명 주기는 [팀 결정 안건](DECISIONS_NEEDED.md)에 있다.

## 파일 목록

아래 목록은 Raspberry Pi 기준 커밋에서의 추가(A)·수정(M)이다. 서버 원본에서 가져온 코드도 포함한다.

```text
M  .gitignore
M  README.md
A  config/edge.demo.example.json
M  config/edge.example.json
M  config/roi.example.json
A  docs/DECISIONS_NEEDED.md
M  docs/EDGE_CLOUD_IMPLEMENTATION.md
A  docs/INTEGRATION_REPORT.md
A  docs/INTERFACE_CONTRACT.md
A  docs/RUN_INTEGRATION.md
A  docs/server_interface.md
A  server/.dockerignore
A  server/.env.example
A  server/.gitignore
A  server/Dockerfile
A  server/README.md
A  server/app/__init__.py
A  server/app/config.py
A  server/app/db.py
A  server/app/identifiers.py
A  server/app/main.py
A  server/app/matching.py
A  server/app/models.py
A  server/app/models_map.py
A  server/app/mqtt_listener.py
A  server/app/parking.py
A  server/app/plates.py
A  server/app/routers/__init__.py
A  server/app/routers/parking.py
A  server/app/routers/stubs.py
A  server/compose.tls.yml
A  server/db/map_schema.sql
A  server/db/map_seed.sql
A  server/docker-compose.yml
A  server/docs/plans/2026-11-15-fake-pi.md
A  server/docs/specs/2026-11-15-fake-pi-design.md
A  server/mosquitto/acl.example
A  server/mosquitto/mosquitto-tls.conf
A  server/mosquitto/mosquitto.conf
A  server/pytest.ini
A  server/requirements.txt
A  server/tests/conftest.py
A  server/tests/map_seed.py
A  server/tests/test_api.py
A  server/tests/test_fake_pi.py
A  server/tests/test_fake_pi_messages.py
A  server/tests/test_integration.py
A  server/tests/test_live_integration.py
A  server/tests/test_matching.py
A  server/tests/test_models.py
A  server/tests/test_mqtt_handler.py
A  server/tests/test_parking.py
A  server/tests/test_scenarios.py
A  server/tests/test_skeleton.py
A  server/tools/__init__.py
A  server/tools/fake_pi.py
A  server/tools/fake_pi_messages.py
A  server/tools/scenario.py
A  server/tools/scenarios/01_exact.json
A  server/tools/scenarios/02_edit1_high_votes.json
A  server/tools/scenarios/03_edit1_low_votes.json
A  server/tools/scenarios/04_two_similar.json
A  server/tools/scenarios/05_no_entry.json
A  server/tools/scenarios/06_duplicate_event_id.json
A  server/tools/scenarios/07_slot_new_car.json
A  server/tools/scenarios/08_lwt.json
A  server/tools/scenarios/09_crop_request.json
M  src/edge_cloud/config.py
M  src/edge_cloud/crops.py
M  src/edge_cloud/events.py
M  src/edge_cloud/runtime.py
M  src/edge_cloud/slots.py
M  src/edge_cloud/transport.py
M  src/postprocessing.py
M  tests/test_edge.py
M  tests/test_mqtt_integration.py
```
