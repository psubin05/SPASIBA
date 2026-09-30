# 번호판 인식 시험 키트

이 키트는 EasyKoreanLpDetector를 재사용해 사진 폴더를 일괄 평가하고, 카메라나 동영상 입력으로 실시간 인식을 확인합니다.

## 설치

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Ubuntu/Debian에서 가상환경 생성 시 `ensurepip is not available` 오류가 나면 먼저 `python3-venv` 패키지를 설치하세요.

이 README와 `lp_engine.py`, `test_images.py`, `live_webcam.py`는 저장소 루트에 둡니다. 저장소에는 번호판 탐지 가중치와 OCR 가중치가 포함되어 있습니다. 첫 실행 때 EasyOCR의 문자 검출 모델, YOLOv5 코드가 내려받아질 수 있습니다. 네트워크가 제한되면 YOLOv5를 미리 복제하고 `--yolov5 ./yolov5`를 지정하세요.

## 실시간 카메라

```bash
python live_webcam.py
```

`q`/ESC 종료, `s` 화면 저장, `r` 투표 초기화입니다. 결과는 `live_log/events.csv`에 쌓입니다. `--cam 1`로 카메라를 바꾸거나 `--source sample.mp4`로 동영상을 입력할 수 있습니다. GUI 없는 환경에서는 `--no-display --source sample.mp4 --max-frames 60`을 사용할 수 있습니다.

초록 상자는 번호판 형식 정규식을 통과한 결과, 주황 상자는 통과하지 않은 결과입니다. 최근 추론 결과 중 같은 형식 결과가 기본 10회 안에 3회 이상 나오면 확정 표시합니다.

## 사진 폴더 일괄 시험

```bash
python test_images.py --images ./photos
```

기본 파일명 규칙은 `정답번호_조건1_조건2_순번.jpg`입니다. 예: `12가3456_yaw20_pitch0_near_01.jpg`. 또는 CSV에서 `filename,plate,conditions` 열을 제공하고 `--labels labels.csv`로 읽을 수 있습니다. `conditions`는 세미콜론으로 구분합니다.

결과는 `results/results.csv`, `results/summary.md`, `results/annotated/`에 기록됩니다.

## 주요 옵션

- `--stage plate`: 프레임 전체에서 번호판을 탐지합니다.
- `--stage car+plate`: 차량을 먼저 찾고 번호판을 탐지합니다.
- `--conf 0.25`: 번호판 탐지 최소 신뢰도입니다.
- 실시간 투표는 `--window 10 --min-votes 3`으로 조정합니다.

실제 카메라 동작은 OS 카메라 권한과 하드웨어에 좌우됩니다. 모델의 정확도는 실제 번호판 및 지정 시험 조건에 맞춘 별도 데이터로 평가해야 합니다.
