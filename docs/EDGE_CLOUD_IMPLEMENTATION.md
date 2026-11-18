# SPASIBA Raspberry Pi Edge–Cloud 구현 기록

> 이 문서는 통합 이전 Raspberry Pi 브랜치의 구현 기록이다. 현재 설정과 토픽은 [실행 가이드](RUN_INTEGRATION.md)와 [인터페이스 계약](INTERFACE_CONTRACT.md)을 따른다.

작성일: 2026-11-18. 기준: 사용자 제공 SAD v1.2 및 인터페이스 v0.3.1(11/17).
두 기준 문서 원본은 저장소에 없으므로 대화에 제공된 규격을 사용했다.
새 브랜치명은 사용자의 최종 지시에 따라 **`raspberrypi`**다.

## 1. 작업 개요와 기존 코드 보존

- 시작 브랜치: `heewoo/plate_ocr` (작업 시작 시 origin보다 1커밋 뒤).
- 원격 변경을 pull/merge하거나 기존 브랜치 포인터를 수정하지 않았다.
- 기존 미커밋 수정: `src/main.py`, `src/paddle_ocr.py`, `src/pi_camera.py`, `src/webcam.py`.
  PaddleOCR 우선 초기화 및 CPU 스레드 최대 4개 제한 변경을 그대로 별도 커밋으로 보존했다.
- 기존 untracked 파일: 이전 카메라 점검에서 만든 `camera_check.jpg`. 보존하되 Git에서 제외했다.
- 백업: 저장소 밖 `/home/user/spasiba_backups/hybrid_subin_before_edge_20261118.tar.gz`,
  `local_ocr_20261118.patch`. 압축에는 `.venv`, 모델, 캐시를 제외했다. 이 파일들은 원래 위치에 그대로 있다.
- 모델 `models/detector/plate_v3.pt`는 기존 Git LFS 추적 대상이다. 기존 모델 내용과 LFS 규칙을 변경하지 않았다.
  기존 PaddleOCR 캐시는 `models/paddlex/`, Python 환경은 `.venv`이며 Git에서 제외된다.
- YOLO/PaddleOCR/추적 알고리즘은 유지한다. 카메라 실행 파일에는 선택적 Edge 훅과 프레임 OCR 오류 처리를 추가했다.

## 2. 구현 완료 기능

| 파일 | 역할 |
| --- | --- |
| `src/edge_cloud/config.py` | JSON + 환경변수 설정, ID·TLS·슬롯·토픽 검증 |
| `src/edge_cloud/events.py` | 번호 정규화, 전체 문자열 검사, 최근 최대 10개 투표, UUID v4·시간대 포함 이벤트 |
| `src/edge_cloud/slots.py` | EMPTY/OCCUPIED/UNKNOWN 상태 형식, 단일 슬롯·bbox 중심의 ROI 후보 계산 |
| `src/edge_cloud/store.py` | SQLite WAL/FULL outbox, 슬롯별 마지막 번호·상태, 원자적 중복 방지 |
| `src/edge_cloud/transport.py` | paho MQTT v3.1.1 persistent session, TLS, QoS 1, PUBACK, 재연결, LWT |
| `src/edge_cloud/runtime.py` | OCR track → 슬롯 → 이벤트 → outbox 연결, 선택 기능 초기화 실패 격리 |
| `src/edge_cloud/crops.py` | 선택적 슬롯별 JPEG 캐시·요청 응답, event_id 일치 검증·TTL |
| `src/edge_cloud/__main__.py` | 모델 없이 합성 OCR 결과로 MQTT/outbox를 점검하는 CLI |
| `config/edge.example.json`, `config/roi.example.json` | 안전한 기본 설정과 여러 슬롯 ROI 형식 예시 |
| `requirements_edge.txt` | 선택 의존성 paho-mqtt |
| `tests/test_edge.py`, `tests/test_mqtt_integration.py` | 저장·중복·투표·보류 및 실제 TLS 브로커 테스트 |
| `src/pi_camera.py`, `src/webcam.py` | 기존 옵션 유지, `--mqtt --edge-config` 선택 통합 |

### 실제 동작

1. 기존 Tracker의 `readings`에서 최근 최대 10개의 유효 읽기를 사용한다. `votes`는 1등 번호 횟수,
   `frames`는 형식이 맞는 읽기 수다. 동률은 보류하며, 기본 최소 투표는 5다.
2. 명시적 단일 슬롯 또는 ROI 중심점이 유일하게 일치하는 슬롯을 찾는다. 같은 슬롯에 여러 트랙이
   보이면 보류한다. 현재 읽기와 과거 투표 결과가 다르거나 현재 형식이 틀리면 과거 결과를 발행하지 않는다.
3. 기본 UNKNOWN 상태에서는 발행하지 않는다. 외부의 신뢰할 수 있는 OCCUPIED 입력 또는
   리허설용 `publish_on_consensus: true` 설정이 있어야 발행한다. 이 설정은 정차를 검출하는 기능이 아니다.
4. 이벤트와 마지막 번호 상태를 같은 SQLite 트랜잭션으로 보관한다. 번호가 같으면 가림·재검출·재시작 후에도
   새 이벤트를 만들지 않는다. 다른 번호가 충분한 투표로 확정되면 새 UUID 이벤트를 만든다.
5. 네트워크 작업은 별도 스레드에서 수행한다. 이벤트는 한 번에 1개씩 보내고 PUBACK 콜백을 받은 뒤에만
   outbox에서 삭제한다. 발행 반환 전에 ACK가 오는 경합과 연결 단절 직전 publish도 처리한다.
6. Wi-Fi 단절은 paho가 재연결하고, 프로세스 재시작은 SQLite가 복구한다. payload와 UUID를 유지한다.
   브로커가 받은 직후 Pi가 죽으면 중복 전달될 수 있으므로 서버의 event_id 중복 제거는 필요하다.
7. QoS 1 PUBACK는 브로커 수신 확인이다. 서버 DB 저장 완료를 보장하는 응답은 이 규격에 없다.
8. 연결 시 retained `online + ts`, 정상 종료 시 retained `offline + ts`, 비정상 종료 LWT는 `offline`만 보낸다.
   이벤트와 crop 응답은 retained가 아니다. 브로커 장애 중에는 offline도 도달하지 않을 수 있다.
9. 미검출·트랙 만료만으로 EMPTY를 설정하지 않는다. 외부 검증기가
   `runtime.store.set_occupancy(slot_id, Occupancy.EMPTY)`를 명시적으로 호출할 때만 마지막 번호를 초기화한다.
   다시 OCCUPIED가 되어야 같은 번호의 새 세션을 발행할 수 있다.
10. outbox 기본 상한은 10,000건이다. 가득 차면 새 이벤트와 중복 방지 상태 변경을 보류하고 오류를 로그에 남긴다.
    OCR은 계속된다. 디스크 고장·용량 부족 시 무손실 보장은 할 수 없으며 파일을 자동 삭제하지 않는다.

## 3. 미구현 및 기본 구조만 있는 기능

- **정차·빈 칸 자동 판단:** 구현하지 않았다. 번호판 미검출은 빈 칸 근거가 아니다.
- **실제 슬롯 배치:** 예시 ROI는 1280×720 픽셀 좌표의 형식 예시일 뿐이다. 카메라 설치와 영상 해상도에 맞춰 실측해야 한다.
  단일 슬롯도 담당자가 확인한 매핑을 넣어야 한다. 예시 식별자는 실제 등록값이 아니다.
- **crop:** 기본 비활성화. 활성화하면 이벤트 생성 시 슬롯당 최근 JPEG 1장만 메모리에 보관한다.
  요청의 slot_id와 event_id가 정확히 일치하고 TTL(기본 600초) 이내인 경우만 응답한다.
  긴 변 640px·JPEG 원본 100,000바이트 이하이며 Base64 JSON 크기는 이보다 크다.
  이전 이벤트·재시작 후 사진·없는 사진에는 응답을 보내지 않고 로그를 남긴다. 오류 응답 토픽은 미합의다.
  캐시는 최대 슬롯당 1장이고 오래된 항목은 요청 시 만료 처리한다. 서버 review/출차 알림을 받는 삭제 프로토콜은 없다.
- **주기적 recheck**, 연속 차량 추적, 입·출차 세션 매칭, API·DB 서버·웹·경로 탐색은 구현하지 않았다.
- 서버의 crop 요청/응답 재시도 정책, ACL 실제 적용, 최종 클라우드 연결은 미검증이다.

## 4. 클라우드 팀과 합의할 사항

- 브로커 주소·계정·CA 및 필요 시 클라이언트 인증서, 서버의 camera/zone/slot 등록값.
- 기본 이벤트 토픽: `spasiba/{zone_id}/{camera_id}/event`.
- 상태 기본값은 v0.3.1의 `spasiba/{zone_id}/{camera_id}/status` 제안이다.
  `status_topic`으로 SAD v1.2의 `spasiba/{camera_id}/status`도 선택할 수 있다. ACL도 같은 경로로 맞춰야 한다.
- Pi ACL: 자기 event/status/crop 발행, 자기 crop_request 구독. 서버 ACL 설정은 이 작업 범위 밖이다.
- 전송 번호 검사: 선택 지역명 17개 + ASCII 숫자 2~3개 + 한글 1개 + 숫자 4개.
  공백·하이픈·중점 제거, 전각 숫자 변환. 불필요한 다른 문자는 제거해서 정상 번호로 만들지 않는다.
  **기존 OCR의 허용 한글 목록은 더 엄격하며 그대로 보존했다.** 전체 `[가-힣]` 허용과 통일할지는 팀 합의가 필요하다.
- votes/frames는 기존 track의 유효 readings 기준이다. Tracker가 연속 불일치로 기록을 초기화하는 기존 동작도 유지했다.
  최소 5표는 제안 기본값이며 `min_votes`로 조절할 수 있다. 화면의 기존 `--min-votes`와 전송 기준은 별개다.
- 슬롯-카메라 매핑, 단일 슬롯 시야 보장, ROI 좌표·경계, 정차/EMPTY의 신뢰할 입력을 확정해야 한다.
- crop 활성화·보관 TTL·JPEG 100KB 정의·만료/불일치 응답·삭제 알림 프로토콜.
- 장치 NTP 동기화가 필요하다. recognized_at은 OS 시간대의 ISO 8601이며 서버는 오프셋을 포함해 처리해야 한다.
- SAD의 구역 단위 범위에서 개별 칸 단위로 바뀌는 사항은 문서 v1.3에 명시해야 한다.

## 5. Raspberry Pi 실행 방법

아래는 모두 `~/SPASIBA` 기준이다. 기존 가상환경을 재생성하거나 모델을 재설치하지 않는다.

```bash
cd ~/SPASIBA
source .venv/bin/activate
python -m pip install -r requirements_edge.txt
```

Picamera2가 없는 새 Pi에서만 시스템 패키지를 설치하고 `--system-site-packages` 환경을 준비한다.
기존 환경이 있다면 그대로 사용한다.

```bash
sudo apt install python3-picamera2 python3-opencv
```

### 기존 OCR 단독 실행

```bash
cd ~/SPASIBA
source .venv/bin/activate
bash run_pi_camera.sh --width 1280 --height 720 --det-size 640 --process-every 10
# USB 웹캠용 기존 명령도 유지
bash run_webcam.sh --camera 0 --det-size 640 --process-every 3
# 모델 로딩/이미지 처리 점검 (번호판이 없는 사진은 결과 0건이 정상)
python src/main.py --image camera_check.jpg --output outputs/image
```

### 설정과 인증 정보

```bash
cp config/edge.example.json config/edge.local.json
# 이 파일에서 실제 등록된 zone_id/camera_id와 확인된 single_slot 또는 rois를 수정한다.
# 미확정 값은 null/빈 객체로 남겨 발행을 보류한다.
nano config/edge.local.json
export SPASIBA_HOST='broker.example.org'  # 실제 서버 주소로 교체
export SPASIBA_USERNAME='your-camera-account'
read -r -s -p 'MQTT password: ' SPASIBA_PASSWORD; echo
export SPASIBA_PASSWORD
export SPASIBA_CA='/absolute/path/to/ca.crt'  # 사설 CA일 때; 공인 CA는 설정 생략 가능
```

예시 주소·계정은 그대로 실서버에 접속할 수 있는 값이 아니다.
환경변수: `SPASIBA_HOST`, `PORT`, `USERNAME`, `PASSWORD`, `CA`, `CERT`, `KEY`, `DATABASE`,
`ZONE_ID`, `CAMERA_ID`, `STATUS_TOPIC` (각 항목에 `SPASIBA_` 접두사).
JSON에 비밀번호를 쓰지 않는 것을 권장한다. `.local.json`, `.env*`, 인증서·키·SQLite·출력·가상환경은 Git 제외다.
TLS 기본 활성화, 포트 8883, CA/호스트명 검증을 끄는 옵션은 없다.
평문 `tls:false`는 localhost/127.0.0.1/::1 테스트에만 허용된다.

### 모델 없는 로컬 MQTT 테스트

설치된 로컬 Mosquitto가 없다면 아래 명령으로 설치할 수 있다. 이 작업에서는 시스템 서비스 설치 대신
`/tmp/spasiba-mosquitto`에 패키지를 풀어 테스트했다.

```bash
sudo apt install mosquitto mosquitto-clients openssl
cd ~/SPASIBA
mkdir -p outputs
cat > outputs/mosquitto-test.conf <<'CONF'
listener 18883 127.0.0.1
allow_anonymous true
CONF
mosquitto -c outputs/mosquitto-test.conf -v
```

다른 터미널에서 환경변수의 실서버 설정이 남아 있지 않은지 확인하고 합성 데이터 전용 설정을 만든다.
**아래 ID는 테스트 전용이며 실제 카메라 설정에 복사해서 쓰지 않는다.**

```bash
cd ~/SPASIBA
source .venv/bin/activate
unset SPASIBA_HOST SPASIBA_PORT SPASIBA_USERNAME SPASIBA_PASSWORD SPASIBA_CA SPASIBA_CERT SPASIBA_KEY SPASIBA_DATABASE SPASIBA_ZONE_ID SPASIBA_CAMERA_ID SPASIBA_STATUS_TOPIC
cat > config/test.local.json <<'JSON'
{"zone_id":"B2-A","camera_id":"CAM-B2-A-99","host":"127.0.0.1","port":18883,"tls":false,"single_slot":"B2-A-99","database":"outputs/edge-test.sqlite3","publish_on_consensus":false}
JSON
PYTHONPATH=src python -m edge_cloud --config config/test.local.json --synthetic --wait 10
# 서버 없이 SQLite 저장만 확인
PYTHONPATH=src python -m edge_cloud --config config/test.local.json --synthetic --offline
```

구독 확인용 터미널:

```bash
mosquitto_sub -h 127.0.0.1 -p 18883 -t 'spasiba/#' -q 1 -v
```

CLI는 테스트 전용 단일 슬롯을 OCCUPIED로 설정한다. 반복 실행 시 동일 번호는 중복 생성되지 않는다.
새 번호를 시험하려면 `--plate '34나5678'`를 추가한다. 운영 DB에 합성 테스트를 실행하지 않는다.

### OCR + MQTT 통합 실행 및 로그

```bash
cd ~/SPASIBA
source .venv/bin/activate
mkdir -p outputs
bash run_pi_camera.sh --width 1280 --height 720 --det-size 640 --process-every 10 \
  --mqtt --edge-config config/edge.local.json 2>&1 | tee outputs/edge.log
```

이 예시는 기본 UNKNOWN이면 발행을 보류한다. 담당자가 단일 슬롯/ROI와 시연 조건을 확인한 뒤
`publish_on_consensus:true`를 명시적으로 켜면 정차 검출 없이 투표 기준으로 발행한다.
실제 정차 감지기로 OCCUPIED/EMPTY를 공급하는 모듈은 추후 연결한다.
`event queued`, `MQTT publish`, `MQTT PUBACK`, `MQTT connect failed` 로그를 구분해서 확인한다.
같은 camera_id·SQLite로 여러 프로세스를 동시에 실행하지 않는다.
서버 미접속은 계속 재연결하며 OCR을 막지 않는다. 잘못된 설정은 오류 로그 후 Edge만 비활성화한다.

### 테스트 명령

```bash
cd ~/SPASIBA
source .venv/bin/activate
python -m unittest discover -s tests -v
python -m compileall -q src
sha256sum -c MODEL_SHA256SUMS.txt
# 실제 로컬 TLS 브로커 테스트까지 수행 (자동 생성한 임시 인증서/포트 사용)
SPASIBA_TEST_MOSQUITTO="$(command -v mosquitto)" python -m unittest discover -s tests -v
```

환경변수를 지정하지 않으면 실제 브로커 테스트는 SKIP된다. 단위 테스트 PASS와 실제 MQTT PASS를 혼동하지 않는다.
TLS 테스트 인증서는 임시 디렉터리에서 생성·삭제하며 Git에 들어가지 않는다.

## 6. 실제 테스트 결과

- 기존 OCR 핵심 테스트 7개: PASS.
- Edge 단위 테스트: 번호·투표·UUID/시각·중복·재시작·명시적 EMPTY·UNKNOWN 보류·미확정/중복 ROI·
  복수 트랙·오래된 투표·큐 상한·잘못된 설정·서버 부재·crop 제한·PUBACK 경합을 검증.
- 실제 Mosquitto 2.0.21 / paho-mqtt 2.2.0, loopback TLS: 이벤트 수신·QoS 1 PUBACK·retained online/offline·
  브로커 중단/재연결·프로세스 재시작 복구·동일 event_id·비정상 종료 LWT·crop·계정 인증·신뢰하지 않는 CA 거부를 검증.
- 첫 MQTT 테스트에서 브로커 재시작 후 테스트용 구독자가 구독을 잃어 수신 검사 2개 실패했다.
  테스트 구독자를 persistent session + 브로커 persistence로 수정한 후 재실행했다.
- 잘못된 CA의 음성 테스트에서는 paho 2.2.0의 SSL 소켓 ResourceWarning이 관찰됐다. 인증서 검증 거부와
  outbox 보존은 성공했다. 장기 실행에서 이 외부 라이브러리 경고의 반복 여부는 추가 확인이 필요하다.
- 이미지 입력 `src/main.py --image camera_check.jpg`: 종료 코드 0, 결과 `[]`.
  YOLO/PaddleOCR 실제 로딩·추론 성공이며 번호판 정확도 검증은 아니다.
- 실제 imx708: rpicam 목록 감지 및 1280×720 JPEG 촬영 성공. 사진은 흐렸고 읽을 번호판이 없었다.
- 실제 Picamera2 + YOLO + PaddleOCR + MQTT 비접속: 1280×720, 2프레임 실행 종료 코드 0.
  연결 실패 로그가 있어도 OCR 루프와 카메라 정상 종료까지 완료했다.
- 실번호판을 카메라에 보여 확정 이벤트가 실제 클라우드 DB까지 저장되는 시험, NFR-01 100회 정확도,
  NFR-02 웹 응답 성능, 장시간 메모리·발열·디스크 장애 시험은 수행하지 않았다.
- 테스트 로그는 Git 제외 `outputs/edge-check/`에 보관한다.

## 7. Git 작업 내역

- 시작: `heewoo/plate_ocr` → 새 작업 브랜치 `raspberrypi`.
- 기존 로컬 OCR 보존 커밋: `ce83aec` (`Preserve local Raspberry Pi OCR initialization and CPU thread fixes`).
- 새 Edge 구현·테스트·문서는 별도 커밋으로 보관한다. 정확한 목록은 `git log --oneline raspberrypi -3`로 확인한다.
- `main` 및 `heewoo/plate_ocr`에 merge/push하지 않는다. 강제 복원·강제 push는 사용하지 않는다.
- 원격 대상은 사용자 최종 브랜치명에 맞춘 `origin/raspberrypi`다.
- 최종 테스트 집계와 원격 반영 결과는 아래 완료 기록에 기재한다.

### 완료 기록

- 전체 최종 회귀 테스트: **30개 PASS** (기존 OCR 7 + Edge 16 + 실제 TLS/MQTT 7), SKIP 없음.
- `python3 -m compileall -q src`, `git diff --check`: PASS.
- `sha256sum -c MODEL_SHA256SUMS.txt`: `plate_v3.pt` PASS, 기존 모델 보존 확인.
- 모델 없는 CLI 오프라인 실행: 첫 실행 1건 저장, 재실행 새 이벤트 0건/기존 pending 1건 보존 확인.
- crop TTL 기본 600초는 서버의 보류 120초 이후 요청에도 응답할 여유를 둔 임시 설정이며 합의 대상이다.

### 커밋과 원격 반영 결과

1. `ce83aec` — 기존 로컬 OCR의 Pi 초기화/CPU 스레드 수정 보존.
2. `cc03e00` — 선택적 Edge–Cloud 구현·테스트·README·본 문서 추가.
3. 후속 문서 커밋 `Document verification results and GitHub authentication blocker` — push 결과 기록.
   해당 커밋 해시는 `git log -3 --oneline`로 확인할 수 있다.

`git push -u origin raspberrypi`를 실제 시도했으나 다음 인증 오류로 실패했다.

```text
fatal: could not read Username for 'https://github.com': No such device or address
```

따라서 **원격 브랜치 생성·업스트림 설정·원격 반영은 미완료**다. 원격 raspberrypi는 사전 조회 시 없었다.
이 인증 오류 이후 강제 push나 다른 브랜치로의 push는 하지 않았다.
모든 작업은 로컬 raspberrypi의 커밋에 보존되어 있다. GitHub 인증을 설정한 후 다음 명령으로 재시도한다.
비밀번호·토큰을 파일이나 명령행 URL에 넣어 커밋하지 않는다.

```bash
cd ~/SPASIBA
git switch raspberrypi
git push -u origin raspberrypi
```

## 2026-11-18 폴더 구조 정리

사용자 요청으로 `hybrid_subin/` 내부 전체를 `SPASIBA/` 바로 아래로 이동했다.
기존 detector와 기존 루트 README는 각각 `legacy/detector/`, `legacy/ROOT_README.previous.md`에 보존했다.
모델·가상환경·로컬 설정·SQLite와 출력 파일도 그대로 옮겼으며 삭제하지 않았다.
가상환경의 activation 스크립트와 console-script 절대 경로를 새 `.venv` 위치에 맞췄다.
현재 README 및 문서의 실행 경로는 `~/SPASIBA` 기준이다.
이전 구현/백업/커밋에 대한 `hybrid_subin` 언급은 당시 경로를 뜻한다.

폴더 이동 후 검증: 새 루트에서 기존 OCR·Edge·실제 로컬 TLS/MQTT 총 30개 테스트 모두 PASS,
모델 체크섬 PASS, compileall·실행 스크립트 문법·Pi Camera CLI 도움말 PASS.
이동한 가상환경의 Python과 pip가 `/home/user/SPASIBA/.venv`를 사용하는 것도 확인했다.
이번 구조 정리에서 카메라 촬영 자체는 다시 실행하지 않았다.
작업 시작 시에는 `raspberrypi`가 `origin/raspberrypi`를 추적하고 있었다.
위의 인증 실패 기록은 최초 구현 당시 시도 결과이며, 이후 원격 반영된 상태에서 이번 정리를 시작했다.
