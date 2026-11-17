# 지도 DB / 수인 서버 연결

## 제공 파일

- `db/map_schema.sql`: server_interface 5.2의 A 담당 6개 테이블.
- `db/map_seed.sql`: 현재 지도를 검증한 후 생성한 스키마+데이터 트랜잭션.
- `tools/export_map_sql.py`: 지도 수정 시 SQL 재생성 도구.

```powershell
.\.venv\Scripts\python.exe -m tools.export_map_sql
```

PostgreSQL 접속 환경에서 파일을 검토한 뒤 적용한다.

```powershell
psql --set ON_ERROR_STOP=1 --file db/map_seed.sql --dbname spasiba
```

접속 대상·인증 설정은 공용 DB 환경에 맞춘다. 비밀번호는 파일에 넣지 않는다.
현재 작업 환경에 PostgreSQL/psql이 없어 실제 서버 적용은 아직 수행하지 않았다.
이 SQL이 이미 존재하는 수인 서버 스키마와 호환되는지도 실제 DB에서 확인해야 한다.

## 참조와 갱신 규칙

테이블 순서는 zone → camera → map_node → parking_slot → map_edge → qr_location이다.
수인의 parking_event 등에서 camera/zone/parking_slot을 참조하므로 지도부터 적재한다.
같은 ID는 갱신하며 기존 데이터를 삭제하지 않는다. 제거된 칸·간선을 자동 정리하지는 않는다.
배치 변경 시 오래된 간선이 남지 않도록 기존 DB와 변경 목록을 대조해야 한다.
양방향 간선은 작은 node_id를 from_node로 정규화해서 한 행만 저장한다.

`parking_slot.polygon JSONB`는 제안된 `/map` 응답에 필요한 웹 지도 경계다.
기준 테이블 정의에 이 필드가 없어 추가 컬럼으로 제공한다. 카메라 roi와는 다른 좌표계다.
이 확장은 원본 인터페이스를 수정하지 않고 여기에 기록했다.

## 앱 통합

현재 `server.app.create_app()`이 앱 시작 시 지도 JSON을 검증하고 메모리 그래프를 만든다.
현재 API의 실행 중 데이터 원본은 JSON이며 PostgreSQL에서 지도를 읽는 기능은 아직 없다.
수인 쪽 라우터는 생성된 앱에 `app.include_router(수인_라우터)`로 연결할 수 있다.
지도 앱의 app.state.maps는 지도 전용 캐시로 유지한다.

Web 요청 순서:

1. GET /qr/{location_id} → 출발 QR 검증.
2. GET /vehicles/{plate}/last-location → 수인 담당.
3. CONFIRMED일 때 GET /route?from={location_id}&to={slot_id}.
4. path의 x/y는 `/map`과 같은 좌표계, steps는 안내 문장이다.

PENDING이면 칸까지 안내하지 않는다. 404면 차량 기록 없음/출차 상태를 안내한다.
사용자용 화면과 관리자 인증은 각 담당 구현을 연결해야 한다.
