# 수인 인터페이스 v0.3.1 대조 결과

## 확인한 자료

- 최초 제공: 서버 작업 계획과 server_interface v0.3.
- 추가 제공: 2026-11-17 수정된 v0.3.1 전체 본문(0~6장).
- 실제 수인 구현 코드, 배포 서버, DB는 현재 제공되지 않아 확인하지 못했다.

docs/server_interface.md는 새 첨부 본문을 그대로 복사한 기준 문서다.
기존 파일은 server_interface_v0.3.md에 보관했다.
초안·합의 필요 표시와 체크리스트는 유지했으며 완료 처리하지 않았다.

## v0.3 → v0.3.1 변경

- 매칭 체크리스트의 오래된 '이벤트 2번' 표현이 제거되고 votes 5 이상으로 통일됐다.
- 정상 종료 status는 offline과 ts를 함께 발행하며 LWT의 ts 없는 offline과 구분한다.
- 지도·QR·경로 응답과 A/B 분담은 그대로다.

## A 담당 구현 대조

| 명세 항목 | 현재 상태 |
|---|---|
| zone/camera/slot/location 식별자 | 샘플 JSON이 명세 형식 사용 |
| GET /qr/{location_id} | location_id/name/floor/node_id 및 없는 ID의 404 구현 |
| GET /route?from=&to= | QR ID→slot ID, distance/path/steps 응답 구현 |
| GET /map?floor= | 제안 형식 구현, 추가 제안 상태는 유지 |
| A 소유 테이블 6개 | PostgreSQL 생성·데이터 SQL 준비, 실제 DB 적용은 미검증 |
| Web 검색 후 경로 연결 | CONFIRMED의 slot_id만 사용, PENDING/404는 경로 차단 |
| 실측 지도·카메라 ROI | 아직 미확정, 샘플 polygon만 입력 |

## 수인 담당과 겹치는 로컬 시연 코드

`server/demo_parking.py`는 언니의 실제 구현을 확인하거나 대체한 결과물이 아니다.
카메라·언니 서버 없이 네 지도·경로 흐름을 시험하기 위해 추가한 임시 어댑터다.
`server.demo_app:app`에서만 켜지며, `server.app:app`에는 등록되지 않는다.

| 항목 | 임시 어댑터 상태 |
|---|---|
| entries/exits/last-location | 외부 요청·응답의 주요 계약을 따라 시연 |
| EXACT / 고유 EDIT1, votes 5 | 최소 동작 구현 |
| MQTT TLS/ACL/status/crop | 미구현. v0.3.1 offline+ts도 실제 연결 시 수인 구현 확인 필요 |
| entry_session/slot_assignment 등 정식 DB | 미구현. 별도 demo_entry/demo_event SQLite 사용 |
| plate_norm 별도 저장·배정 이력 | 정식 구현과 다름 |
| 120초 보류·review_queue·crop·관리자 인증 | 미구현 |
| 세션 없는 이벤트의 last-location fallback | 미구현 |
| 필수 필드 누락 등의 잘못된 이벤트 원문 보존 | 일부 요청이 422로 거절되어 명세와 다름 |

따라서 '수인 명세 전체 구현 완료' 또는 '수인 코드 연결 완료'로 볼 수 없다.
통합 시에는 시연 어댑터 대신 수인 라우터·MQTT·DB를 연결한다.
그 전까지는 로컬 시연 모드로만 사용한다.

## 화면 한글 수정

PowerShell→Python 파이프의 인코딩 변환으로 index.html 일부와 b2.json 이름이
리터럴 물음표로 저장됐던 것을 UTF-8 원문으로 복구했다.
HTML 사용자 문구·샘플 차량번호·HTTP 응답·지도 이름을 직접 검사하는 회귀 테스트를 추가했다.
기존 상태코드·동작 테스트만으로는 이 손상을 잡지 못했다.
