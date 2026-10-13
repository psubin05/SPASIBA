# 번호판 검출기

## A-0 / A-1 기준 모델 완료 (2026-10-07)

- GPU 서버에서 PyTorch 2.14.1+cu130, Ultralytics 8.4.174, RTX 4090 사용을 확인했습니다.
- AI Hub 블러 원본에서 만든 차량 crop 데이터 31,416장 학습 / 3,451장 검증으로 YOLO11n을 640px, batch 64, 30 epoch 학습했습니다.
- 최고 가중치 `detector/runs/plate_blur_a1/weights/best.pt`의 **블러 검증**: P 0.997 / R 0.997 / mAP50 0.994 / mAP50-95 0.649.
- 팀원 기록은 P 0.997 / R 0.998 / mAP50 0.994 / mAP50-95 0.654입니다. 데이터 분할 건수가 달라 완전한 동등 비교는 아닙니다. 블러 검증 수치로 선명한 번호판 성능을 판단할 수 없습니다.

```bash
.venv/bin/yolo detect train model=detector/yolo11n.pt \
  data=data/yolo_plate/dataset.yaml imgsz=640 batch=64 epochs=30 device=0 workers=8 \
  project=$PWD/detector/runs name=plate_blur_a1 \
  degrees=10 perspective=0.0005 shear=5 scale=0.5 hsv_v=0.5 fliplr=0.0
```

## 번호판 검출 데이터 준비 (공유 PDF의 A 단계)

아래 명령은 저장소 루트에서 실행합니다. AI Hub 원본 프레임 ZIP과 `라벨링데이터.zip`을 준비합니다. 원본 프레임 ZIP의 압축 종료 정보와 모든 이미지 CRC가 정상이어야 하며, 스크립트도 실행 전에 이를 검사합니다. 결과는 Git에서 제외된 `data/` 아래에 저장합니다.

원본 이미지 filekey 48980을 다시 받아야 한다면, 서버에서 AI Hub API 키를 `data/.aihub_api_key`에 0600 권한으로 저장한 뒤 `python3 detector/redownload_original.py`를 실행합니다. 이 스크립트는 TAR을 이어받고 ZIP을 조립·검증한 다음 기존 손상 파일을 교체합니다. 검증이 끝나기 전에는 기존 ZIP을 건드리지 않고, 교체 후 손상 ZIP과 중간 TAR을 삭제합니다.

```bash
.venv/bin/python detector/prepare_detector_data.py \
  --labels 'data/103.자동차_차종-연식-번호판_인식용_데이터/추가_데이터_보완_건_220114(원본이미지추가개방)/원본이미지(추가개방)/라벨링데이터/라벨링데이터.zip' \
  --images 'data/103.자동차_차종-연식-번호판_인식용_데이터/추가_데이터_보완_건_220114(원본이미지추가개방)/원본이미지(추가개방)/원천데이터/원천데이터11.zip' \
  --output data/detector_yolo11
```

스크립트는 라벨이 지정한 차량 주변만 잘라 번호판 박스를 YOLO 좌표로 바꿉니다. 너비 20픽셀 미만 번호판은 제외하고, 같은 영상의 연속 프레임이 학습과 검증에 섞이지 않도록 영상별로 나눕니다. `dataset.yaml`과 건수 요약도 생성합니다. `--limit 20`을 붙여 먼저 소량으로 시험할 수 있습니다. 검출기 학습과 평가는 원본 ZIP을 검증한 후 진행합니다.


## 다른 학습 경로: 선명한 번호판부터 학습

블러 원본만 학습한 모델은 선명한 번호판 48장 시험에서 거의 검출하지 못했습니다. 이 경로는 **OCR crop용 모델**을 먼저 만들고, 선명한 번호판을 차량 crop에 합성해 **카메라용 모델**을 따로 학습합니다. 블러 모델의 가중치에서 시작하지 않습니다.

1. `weak_label.py`가 OCR 학습 ZIP의 글자 위치를 PaddleOCR로 찾습니다. 인식 문자열이 AI Hub 정답 번호와 완전히 같은 이미지만 남기고, 글자 박스를 번호판 테두리 쪽으로 확장합니다. 생성 박스는 **약한 라벨**이므로 `audit.jpg`와 샘플 원본을 검수해야 합니다. 번호 문자열의 SHA-256 해시로 90:10을 나눕니다.
2. 생성된 `dataset.yaml`로 YOLO11n을 학습합니다. `evaluate_sharp.py`를 기존 블러 모델과 새 모델에 같은 검증 이미지, 같은 `--conf`로 적용해 비교합니다. 이 도구의 `any_box_rate`는 오검출도 포함하므로 재현율이라고 부르지 않습니다.
3. `make_synth.py`가 선명한 번호판 영역을 블러 차량 번호판 자리에 붙입니다. 합성 val은 방법 점검용이며 실제 카메라 성능을 뜻하지 않습니다. 차량 촬영 사진의 수작업 박스 평가가 최종 기준입니다.

```bash
# OCR 학습 ZIP 경로는 이 저장소의 data/ 아래 실제 경로로 지정
.venv/bin/python detector/weak_label.py --images "$OCR_TRAIN_IMAGES" \
  --labels "$OCR_TRAIN_LABELS" --output data/ocr_teacher --materialize

.venv/bin/yolo detect train model=detector/yolo11n.pt \
  data=data/ocr_teacher/dataset.yaml imgsz=640 epochs=30 batch=16 device=0 \
  fliplr=0 project=$PWD/detector/runs name=sharp_first

.venv/bin/python detector/make_synth.py --sharp data/ocr_teacher \
  --vehicle data/yolo_plate --output data/plate_synth

.venv/bin/yolo detect train model=detector/runs/sharp_first/weights/best.pt \
  data=data/plate_synth/dataset.yaml imgsz=640 epochs=30 batch=16 device=0 \
  fliplr=0 project=$PWD/detector/runs name=camera_synth

.venv/bin/python detector/evaluate_sharp.py --model detector/runs/sharp_first/weights/best.pt \
  --images "$OCR_VAL_IMAGES" --labels "$OCR_VAL_LABELS" \
  --output data/sharp_first_eval --limit 48

# YOLO-World의 공개 가중치가 로컬에 있거나 내려받을 수 있을 때
.venv/bin/python detector/evaluate_sharp.py --world --model yolo-worldv2s.pt \
  --images "$OCR_VAL_IMAGES" --labels "$OCR_VAL_LABELS" \
  --output data/world_eval --limit 48
```

AI Hub 선명한 번호판 이미지는 개인 정보입니다. `data/`와 가중치는 Git에서 제외하고 외부 라벨링 서비스에 업로드하지 않습니다. 공개 자료에 넣는 평가 이미지는 번호를 가려야 합니다.

### 2026-10-07 로컬 실험

| 모델/시험 | 결과 | 해석 |
| --- | --- | --- |
| OCR 글자 위치 기반 약한 라벨 | 1,200장 검사, 595장 채택 (학습 519 / 검증 76) | 박스는 사람이 전수 검수한 정답이 아님 |
| `sharp_first_1200`, OCR validation 48장 | 48/48에서 박스; 48장 미리보기에서 번호판 위치 확인 | 학습에 나온 번호 값은 제외. 기존 팀원의 블러 모델 0/48과 사진 목록은 다를 수 있음 |
| `sharp_first_1200`, OCR validation 300장 | 299/300에서 박스 (`conf=0.25`, `imgsz=640`) | 박스 정답이 없어 진짜 재현율·mAP은 측정 불가 |
| `sharp_first_1200`, 합성 차량 val 436장 | R 0.0046, mAP50 약 0 | OCR crop용 모델은 차량 장면에서 거의 작동하지 않음 |
| `camera_synth_1200`, 합성 차량 val 436장 | P 1.000 / R 1.000 / mAP50 0.995 / mAP50-95 0.823 | 같은 생성 방식의 합성 검증이므로 실제 카메라 점수는 아님 |
| `camera_synth_1200`, OCR validation 48장 | 1/48에서 박스 | 차량용 모델을 OCR crop 정리에 재사용하지 않음 |

실험 가중치는 Git에서 제외된 `runs/detect/detector/runs/sharp_first_1200/weights/best.pt`와 `detector/runs/camera_synth_1200/weights/best.pt`에 있습니다. 첫 경로에 `runs/detect/`가 추가된 것은 첫 학습 때 상대 `project` 경로를 사용했기 때문입니다. 위 명령은 절대 `project` 경로를 써서 중복을 피합니다.

실제 카메라 이미지에서 ①단계 crop을 만들려면 다음처럼 실행합니다. `--vehicle-model`은 작은 번호판을 위해 차량을 먼저 찾고 차량 crop 안에서 한 번 더 번호판을 찾습니다.

```bash
.venv/bin/python detector/detect.py --image 입력.jpg \
  --plate-model detector/runs/camera_synth_1200/weights/best.pt \
  --vehicle-model detector/yolo11n.pt --output data/detected --device 0
```

실제 앞·뒤 차량 사진과 수작업 번호판 박스로 별도 평가하기 전에는 카메라 재현율 95% 목표 달성을 주장하지 않습니다.

## Roboflow 공개 번호판 데이터로 검출기 개선 (2026-10-13)

출처: [korea car plat v1](https://universe.roboflow.com/korean-car-plat/korea-car-plat/dataset/1), CC BY 4.0. ZIP을 YOLOv11 형식으로 내려받아 `data/roboflow_korea_car_plat/`에 압축 해제했습니다. 학습 700장, 검증 200장, 시험 100장이고 클래스 `plat` 하나에 번호판 박스가 붙어 있습니다. 라벨 1,007개를 확인했으며 누락·잘못된 좌표는 없었습니다. 공개 데이터의 번호판 박스는 중앙값으로 이미지 너비의 75.6%, 높이의 50.6%를 차지합니다. 기존 합성 차량 데이터에서는 각각 약 19.8%, 3.9%여서 두 크기를 함께 학습했습니다.

`prepare_roboflow_mix.py`는 공개 데이터 학습 700장을 세 번, 기존 합성 차량 학습 4,440장을 한 번 연결합니다. 검증은 공개 데이터 200장과 합성 차량 436장을 연결하고, 공개 시험 100장은 학습과 모델 선택에서 제외합니다. 이미지 복사 대신 `data/` 아래 심볼릭 링크를 만듭니다. 원본 위치를 바꾸면 혼합 데이터를 다시 생성해야 합니다.

```bash
.venv/bin/python detector/prepare_roboflow_mix.py
.venv/bin/yolo detect train model=detector/yolo11n.pt \
  data=data/plate_mixed_rf_v1/dataset.yaml imgsz=640 batch=64 epochs=25 device=0 workers=8 \
  project=$PWD/detector/runs name=plate_mixed_rf_v1 \
  degrees=5 perspective=0.0005 shear=2 scale=0.4 hsv_v=0.2 fliplr=0 \
  mosaic=0.5 close_mosaic=8 patience=8 seed=42 plots=False cache=ram
.venv/bin/yolo detect train model=detector/runs/camera_synth_1200/weights/best.pt \
  data=data/plate_mixed_rf_v1/dataset.yaml imgsz=640 batch=64 epochs=18 device=0 workers=8 \
  project=$PWD/detector/runs name=plate_mixed_rf_finetune \
  degrees=5 perspective=0.0005 shear=2 scale=0.3 hsv_v=0.2 fliplr=0 \
  mosaic=0.3 close_mosaic=6 patience=7 seed=42 plots=False cache=ram \
  optimizer=AdamW lr0=0.0005 lrf=0.1 warmup_epochs=1
```

Ultralytics 8.4.174, PyTorch 2.14.1+cu130, RTX 4090에서 학습했습니다. `best.pt`는 `detector/runs/plate_mixed_rf_finetune/weights/`에 있습니다.

| 모델 | 공개 검증 mAP50 / mAP50-95 | 합성 차량 검증 mAP50 / mAP50-95 | 흐린 차량 검증 mAP50 / mAP50-95 |
| --- | --- | --- | --- |
| 기존 `camera_synth_1200` | 0 / 0 | 0.995 / 0.827 | 0.806 / 0.378 |
| 새 `plate_mixed_rf_v1` | 0.995 / 0.912 | 0.995 / 0.810 | 측정 안 함 |
| **선택: `plate_mixed_rf_finetune`** | **0.995 / 0.893** | **0.995 / 0.845** | **0.869 / 0.422** |

선택한 모델을 별도 공개 시험셋 100장(번호판 102개)에 한 번 평가한 결과: P 0.988 / R 0.980 / mAP50 0.985 / mAP50-95 0.897. 재평가는 다음처럼 합니다.

```bash
.venv/bin/python detector/evaluate_domains.py \
  --model detector/runs/plate_mixed_rf_finetune/weights/best.pt \
  --test --output data/plate_mixed_rf_v1/final_evaluation.json
.venv/bin/python detector/detect.py --image 입력.jpg \
  --plate-model detector/runs/plate_mixed_rf_finetune/weights/best.pt \
  --vehicle-model detector/yolo11n.pt --output data/detected --device 0
```

공개 데이터는 번호판 근접 사진이고 합성 차량 검증셋은 같은 방식으로 만든 이미지입니다. 흐린 차량 검증셋은 합성 검증셋과 원본 차량 이미지를 공유하므로 서로 독립된 시험이 아닙니다. 어느 점수도 실제 카메라 촬영 영상의 검출 성능을 대신하지 않습니다. 실제 앞·뒤 차량 사진에 수작업 번호판 박스를 표시해 별도로 평가해야 합니다. 공개 이미지는 번호판 식별 정보가 있으므로 원본과 가중치는 Git에서 제외된 `data/`, `detector/runs/`에만 둡니다.
