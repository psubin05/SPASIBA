# SPASIBA

서버 A 담당의 지도·경로 개발 시작 코드.
담당 범위와 문서 차이는 [작업 메모](docs/map_route_start.md),
지도 형식은 [schema](map/schema.md), 공통 계약은 [인터페이스 초안](docs/server_interface.md)을 참고한다.

현재는 개발용 샘플 지도, FastAPI 지도·경로 API, 브라우저 3D 경로 시뮬레이터다.
실제 모형 지도와 PostgreSQL 연동은 아직 없다.

저장소 폴더에서 테스트:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m uvicorn server.demo_app:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000/simulator 접속.
차단기 인식 결과 저장 → 주차면 관측 전송 → 이용자 차량번호 검색 → 이동 재생 순서로 확인한다.
QR 위치 링크로 나중에 접속하는 흐름도 재현한다. 자세한 절차는 [전체 흐름 시연](docs/full_flow_demo.md).
실제 카메라 대신 인식 결과를 입력하는 로컬 어댑터이며 기록은 .local/demo.sqlite3에 저장된다.
지도 API만 실행하려면 위 명령의 server.demo_app:app을 server.app:app으로 바꾼다.
3D/평면 전환, 회전·확대, 일시정지·재개, 장난감 차량 배치, 제작 치수 환산과 SVG 저장을 제공한다.
카메라는 A/B열별 기존 임시 배치다.
제작 순서는 [모형 제작 메모](docs/demo_build.md), DB와 수인 서버 연결은
[연결 메모](docs/map_db_handoff.md)를 참고한다.
API 문서는 http://127.0.0.1:8000/docs 에서 확인한다.
서버 종료는 실행 터미널에서 Ctrl+C.

```powershell
.\.venv\Scripts\python.exe -m tools.check_map --svg map/preview.svg
.\.venv\Scripts\python.exe -m tools.benchmark_route
```

두 번째 명령은 서버가 실행 중일 때 localhost HTTP 응답 시간을 측정한다.
시뮬레이터의 시간은 브라우저에서 QR 조회와 경로 수신까지의 시간으로,
단독 `/route` 측정값과 다르다. 이동 재생은 시각적 검증용이며 실제 보행 시간 추정은 아니다.

샘플 QR `QR-B2-ENT1` → 주차면 `B2-A-03` 경로는 16m다.

Python 테스트와 Node 기반 시뮬레이터 동작 검증을 함께 실행하려면:

```powershell
.\.venv\Scripts\python.exe -m tools.verify
```

Node 테스트는 DOM/Canvas 대역을 사용하며 실제 브라우저의 화면 검증을 대신하지 않는다.

현재 검증 환경은 Python 3.13 / Node.js 20이다. requirements-lock.txt는 검증한 패키지 버전을 고정한다.
남은 실제 연동 작업과 검증 범위는 [남은 작업](docs/remaining_work.md)을 참고한다.
