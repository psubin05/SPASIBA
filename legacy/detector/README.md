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
SPASIBA_plate_ocr/
├── src/                     # 실행·학습·평가 코드
├── models/
│   ├── detector/
│   │   ├── plate_yolo11n_balanced_webcam_v1.pt # 기본 YOLO11n 검출기
│   │   ├── plate_yolo11n_balanced_v1.pt        # 웹캠 적응 전 균형 모델
│   │   └── lp_det.pt                              # 기존 YOLOv5 호환 모델
│   ├── ocr/
│   │   ├── plate_ctc_v3_strong.pt
│   │   ├── plate_ctc_fp32.onnx
│   │   ├── model_metadata.json
│   │   └── export_report.json
│   ├── ocr_webcam_v1/       # 기본 웹캠 OCR(Pytorch/fp32/int8 ONNX)
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
bash run_webcam.sh --camera 0
```

키:

- `q` 또는 `ESC`: 종료
- `s`: 현재 화면 저장
- `r`: 최근 프레임 OCR 투표 초기화

CRAFT 줄 확인이 느리면 비율 방식으로 실행합니다.

```bash
bash run_webcam.sh --camera 0 --line-mode ratio
```

GPU가 없으면:

```bash
bash run_webcam.sh --camera 0 --device cpu --line-mode ratio
```

창 없이 카메라 추론 경로만 확인:

```bash
bash run_webcam.sh \
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
  --init models/ocr_webcam_v1/plate_ctc_webcam_v1.pt
```

데이터 디렉터리에는 `train.tsv`, `val.tsv`, `test.tsv`와 각 TSV가 가리키는 `images/`가 있어야 합니다. 같은 번호판 ID가 split 사이에 섞이지 않아야 합니다.

AI Hub OCR 원본부터 데이터셋을 다시 만들려면:

```bash
python src/build_ocr_dataset.py \
  --images /path/to/plate_ocr_images \
  --labels-zip /path/to/자동차번호판OCR_training.zip \
  --detector models/detector/plate_yolo11n_balanced_webcam_v1.pt \
  --detector-backend yolo11 \
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

기본 웹캠 모델은 `plate_yolo11n_balanced_webcam_v1.pt`입니다. 기존 `lp_det.pt`는 비교와 하위 호환을 위해 보존했습니다.

### Roboflow ZIP으로 현재 검출기 재학습

두 Roboflow ZIP을 각각 푼 디렉터리와 기존 블러 YOLO 데이터셋을 지정합니다. 스크립트는 polygon을 bbox로 바꾸고 Roboflow 증강 원본 단위로 분할해 leakage를 막으며, 선명·블러 1:1 목록도 만듭니다.

```bash
python src/prepare_roboflow_detect_dataset.py \
  --sources /path/to/korea_carplate_v3 /path/to/korean_license_plate_v2 \
  --output data/roboflow_plate_detect \
  --base /path/to/yolo_blur --external-repeat 2 \
  --balanced-base-ratio 1.0 --seed 42

yolo detect train \
  model=models/detector/plate_yolo11n_balanced_v1.pt \
  data=data/roboflow_plate_detect/balanced.yaml \
  imgsz=640 batch=32 epochs=12 device=0 workers=4 \
  project=outputs name=plate_balanced_custom \
  degrees=15 perspective=0.0005 shear=5 scale=0.4 hsv_v=0.45 fliplr=0.0
```

웹캠 수집 폴더에 `frame_raw.jpg`, `metadata.json`과 정답 `expected_plate`가 있으면 다음 스크립트로 검출 및 OCR 적응 데이터를 재생성할 수 있습니다.

```bash
python src/prepare_webcam_pseudo_dataset.py \
  --captures /path/to/webcam_captures \
  --output data/webcam_pseudo \
  --balanced-root data/roboflow_plate_detect

python src/prepare_webcam_ocr_adaptation.py \
  --webcam-detect data/webcam_pseudo \
  --captures /path/to/webcam_captures \
  --base-ocr /path/to/ocr_ctc_v2 \
  --output data/ocr_ctc_webcam_adapt --webcam-repeat 20
```

## 현재 모델 성능

현재 기본 모델의 검증 결과:

| 항목 | 정밀도/정확도 | 재현율 | mAP50 |
| --- | ---: | ---: | ---: |
| YOLO11 선명 독립 test 348장 | 99.4% | 99.1% | 99.4% |
| YOLO11 기존 블러 val 3,364장 | 98.8% | 98.4% | 99.1% |
| YOLO11 웹캠 시간분리 val 36장 | 99.8% | 100% | 99.5% |
| OCR AI Hub val 6,058대 | 전체 일치 87.60% | - | - |
| OCR 웹캠 시간분리 val 36장 | 전체 일치 83.33% | - | - |
| OCR 웹캠 두 줄 33장 | 전체 일치 87.88% | - | - |

웹캠 검증은 같은 세 번호판의 시간상 후반 프레임이므로 새 번호판 일반화 지표는 아닙니다. 대표 세 프레임에서는 검출→줄 분리→OCR 전체 문자열이 모두 정확했으며, 새 번호판을 번호 단위로 분리한 추가 평가는 여전히 필요합니다.

## Git 및 데이터 주의사항

- `models/`의 `.pt`, `.onnx`는 Git LFS 사용을 권장합니다.
- AI Hub 원본, 번호판 이미지, OCR crop과 라벨 ZIP은 커밋하지 않습니다.
- `third_party/yolov5`는 AGPL-3.0 라이선스이며 원문은 해당 폴더의 `LICENSE`에 있습니다.
- `lp_det.pt`의 외부 공개 범위는 SPASIBA 프로젝트 정책을 확인한 뒤 결정합니다.
- 상세 실험 과정은 `PLATE_DETECTOR_WORKLOG.md`를 확인합니다.
