# 첨부된 서버 인터페이스 v0.4 재점검

사용자가 추가로 제공한 v0.4 문서를 docs/server_interface.md의 기준으로 반영했다.
이전 기준 파일은 server_interface_v0.4_previous.md에 보관했다.
문서의 초안·합의 필요·미확정 체크 항목은 완료 처리하지 않았다.

## 이미 맞아 있던 항목

| 명세 | 확인 결과 |
|---|---|
| 카메라 ID CAM-{층}-{번호2자리} | 샘플 지도·SQL·가짜 Pi·통합 테스트에서 사용 |
| spasiba/{camera_id}/… | 서버 구독·발행, 가짜 Pi 메시지에서 사용 |
| 카메라의 구역 간 관측 | slot.camera_id로 검증, camera.zone_id와 같아야 한다는 제한 없음 |
| 서버가 zone_id 결정 | ParkingSlot에서 채우며 이전 송신자의 zone_id는 무시 |
| 번호 용도 문자 40자·지역명 토큰 | 정식 서버와 가짜 Pi가 동일한 app.plates를 사용 |
| votes 5의 고유 EDIT1 | 정식 매칭과 설정 기본값 일치 |
| online/정상 offline의 ts, LWT의 ts 생략 | 서버 추적·가짜 Pi 종료·회귀 테스트에서 확인 |
| event_id 중복 제거·오류 이벤트 저장 | 잘못된 데이터는 valid=false/invalid_reason, 저장 불가 메시지는 로그 |
| 입차 세션·배정 이력·PENDING/CONFIRMED/404 | 기존 수인 서비스와 공용 DB 사용 |
| event_ids JSONB, parking_event의 지도 FK 제거 | 기존 정식 모델과 일치 (SQLite는 JSON 호환 타입) |
| QR·지도·경로 응답 | v0.4 3.4의 필드와 요청 형식 유지 |

## 발견해서 수정한 차이

| 차이 | 수정 |
|---|---|
| 시뮬레이터가 예전 zone_id를 계속 전송 | 이벤트에서 제거. 서버의 이전 송신자 호환 처리는 유지 |
| 과거 독립 demo 어댑터의 넓은 한글 허용·필수 zone_id | 같은 용도 문자 목록·정규화 사용, zone_id 선택 및 무시 |
| event_id 형식·투표 수 검증 부족 | UUID v4, votes/frames 0~10 및 votes≤frames 검사, 오류 원본은 invalid로 보존 |
| crop이 200KB까지 허용됨 | 100,000바이트 이하로 제한 (이 구현의 100KB 해석) |
| JPEG 시작 바이트만 검사 | 실제 JPEG 디코더 검사, 긴 변 640px 이하 검사 |
| 다른 slot/event 사진을 같은 검토에 붙일 수 있음 | request_id + camera + slot + event + 시간대 있는 captured_at 확인 |
| 나중에 변경된 칸의 이전 사진 수신 가능 | 최신 유효 관측과 요청한 이벤트가 일치할 때만 수신 |
| crop 요청이 잘못된 최신 이벤트를 선택할 수 있음 | 해당 카메라·칸의 유효 이벤트를 선택하고 요청 event_id를 검토 JSON에 스냅샷 |
| MQTT 연결이 없으면 보류 시간 점검도 정지 | 연결과 독립적으로 검토 큐를 생성. 사진 무응답이어도 검토 가능 |
| 출차 시 보류·검토 사진 정리 부족 | 공유 후보를 보존하면서 해당 차량의 독점 보류 제거, 관련 사진 삭제·후보 정리 |
| 출차 후 새 관측으로 이벤트 조회가 되살아남 | 활성 재입차 세션이 없으면 출차 이력 차량의 이벤트 fallback 차단 |
| 관리자 API 501 | 인증·목록·사진·확정/기각 API를 기존 서비스에 연결 |
| 자동 보정의 검토 권장 정보를 API로 볼 수 없음 | 인증된 `/admin/auto-assignments`에 EDIT1·검토 권장 제공 |
| 가짜 Pi crop 캐시가 카메라·10분 보관을 확인하지 않음 | 원 카메라 및 단조 시계 10분 제한 확인 |
| 검색 화면에 칸·층·확인 시각이 빠짐 | 확정 검색 결과에 표시 |

요청한 crop event_id는 ReviewQueue.read_plates JSON 내부 메타데이터에 저장한다.
새 DB 열은 추가하지 않았다. 기존 검토 항목은 읽기 시각으로 요청 이벤트를 추론한다.
추론할 수 없으면 사진을 붙이지 않고 사진 없는 검토로 유지한다.

## 관리자 API 사용

환경변수 ADMIN_TOKEN을 설정하고 Authorization: Bearer <설정값>을 보낸다.
설정 누락은 503, 인증 누락·불일치는 401, 잘못된 요청은 공통 422 오류다.

- GET /admin/reviews?status=OPEN
- GET /admin/reviews/{review_id}/crop
- POST /admin/reviews/{review_id}/resolve (`assign`+session_id 또는 `dismiss`)
- GET /admin/auto-assignments (문서의 검토 권장 표시를 지원하는 보조 API)

자동 확정 메타데이터와 API는 제공하지만 별도의 관리자 웹 페이지는 만들지 않았다.
관리자 페이지 담당은 원문의 미합의 상태를 유지한다.

## 실제 환경에서 남은 항목

- 로컬 개발은 1883/평문 브로커를 유지한다. 명세의 실제 배포 TLS 8883·계정·ACL을
  구성할 수 있도록 mosquitto.production.conf.example과 acl.example을 추가했다.
- 인증서·계정·네트워크가 없어 실제 TLS/ACL·브로커 동작은 검증하지 못했다.
- `.env.production.example`에 8883/TLS/계정 설정을 구분했다. 사설 CA는 MQTT_CA_CERT로
  지정할 수 있다. 기본 .env.example은 로컬 개발용 1883 설정을 유지한다.
- PostgreSQL 실행 환경이 없어 해당 테스트는 skip되며 SQLite 결과와 구분한다.
- 실제 Pi의 번호판 인식·발행 규칙·crop 보관 동작은 서버 코드와 별도로 확인해야 한다.
- crop 없음 응답 형식, GET /map 추가 승인 등 미합의 사항은 임의로 확정하지 않았다.

## 검증 기록

- 기존 수빈 unittest 29개 및 Node 화면 코드 테스트 통과.
- 수정 중 전체 서버 pytest: 200 passed / 21 skipped.
- 후속 오류 입력 케이스 포함 SQLite 재검증: 201 passed / 브로커 2 skipped / PostgreSQL 19 deselected.
- 최종 인증·crop 디코딩·출차·MQTT 처리·시나리오 집중 회귀: 86 passed.
- TLS CA 설정 전달·OpenAPI v0.4 메타데이터 및 관리자 요청 검증 포함 집중 테스트 통과.
- 건너뛴 실제 브로커 2개·PostgreSQL 19개는 환경 부재이며 통과로 계산하지 않았다.
- Node 테스트는 v0.4 이벤트에 zone_id가 없는 것, 실제 매칭 결과 assigned 표시도 검사한다.
- 기존 DB 열을 바꾸는 마이그레이션은 없으며 사진 요청 스냅샷은 기존 JSON에 보관한다.
