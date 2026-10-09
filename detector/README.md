# SPASIBA Korean Plate OCR

한국 번호판을 웹캠에서 검출하고, 한 줄/두 줄을 나눈 뒤 CTC OCR로 읽는 실행·학습 묶음입니다.

이 저장 폴더에는 다음이 포함됩니다.

- 웹캠 실시간 추론 코드
- 번호판 검출 가중치 `lp_det.pt`
- 최종 OCR PyTorch 체크포인트와 fp32 ONNX
- OCR 데이터 생성·학습·평가·내보내기 코드
- YOLO 검출 데이터 생성·혼합·평가 코드
- 로컬 실행에 필요한 YOLOv5 소스
- 실제 실험 지표와 전체 작업 기록

AI Hub 원본 이미지, 번호판 crop, 라벨 ZIP은 개인정보와 이용조건 때문에 포함하지 않습니다.

## 폴더 구조

```text
detector/
├── src/                     # 실행·학습·평가 코드
├── models/
│   ├── detector/
│   │   └── lp_det.pt        # 현재 웹캠용 선명 번호판 검출기
│   ├── ocr/
│   │   ├── plate_ctc_v3_strong.pt
│   │   ├── plate_ctc_fp32.onnx
│   │   ├── model_metadata.json
│   │   └── export_report.json
│   └── training/
│       └── plate_blur_v1.pt # sharp 혼합 검출 학습 시작점
├── reports/                 # 검증·테스트 결과
├── third_party/yolov5/      # 로컬 YOLOv5 로더, AGPL-3.0
├── requirements.txt
└── PLATE_DETECTOR_WORKLOG.md
```

## 설치

Python 3.10~3.12 환경을 권장합니다.

```bash
cd detector
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

CUDA 12.8 GPU를 사용하는 현재 개발 환경과 동일하게 설치하려면:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

CPU 환경이면 PyTorch 공식 설치 안내에 맞는 CPU wheel을 설치한 뒤 `requirements.txt`를 설치합니다.

EasyOCR이 `opencv-python-headless`를 같이 설치해 웹캠 창이 열리지 않는 경우 다음처럼 GUI판 하나만 남깁니다.

```bash
pip uninstall -y opencv-python-headless
pip install --force-reinstall --no-deps opencv-python
```

설치와 모델 파일 확인:

```bash
sha256sum -c MODEL_SHA256SUMS.txt
python verify_bundle.py
```

검출기까지 실제로 로드하는 전체 확인:

```bash
python verify_bundle.py --full
```

## 웹캠 실행

기본 실행은 GPU가 있으면 GPU 검출, OCR은 ONNX Runtime CPU를 사용합니다.

```bash
python src/webcam_plate_demo.py --camera 0
```

키:

- `q` 또는 `ESC`: 종료
- `s`: 현재 화면 저장
- `r`: 최근 프레임 OCR 투표 초기화

CRAFT 줄 확인이 느리면 비율 방식으로 실행합니다.

```bash
python src/webcam_plate_demo.py --camera 0 --line-mode ratio
```

GPU가 없으면:

```bash
python src/webcam_plate_demo.py --camera 0 --device cpu --line-mode ratio
```

창 없이 카메라 추론 경로만 확인:

```bash
python src/webcam_plate_demo.py \
  --camera 0 --headless --max-frames 10 --line-mode ratio
```

## OCR 추가 학습

이미 만들어진 `ocr_ctc` 데이터셋이 있다면 최종 모델에서 이어 학습할 수 있습니다.

```bash
python src/train_ctc_ocr.py \
  --data /path/to/ocr_ctc \
  --output outputs/plate_ctc_custom \
  --epochs 10 --batch 128 --workers 4 --device cuda \
  --augment strong --lr 1e-4 \
  --init models/ocr/plate_ctc_v3_strong.pt
```

데이터 디렉터리에는 `train.tsv`, `val.tsv`, `test.tsv`와 각 TSV가 가리키는 `images/`가 있어야 합니다. 같은 번호판 ID가 split 사이에 섞이지 않아야 합니다.

AI Hub OCR 원본부터 데이터셋을 다시 만들려면:

```bash
python src/build_ocr_dataset.py \
  --images /path/to/plate_ocr_images \
  --labels-zip /path/to/자동차번호판OCR_training.zip \
  --detector models/detector/lp_det.pt \
  --detector-backend yolov5 \
  --yolov5-repo third_party/yolov5 \
  --line-detector craft --min-line-overlap 0.65 \
  --output data/ocr_ctc --max-per-plate 5 --batch 32
```

## 번호판 검출기 추가 학습

`models/training/plate_blur_v1.pt`는 블러 원본으로 학습한 시작점입니다. 선명 번호판 회전 박스 2,000장을 사람이 검수한 뒤 축 정렬 YOLO 형식으로 변환하고, 블러 데이터와 혼합해서 학습해야 합니다.

```bash
python src/make_mix_dataset.py \
  --blur /path/to/yolo_blur \
  --sharp /path/to/yolo_sharp \
  --output data/yolo_mix --sharp-repeat 5

yolo detect train \
  model=models/training/plate_blur_v1.pt \
  data=data/yolo_mix/data.yaml \
  imgsz=640 batch=16 epochs=20 device=0 workers=4 \
  project=outputs name=plate_mix_v1 \
  degrees=10 perspective=0.0005 shear=5 scale=0.5 hsv_v=0.5 fliplr=0.0
```

현재 `lp_det.pt`는 웹캠 데모용 teacher이고 `plate_blur_v1.pt`는 추가 학습 시작점입니다. 최종 sharp 혼합 검출 모델이 만들어지면 웹캠의 `--detector` 인자로 지정해야 합니다.

## 현재 모델 성능

최종 `plate_ctc_v3_strong`의 teacher-cropped AI Hub 독립 test 결과:

| 조건 | 번호판 전체 일치율 | 두 줄 일치율 |
| --- | ---: | ---: |
| clean | 85.83% | 86.99% |
| 강한 합성 기울기·원근·흐림 | 60.98% | 67.35% |

이는 카메라 프레임부터의 end-to-end 성능이 아닙니다. 실제 시스템 평가는 sharp YOLO 파인튜닝과 데모 카메라 번호 단위 평가셋이 추가로 필요합니다.

## Git 및 데이터 주의사항

- `models/`의 `.pt`, `.onnx`는 Git LFS 사용을 권장합니다.
- AI Hub 원본, 번호판 이미지, OCR crop과 라벨 ZIP은 커밋하지 않습니다.
- `third_party/yolov5`는 AGPL-3.0 라이선스이며 원문은 해당 폴더의 `LICENSE`에 있습니다.
- `lp_det.pt`의 외부 공개 범위는 SPASIBA 프로젝트 정책을 확인한 뒤 결정합니다.
- 상세 실험 과정은 `PLATE_DETECTOR_WORKLOG.md`를 확인합니다.
