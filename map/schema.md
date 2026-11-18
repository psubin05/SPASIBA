# 지도 형식 초안

통합 브랜치는 인터페이스 v0.4를 따른다. 카메라 ID는 CAM-B2-01/CAM-B2-02이며
카메라 소속 구역과 다른 구역의 주차면도 parking_slot.camera_id로 연결할 수 있다.
통합 앱의 런타임 지도는 JSON이 아니라 공용 SQLAlchemy DB에서 읽는다.

`b2.json`은 제공된 경로 그림을 옮긴 개발용 샘플이며 실제 모형 실측값이 아니다.
단일 층, 양방향 보행로만 지원한다. 좌표와 간선 거리는 m 단위이며 x는 오른쪽,
y는 아래쪽으로 증가한다. 길찾기 비용은 좌표 간 직선거리 대신 `length_m`을 사용한다.

- `nodes`: `node_id`, `floor`, `x`, `y`, `type`.
- `edges`: `from_node`, `to_node`, 양수 `length_m`. 양방향은 한 번만 등록한다.
- `slots`: `slot_id`, `zone_id`, `camera_id`, `name`, `node_id`, `roi`, `polygon`.
- `qr_locations`: `location_id`, `node_id`, `floor`, `name`.
- `zones`, `cameras`: 최신 인터페이스의 zone/camera 등록 정보.

`slot.node_id`는 차량 중심이 아닌 보행자가 도착할 주차면 앞 노드다.
`polygon`은 웹 지도 좌표, `roi`는 카메라 영상 좌표이며 서로 다르다.
polygon은 현재 샘플 배치의 경계가 입력되어 있다. roi는 실물 카메라 보정 전까지 null이다.
식별자는 server_interface 초안을 따른다.
DB 적재 시 nodes→zones→cameras→slots→edges→qr_locations 순서로 참조를 연결한다.
PostgreSQL 스키마와 SQL 생성 도구는 db/ 및 tools/export_map_sql.py에 있다.
실제 DB 적용과 DB에서 읽는 런타임 로더는 아직 연결하지 않았다.

`demo_layout`은 시뮬레이터 전용 board/aisle/walls/camera_mounts 정보다.
3D의 바닥 좌표는 지도 x/y와 동일하고 z는 위쪽 높이다.
카메라는 A/B별 기존 임시 위치를 유지하며 coverage/FOV를 계산하지 않는다.

## 11/18 회의 배치 (`b2_layout_1118.json`)

- 회의 정리본(`docs/figures/parking_layout_2026-11-18.jpg`)을 옮긴 18칸 지도. `python -m tools.make_layout_1118`로 생성하며,
  손으로 고치지 말고 스크립트의 치수를 고쳐 다시 만든다 (`tests/test_layout_1118.py`가 파일과 스크립트 결과를 대조).
- 구역 3개(`B2-A`, `B2-B`, `B2-C`), 카메라 `CAM-B2-01`(A, 왼쪽 벽)·`CAM-B2-02`(B, 오른쪽 벽)·`CAM-B2-03`(C, 제안 위치).
  B-2 칸 번호는 그림대로 05~07이며 04 누락 여부는 확인 필요.
- 보행로: 위쪽 인도, 블록 둘레 인도, 횡단보도 6개(블록 모서리에서 건넘). QR은 `QR-B2-ENT1`(왼쪽 사람 입구), `QR-B2-ENT2`(아래 QR 입구).
- `demo_layout`에 `aisles`(도로 여러 개), `sidewalks`, `crosswalks`, `gates`, `entry_camera`, `title`을 추가했다. 없으면 예전처럼 `aisle` 하나만 그린다.
- 서버에서 쓰려면 환경변수 `MAP_FILE=map/b2_layout_1118.json`(기본 `map/b2.json`), 빈 DB에 `SEED_SAMPLE_MAP=true`.
