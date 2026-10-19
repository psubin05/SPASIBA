# Hybrid Subin ALPR

Soogguang의 `plate_v3` 번호판 검출 흐름과 Subin의 PaddleOCR 인식 방식을 결합한 한국 자동차 번호판 인식 모듈입니다.

```text
이미지 / USB 웹캠 / Raspberry Pi Camera
  → plate_v3 (YOLO11n) 번호판 검출
  → 번호판 crop 및 작은 crop 확대
  → PP-OCRv5 mobile 글자 영역 검출
  → korean_PP-OCRv5 mobile 문자 인식
  → 한국 번호판 형식 검사
  → 번호판 트랙별 시간 투표
```

기존 `ocr_v1`을 삭제하거나 덮어쓰지 않습니다. PaddleOCR fine-tuning은 수행하지 않으며 공식 사전학습 모델을 첫 실행 때 자동으로 다운로드합니다.

## 폴더 구조

```text
hybrid_subin/
├── src/                  # 이미지, USB 웹캠, Pi Camera 실행 코드
├── models/detector/      # plate_v3.pt
├── tests/                # 후처리·추적·NMS 단위 테스트
├── docs/                 # 작업 기록
├── requirements.txt      # Ubuntu/PC
├── requirements_pi.txt   # Raspberry Pi 참고 의존성
├── run_webcam.sh
└── run_pi_camera.sh
```

## Ubuntu/PC 준비

저장소 루트에서:

```bash
cd hybrid_subin
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch torchvision
python -m pip install paddlepaddle
python -m pip install -r requirements.txt
```

GPU용 PyTorch/PaddlePaddle을 사용한다면 각 프로젝트 공식 설치 방법에 맞는 빌드를 먼저 설치하세요. 기존 CUDA 환경을 일반 `pip install`로 덮어쓰지 않는 것을 권장합니다.

## 이미지 실행

```bash
source .venv/bin/activate
python src/main.py --image /path/to/car.jpg --output outputs/image
```

그림자·빛번짐 전처리 후보를 비교하려면 `--robust`를 추가합니다. CPU에서는 매우 느려질 수 있습니다.

## USB 웹캠 실행

```bash
bash run_webcam.sh --camera 0 --det-size 960 --process-every 3 --min-votes 2
```

먼 번호판은 타일 검출을 선택할 수 있습니다.

```bash
bash run_webcam.sh --camera 0 --det-size 640 --tile-detect --process-every 10
```

- `q`/`ESC`: 종료
- `s`: 결과 프레임 저장

## Raspberry Pi Camera 실행

64비트 Raspberry Pi OS에서 카메라를 먼저 확인합니다.

```bash
rpicam-hello --list-cameras
rpicam-hello -t 3000
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv
```

Picamera2 시스템 패키지를 사용할 수 있게 환경을 만듭니다.

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch torchvision paddlepaddle
python -m pip install -r requirements_pi.txt
```

SSH/headless 실행:

```bash
bash run_pi_camera.sh --width 1920 --height 1080 --fps 15 \
  --det-size 640 --process-every 10 --min-votes 2
```

Raspberry Pi 데스크톱에서 화면을 띄우려면 `--display`를 추가합니다. SSH/headless에서는 `Ctrl+C`로 종료합니다.

> Pi 4B에서는 PaddleOCR와 PyTorch YOLO가 무거워 실시간 FPS가 나오지 않을 수 있습니다. 기능 확인 후 ONNX/NCNN 경량화나 서버 추론 구조와 비교해야 합니다.

## 테스트

```bash
source .venv/bin/activate
PYTHONPATH=src python -m unittest -v tests/test_core.py
python -m py_compile src/*.py
sha256sum -c MODEL_SHA256SUMS.txt
```

## 현재 한계

- 범용 사전학습 PaddleOCR이므로 실제 주차장 거리·기울기·반사광에 맞춰 fine-tuning된 모델은 아닙니다.
- 낮은 해상도에서 사라진 글자 획은 이미지 확대만으로 복원되지 않습니다.
- `--robust`와 `--tile-detect`는 CPU 처리 시간을 크게 증가시킵니다.
- AI Hub 및 Roboflow 원본 데이터는 이 폴더에 포함하지 않습니다.
