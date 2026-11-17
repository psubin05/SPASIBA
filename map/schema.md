# 지도 형식 초안

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
