# SPASIBA 통합 실행

서버 PC에는 Docker Engine과 Docker Compose v2, Python 3.10 이상을 준비한다. TLS 구성에는 Compose 2.24.4 이상, OpenSSL 및 `mosquitto_passwd`가 필요하다. Pi에서는 기존 Raspberry Pi OS, 카메라, Python 환경과 모델을 사용한다. 두 장치의 시간을 NTP로 동기화한다. [Docker Compose 오버라이드 규칙](https://docs.docker.com/reference/compose-file/merge/#replace-value)

## A. 로컬 서버와 Fake Pi

아래 명령은 별도의 시연용 Compose 프로젝트를 사용한다. API·PostgreSQL·평문 MQTT는 각각 루프백 8000·5432·1883에 열린다. 샘플 SQL은 테스트 환경에 적용한다.

```bash
cd SPASIBA/server
test -f .env || cp .env.example .env
export COMPOSE_PROJECT_NAME=spasiba-demo
docker compose up -d --build
docker compose exec -T db psql -U spasiba -d spasiba -v ON_ERROR_STOP=1 < db/map_seed.sql
curl -fsS http://127.0.0.1:8000/health

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# /health에 "db":true, "mqtt":"connected"가 표시된 뒤 실행
.venv/bin/python -m tools.fake_pi tools/scenarios/01_exact.json \
  --host 127.0.0.1 --entries-url http://127.0.0.1:8000/entries
curl -fsS http://127.0.0.1:8000/vehicles/12%EA%B0%803456/last-location
```

기대 결과는 `plate_number=12가3456`, `status=CONFIRMED`, `slot_id=B2-A-03`, `source=session`이다. 중복 발행은 시나리오 06으로 시험한다. 서버 로그에 `duplicate`가 기록되고 중복 ID에 해당하는 DB 행은 하나다.

## B. 모델 없이 실제 EdgeRuntime

A의 Compose를 계속 실행한다. A에서 입차한 차량을 출차 처리한다. B부터 시작한다면 출차 요청은 생략한다.

```bash
cd ..
curl -fsS http://127.0.0.1:8000/exits -H 'Content-Type: application/json' \
  -d '{"plate_number":"12가3456"}'
curl -fsS http://127.0.0.1:8000/entries -H 'Content-Type: application/json' \
  -d '{"plate_number":"12가3456"}'
cp config/edge.demo.example.json config/edge.synthetic.local.json
sed -i 's/"port": 8883/"port": 1883/; s/"tls": true/"tls": false/' config/edge.synthetic.local.json
test_run_dir=$(mktemp -d)
SPASIBA_HOST=127.0.0.1 SPASIBA_DATABASE="$test_run_dir/outbox.sqlite3" PYTHONPATH=src \
  server/.venv/bin/python -m edge_cloud --synthetic --config config/edge.synthetic.local.json
curl -fsS http://127.0.0.1:8000/vehicles/12%EA%B0%803456/last-location
```

합성 CLI는 OCCUPIED 상태를 직접 입력한다. 자동 통합 테스트는 UNKNOWN 상태에서 시연 합의에 도달하는 경로도 확인한다. 동일 카메라 ID로 Fake Pi, 합성 CLI, 실제 Pi를 동시에 실행하면 이벤트와 상태가 섞이므로 하나씩 실행한다.

### 자동 회귀·통합 테스트

서버 PC에 Mosquitto 실행 파일과 OpenSSL을 준비한다. 테스트 DB는 시연 DB와 별도로 만든다. 실시간 통합 테스트는 그 안에 실행마다 임시 스키마를 만들고 자체 루프백 브로커를 사용한다. 기존 Fake Pi 네트워크 테스트 두 개에는 A의 1883 브로커도 필요하다.

```bash
cd server
docker compose exec -T db createdb -U spasiba spasiba_integration
export TEST_DATABASE_URL='postgresql+psycopg://spasiba:spasiba@127.0.0.1:5432/spasiba_integration'
export SPASIBA_TEST_MOSQUITTO="$(command -v mosquitto)"
.venv/bin/python -m pip install opencv-python-headless
.venv/bin/python -m pytest -q -rs
cd ..
server/.venv/bin/python -m unittest discover -s tests -v
sha256sum -c MODEL_SHA256SUMS.txt
```

## C. 실제 Pi와 서버 PC를 LAN에서 연결

### 서버 PC의 TLS, 계정, ACL

팀 시연용 CA를 만드는 예시다. 인증서 SAN에는 컨테이너 접속 이름 `broker`와 Pi가 접속할 고정 LAN IPv4를 넣는다. DNS로 연결하는 환경이면 해당 DNS 이름도 SAN에 추가한다. CA 개인 키는 발급 PC에만 보관한다.

```bash
cd SPASIBA/server
test -f .env || cp .env.example .env
read -r -p '서버 PC LAN IPv4: ' MQTT_LAN_BIND_IP
export MQTT_LAN_BIND_IP
umask 077
ca_work=$(mktemp -d)
mkdir -p mosquitto/tls.local
openssl req -x509 -newkey rsa:2048 -days 365 -subj /CN=SPASIBA-LAN-CA \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' \
  -keyout "$ca_work/ca.key" -out mosquitto/tls.local/ca.crt
openssl req -new -newkey rsa:2048 -noenc -subj /CN=broker \
  -keyout mosquitto/tls.local/server.key -out "$ca_work/server.csr"
printf 'subjectAltName=DNS:broker,IP:%s\nextendedKeyUsage=serverAuth\n' "$MQTT_LAN_BIND_IP" > "$ca_work/san.cnf"
openssl x509 -req -in "$ca_work/server.csr" -CA mosquitto/tls.local/ca.crt \
  -CAkey "$ca_work/ca.key" -CAcreateserial -CAserial "$ca_work/ca.srl" -days 30 \
  -extfile "$ca_work/san.cnf" -out mosquitto/tls.local/server.crt
mosquitto_passwd -c mosquitto/tls.local/passwd cloud-server
mosquitto_passwd mosquitto/tls.local/passwd CAM-B2-01
chmod 755 mosquitto/tls.local
chmod 644 mosquitto/tls.local/ca.crt mosquitto/tls.local/server.crt
# 기본 컨테이너 그룹. 사용자 매핑 환경이면 매핑된 GID를 사용한다.
sudo chgrp 1883 mosquitto/tls.local/server.key mosquitto/tls.local/passwd
chmod 640 mosquitto/tls.local/server.key mosquitto/tls.local/passwd
chmod 600 .env
```

`.env`의 `MQTT_USERNAME=cloud-server`, `MQTT_PASSWORD`에 등록한 서버 계정을 넣는다. 카메라 추가 시 해당 계정과 `mosquitto/acl.example`에 네 토픽 규칙을 추가한다. 공개 CA 인증서 `ca.crt`는 신뢰할 수 있는 경로로 Pi에 전달한다. 인증서, 개인 키, 암호 파일과 로컬 환경 설정은 Git에서 제외한다. 서버 방화벽에서는 8883 인바운드를 해당 Pi 또는 시연 서브넷으로 제한한다.

```bash
export COMPOSE_PROJECT_NAME=spasiba-demo
docker compose -f docker-compose.yml -f compose.tls.yml up -d --build
docker compose -f docker-compose.yml -f compose.tls.yml exec -T db \
  psql -U spasiba -d spasiba -v ON_ERROR_STOP=1 < db/map_seed.sql
curl -fsS http://127.0.0.1:8000/health
```

같은 프로젝트에서 TLS 설정을 적용하면 MQTT 호스트 포트는 LAN 주소의 8883으로 바뀐다. 서버 컨테이너는 `broker:8883`과 마운트한 CA를 사용한다. API와 DB는 루프백으로 접근한다. 다른 Compose 프로젝트를 실행 중이면 호스트 포트 점유를 확인한다.

### Raspberry Pi에서 카메라 실행

샘플은 `CAM-B2-01`이 `B2-A-03`을 관찰하는 구성이다. 화면에 여러 칸이 들어오면 `single_slot`을 비우고 실제 영상 픽셀 좌표로 `rois`를 넣는다. 서버 지도에서 해당 칸의 담당 카메라도 확인한다.

```bash
cd ~/SPASIBA
source .venv/bin/activate
python -m pip install -r requirements_edge.txt
rpicam-hello --list-cameras
cp -n config/edge.demo.example.json config/edge.local.json
# Pi에 복사한 공개 CA 파일 경로
export SPASIBA_CA="$PWD/config/ca.crt"
read -r -p '브로커 인증서 SAN의 LAN IP: ' SPASIBA_HOST
read -r -s -p 'Pi MQTT 비밀번호: ' SPASIBA_PASSWORD
printf '\n'
export SPASIBA_HOST SPASIBA_PASSWORD
export SPASIBA_USERNAME=CAM-B2-01
bash run_pi_camera.sh --width 1280 --height 720 --process-every 10 \
  --mqtt --edge-config config/edge.local.json
```

기존 `edge.local.json`을 쓰는 경우 새 ID, TLS 8883, 슬롯·ROI, `publish_on_consensus=true`, `min_votes=5`, 새 시연용 SQLite 경로를 확인한다. 구형 Outbox에는 구형 카메라 ID의 미전송 이벤트가 남을 수 있다. 통합 설정은 새 기본 SQLite 경로를 사용한다. 이전 파일을 지정한 경우 대기 이벤트의 카메라 ID가 다르면 MQTT 전송 시작을 거부한다. 기존 파일을 보관하고 구형 환경에서 먼저 전송 상태를 확인한다. 기존 장치와 지도 매핑에 대한 팀 결정이 나오면 이전 데이터를 이관한다.

서버 PC에서 입차를 등록하고 Pi 화면의 지정 칸에서 번호판이 다섯 프레임 이상 읽히도록 한다.

```bash
curl -fsS http://127.0.0.1:8000/entries -H 'Content-Type: application/json' \
  -d '{"plate_number":"12가3456"}'
curl -fsS http://127.0.0.1:8000/vehicles/12%EA%B0%803456/last-location
```

## 로그, DB, 성공 판정

Pi 로그에서 `DEMO`, `event queued`, `MQTT PUBACK`를 확인한다. 서버 로그에서 카메라 `online`과 이벤트 `assigned`를 확인한다. 정상 종료는 시각이 있는 offline이고, 예기치 않은 끊김은 LWT offline이다. DB에서는 `valid=true`인 이벤트와 `EXACT` 배정, 조회는 `CONFIRMED`, `B2-A-03`, `source=session`이 성공 기준이다.

```bash
docker compose logs --tail=120 api broker
docker compose exec -T db psql -U spasiba -d spasiba -c \
  'SELECT event_id, plate_norm, camera_id, zone_id, slot_id, valid, invalid_reason FROM parking_event ORDER BY received_at DESC LIMIT 10'
docker compose exec -T db psql -U spasiba -d spasiba -c \
  'SELECT session_id, slot_id, method, event_ids FROM slot_assignment WHERE ended_at IS NULL'
```

TLS로 실행 중이면 위 Compose 명령에 `-f docker-compose.yml -f compose.tls.yml`을 붙인다. Crop 테스트에서만 서버 `.env`의 `CROP_ENABLED=true`와 Pi JSON의 `crop_enabled=true`를 적용한다. 보류 120초 후 확인 항목이 생기며 사진 수신 여부는 `review_queue.crop_path`와 로그에서 확인한다. Fake Pi 시나리오 09에는 `--linger 10`을 준다.

| 증상 | 확인 항목 |
| --- | --- |
| MQTT disconnected | 포트, 계정과 ACL, 구독 오류 로그 |
| TLS 인증 실패 | CA 파일, 장치 시간, SAN의 접속 주소, 브로커 파일 읽기 권한 |
| Pi에 OCR만 표시됨 | MQTT 플래그, 설정 경로, 시연 모드, 합의 표, ROI와 동일 칸의 여러 트랙 |
| PUBACK 뒤 조회 PENDING | 이벤트의 `invalid_reason`, 카메라 배정, 등록 차량과 시각, 서버 처리 로그 |
| 같은 칸 재입차 PENDING | 이전 번호가 Pi SQLite에 남은 상태. 1차 시연에서는 새 차량 시나리오를 사용한다. |
| Crop 파일 없음 | 양쪽 활성화, 보류 시간, 세 ID, 용량, Pi 재시작·TTL 만료 |
