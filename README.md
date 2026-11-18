# SPASIBA — 서버 통합

수인의 MQTT·입출차·DB·매칭과 수빈의 지도·QR·최단 경로·3D 시뮬레이터를
하나의 FastAPI 앱과 SQLAlchemy DB에 연결했다. 기준은 [인터페이스 v0.4](docs/server_interface.md)다.

## 로컬 전체 시연

저장소 루트에서 실행한다. Python 3.13 / Node.js 20에서 검증했다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn server.app.demo_main:app --host 127.0.0.1 --port 8000
```

- 시뮬레이터: http://127.0.0.1:8000/simulator
- API 문서: http://127.0.0.1:8000/docs
- 순서: 입차 번호 저장 → 주차 관측 → QR 위치 링크 → 차량 검색 → 경로·이동 재생 → 출차.
- 주차 관측 버튼은 수인의 실제 매칭 서비스로 이벤트를 보낸다. 실제 촬영·OCR은 별도 연결한다.
- 기본 DB는 실행 폴더의 `spasiba_dev.db`이며 샘플 지도는 지도 표가 모두 비어 있을 때만 넣는다.
- 기존 DB·시연 기록을 자동 삭제하거나 덮어쓰지 않는다. 종료는 실행 터미널의 Ctrl+C.

## 정식 앱과 설정

```powershell
.\.venv\Scripts\python.exe -m uvicorn server.app.main:app --host 127.0.0.1 --port 8000
```

정식 앱은 로컬 관측 주입과 자동 샘플 seed가 기본적으로 꺼져 있다.
DATABASE_URL/MQTT 등은 [서버 환경변수 예시](server/.env.example)를 참고한다.
실제 지도는 공용 DB에 등록하며 `/qr`, `/map`, `/route`, 차량 검색 모두 같은 DB를 사용한다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m tools.verify
```

수빈 회귀 테스트 + Node 동작 코드 테스트 + 수인 pytest/통합 테스트를 실행한다.
PostgreSQL·브로커 테스트는 실행 환경이 없으면 skip된다.
Node 테스트는 실제 브라우저 화면·모바일·QR 스캔 검증을 대신하지 않는다.

## 문서

- [통합 변경·실행 방법·주의점](docs/integration_matching.md)
- [수인 서버 상세 설명과 가짜 Pi](server/README.md)
- [지도 형식](map/schema.md)
- [수빈 개발 당시 검증 이력](docs/validation.md)

관리자 API는 기존 서버의 미구현(501) 상태를 유지한다. 실제 장비·브로커·PostgreSQL·
모바일 연결 검증은 별도로 남아 있다. 과거 `legacy_app`/`demo_parking`은 회귀 테스트용이며
위 통합 실행에서는 사용하지 않는다. 우드락 제작은 현재 보류 상태다.
