# 담당 범위와 시작 상태

서버 담당 계획 6.1과 server_interface v0.3을 먼저 대조했고, 추가 첨부된 v0.3.1로 기준을 갱신했다.
문서상 A(떵개)는 지도·경로, B(수꽝/수인)는 수신·DB·매칭이다.
server_interface 작성은 공통 계약의 초안 작성이며 구현 완료 증거는 아니다.

## 구현 기준 확정 (사용자 지시)

`docs/server_interface.md`를 구현 기준으로 사용한다. 이전 작업 계획과 충돌하는
API·식별자·테이블·응답 형식은 이 인터페이스를 따른다. 원본에 남은 초안·미합의
표시는 그대로 보존하며, 사용자의 기준 선택을 팀 전체 합의 완료로 해석하지 않는다.

- A의 API: `/qr/{location_id}`, `/route?from={location_id}&to={slot_id}`.
- `/map?floor=`는 인터페이스의 추가 제안 응답 형식에 맞춰 준비한다.
- `/route`의 입력은 QR location_id와 slot_id이고 node_id는 내부에서 해석한다.
- 응답은 `from`, `to_slot`, `floor`, `distance_m`, `path`의 node/x/y, `steps`를 따른다.
- QR 응답은 location_id/name/floor/node_id, 오류는 error.code/message를 따른다.
- 지도와 경로 검증·시뮬레이션은 A의 작업 범위로 유지한다. 구체적인 화면과
  조작 방식은 인터페이스에 정해져 있지 않으므로 별도 구현 사항으로 관리한다.
- 웹 연동은 수인의 `/vehicles/{plate}/last-location` 결과 중 확정된 slot_id를
  도착점으로 사용한다. PENDING일 때 임의의 주차면 경로를 생성하지 않는다.

## A 담당

1. 지도 JSON 형식, 실제 모형 실측 데이터, 지도 검증.
2. Dijkstra 최단 보행 경로 및 좌우회전 안내문.
3. GET /qr/{location_id}, GET /route?from={location_id}&to={slot_id}.
4. GET /map?floor= 는 Web 파트와 합의할 추가 제안.
5. zone, camera, parking_slot, map_node, map_edge, qr_location 데이터 관리.

수인 담당: MQTT, parking_event, 입출차 세션, 매칭, 차량 검색, 관리자 검토.
공동 담당: 앱 뼈대, 인터페이스 검토, 통합 테스트, 실제 연결과 배포.

## 문서 차이

11/11 계획의 /kiosks, /vehicles, 확률표 누적 매칭 대신 11/12 인터페이스
초안의 /qr, /vehicles/{plate}/last-location 및 EXACT/EDIT1 규칙을 기준으로 시작한다.
원본 인터페이스는 docs/server_interface.md에 그대로 보관했다.
v0.3의 체크리스트에 남아 있던 '이벤트 2번'은 v0.3.1에서 votes 5 이상으로 수정됐다.
개발 기준은 사용자가 선택한 server_interface이며 팀 전체 합의 완료로 간주하지 않는다.

## 이번에 시작한 것

- 그림 기반 샘플 지도 및 형식 설명.
- 지도 참조·거리·연결성 검증, 직접 구현한 Dijkstra, 기본 회전 안내.
- NetworkX와 모든 노드 쌍 최단거리 비교 테스트.

## 1차 구현 업데이트

- `/qr/{location_id}`, `/route?from=&to=`, `/map?floor=`, `/health` 구현.
- 앱 시작 시 지도 검증 및 메모리 그래프 로드, 공통 오류 응답 적용.
- `/simulator`: QR·도착 주차면 선택, SVG 경로 표시, 안내문, 이동 재생, API 응답 확인.
- `tools/check_map.py`: 등록 관계·연결성·거리 검증 및 SVG 출력.
- `tools/benchmark_route.py`: 로컬 HTTP 응답 시간 측정.
- API 통합 테스트 추가. 지도 API는 원문에 추가 제안으로 남아 있으며 구현을 제공한 상태다.

실제 모형 지도 입력과 PostgreSQL 적재, 수인의 차량 검색 API 연결은 다음 작업이다.
안내는 QR에서의 초기 시선 방향을 모르므로 첫 구간 진행 방향을 따라선 상태를 가정한다.
실측 도면과 QR 부착 방향을 받으면 좌표·거리와 초기 방향 안내를 보완한다.

## 3D 및 지도 DB 준비 업데이트

- 카메라는 사용자 지시에 따라 A열·B열별 기존 임시 배치를 유지한다.
- 3D/평면 전환, 회전·확대, 장난감 차량 배치, 재생·정지·재개 구현.
- 제작 크기 환산 및 SVG 평면도 저장 구현. 실제 모형은 아직 미제작이다.
- API·지도·DB 내보내기 Python 테스트 13개 통과.
- DOM/Canvas 대역을 사용하는 Node 테스트로 3D 좌표·재생·전환·치수 계산 확인.
- PostgreSQL 지도 스키마 및 검증된 JSON→SQL 생성 도구 준비.
- 실물 제작 절차: docs/demo_build.md, 공용 DB/수인 서버 연결: docs/map_db_handoff.md.

실제 브라우저 시각 검증은 도구의 URL 확인 실패로 아직 수행하지 못했다.
DB 스크립트는 실제 PostgreSQL에서 미실행이며 앱은 현재 JSON에서 지도를 읽는다.
실측 데이터·ROI, 실제 차량 검색 API, DB 접속 환경을 확보하면 통합 검증을 이어간다.

## 입차 → QR 검색 연결

사용자 지시: 우드락 제작은 뒤로 두고, 차단기 번호 저장부터 나중의 QR 차량 찾기까지 연결한다.
별도 demo_app에서만 켜지는 SQLite 시연 어댑터와 화면을 연결했다.
기존 map-only 앱 및 수인 담당 정식 백엔드의 책임은 유지한다.
사용자는 주차면을 직접 고르는 대신 번호로 검색하며 PENDING/404에서 경로가 차단된다.
실제 카메라·OCR·MQTT 연결 전의 수동 인식 결과 시연이며 전체 절차는 full_flow_demo.md에 있다.
