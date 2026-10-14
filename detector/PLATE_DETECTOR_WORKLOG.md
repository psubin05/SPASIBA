# YOLO11n 한국 번호판 검출기 작업 기록

마지막 갱신: 2026-10-08 (Asia/Seoul)

## 목표와 완료 기준

선명한 한국 번호판(전·후면, 한 줄·두 줄)을 찾는 YOLO11n 검출기를 만든다. 라벨러와 분리한 선명 평가 세트 300장에서 **재현율 95% 이상**을 완료 기준으로 삼는다. 최종 모델은 카메라 번호판 위치 검출과 OCR crop 9만 장의 박스 생성에 사용한다.

## 실제 환경 점검 결과

| 항목 | 확인 결과 | 반영 사항 |
|---|---|---|
| GPU | NVIDIA GeForce RTX 3070 Ti Laptop, VRAM 8GB | 계획의 RTX 4090과 다르므로 `batch=16`부터 시작하고 OOM이면 8로 낮춘다 |
| Python | 3.12.3 | 새 가상환경을 `plate_detector/.venv`에 구성 완료 |
| 기존 가상환경 | PyTorch 2.14.0 CPU 빌드, Ultralytics 8.4.166 | GPU 학습용으로 재사용하지 않는다 |
| 학습 환경 | PyTorch 2.11.0+cu128, Ultralytics 8.4.174, CUDA 정상 | CUDA 텐서 연산과 YOLO 1 epoch smoke test 통과 |
| 선명 OCR 이미지 | Training 80,000장(풀림), Validation 10,000장(ZIP) | A-2는 풀린 Training 80,000장을 대상으로 완료 |
| OCR 번호 고유값 | 파일명 기준 약 36,830개 | 동일 번호는 라벨 JSON의 `value`를 우선 사용해 한 장만 선택한다 |
| 원본 프레임 | 34,980장, ZIP 약 16GB | ZIP에서 직접 읽어 차량 crop을 생성한다 |
| 원본 라벨 | JSON 500,000개, ZIP 약 347MB | 실제 원본 ZIP에 존재하는 프레임만 매칭한다 |
| 여유 디스크 | 약 212GB | 원본 ZIP은 보존하고 생성 데이터만 추가한다 |

주의: OCR 이미지는 번호판만 딱 잘린 이미지가 아니라 번호판 주변 차량 맥락도 들어 있는 crop이다. 이는 선명한 번호판 모양과 일부 주변 맥락을 함께 학습하는 데 유리하다.

## 구현한 파일

| 파일 | 역할 |
|---|---|
| `prepare_blur_dataset.py` | 16GB 원본 프레임 ZIP과 라벨 ZIP을 매칭하고 차량 crop + 번호판 YOLO 라벨 생성 |
| `sample_sharp.py` | 번호 중복 제거, 색상·종횡비 기반 2,000장 계층 샘플, 500장씩 4묶음 생성 |
| `convert_and_split_sharp.py` | X-AnyLabeling 회전 다각형 검증, 번호 단위 1,700/300 분할, 축 정렬 YOLO 박스로 변환 |
| `make_mix_dataset.py` | 블러 train + 선명 train 5회 반복 목록 및 선명 eval YAML 생성 |
| `evaluate_models.py` | A-1/A-6 모델의 precision, recall, mAP50, mAP50-95 비교 |
| `infer_all.py` | OCR 이미지 전체 추론 후 박스 CSV 생성 |

## 경로

```text
프로젝트: /home/misys/cloudAIoT/plate_detector
AI Hub:   /home/misys/cloudAIoT/CAR_dataset/103.자동차_차종-연식-번호판_인식용_데이터
OCR 8만:  /home/misys/cloudAIoT/CAR_dataset/plate_ocr_train
생성물:   /home/misys/cloudAIoT/CAR_dataset/plate_detection_work
```

## A-0. GPU 학습 환경

일반 시스템은 다음 명령을 사용한다.

```bash
cd /home/misys/cloudAIoT/plate_detector
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

이 서버는 `ensurepip`가 없어 `python3 -m venv`가 pip 없이 부분 생성됐다. 기존 가상환경의 최신 pip가 지원하는 `--python` 옵션으로 아래처럼 부트스트랩했다.

```bash
EasyKoreanLpDetector/.venv/bin/python -m pip --python plate_detector/.venv install pip
plate_detector/.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
plate_detector/.venv/bin/pip install -r plate_detector/requirements.txt
```

검증 결과는 `torch 2.11.0+cu128`, `cuda True`, `NVIDIA GeForce RTX 3070 Ti Laptop GPU`였고 실제 CUDA 텐서 합 연산도 통과했다. 가상환경 크기는 약 7.2GB다.

## A-1. 블러 기준 데이터셋과 모델

```bash
cd /home/misys/cloudAIoT/plate_detector
source .venv/bin/activate

python prepare_blur_dataset.py \
  --images-zip '/home/misys/cloudAIoT/CAR_dataset/103.자동차_차종-연식-번호판_인식용_데이터/추가_데이터_보완_건_220114(원본이미지추가개방)/원본이미지(추가개방)/원천데이터/원천데이터11.zip' \
  --labels-zip '/home/misys/cloudAIoT/CAR_dataset/103.자동차_차종-연식-번호판_인식용_데이터/추가_데이터_보완_건_220114(원본이미지추가개방)/원본이미지(추가개방)/라벨링데이터/라벨링데이터.zip' \
  --output /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/yolo_blur

yolo detect train model=yolo11n.pt \
  data=/home/misys/cloudAIoT/CAR_dataset/plate_detection_work/yolo_blur/data.yaml \
  imgsz=640 batch=32 epochs=30 device=0 workers=4 cache=False amp=True \
  project=/home/misys/cloudAIoT/plate_detector/runs name=plate_blur_v1 \
  degrees=10 perspective=0.0005 shear=5 scale=0.5 hsv_v=0.5 fliplr=0.0
```

1% 데이터 1 epoch smoke test에서 `batch=16`은 GPU 메모리 약 2.26GB를 사용했다. 본 학습의 `batch=32`는 약 4.17GB로 안정적으로 시작됐다. VRAM OOM이면 `batch=16`으로 재실행한다. 8GB GPU에서는 원래 계획의 `batch=64`를 사용하지 않는다.

실제 생성 결과는 train 31,615장, val 3,364장, 제외 1장이다. 분할은 단순 이미지 무작위가 아니라 비디오 단위 해시 분할이라 인접 프레임 누수를 막는다. 제외된 `자유시장앞_고정1-20200907-065957-010_2800.jpg`는 원본 번호판 박스가 차량 crop과 겹치지 않는 라벨 오류였다. 나머지는 이미지/라벨 1:1, train/val 파일 중복 0, YOLO 좌표 범위 정상이다.

## A-2. 선명 2,000장 추출

```bash
python sample_sharp.py \
  --images /home/misys/cloudAIoT/CAR_dataset/plate_ocr_train \
  --labels-zip '/home/misys/cloudAIoT/CAR_dataset/103.자동차_차종-연식-번호판_인식용_데이터/추가_데이터_보완_건_211229(폴더구조수정)/1.Training/라벨링데이터/자동차번호판OCR_training.zip' \
  --output /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/sharp_sample
```

파일은 기본적으로 복사하지 않고 hard link로 만들어 디스크를 아낀다. `selection.csv`에 원본, 번호 ID, 자동 분류, 종횡비가 기록된다. 자동 색상 분류는 휴리스틱이므로 `summary.json`과 각 묶음을 사람이 빠르게 훑어 유형을 교정해야 한다. 특히 파란 전기차 번호판과 조명색이 강한 이미지는 오분류 가능성이 있다.

실제 생성 결과는 2,000장, 번호 ID 2,000개(중복 0), 파일 2,000개이며 bundle 1~4가 각각 정확히 500장이다. 자동 후보군 수량은 흰색 긴 형 1,000, 노란 긴 형 400, 노란 두 줄 300, 초록 두 줄·기타 300이다. 육안 표본에서 차량 배경 때문에 흰색 긴 번호판이 기타 후보로 들어간 경우가 확인됐으므로, 이 구분값은 확정 라벨이 아니라 라벨링 전 교정용 후보값이다.

## A-3/A-4. 초안과 수동 라벨링

기준 모델로 각 bundle에 초안을 만든다. Ultralytics가 만드는 YOLO 사각 박스는 X-AnyLabeling에서 불러온 후 **회전 박스/다각형으로 사람이 번호판 외곽에 맞춰 교정**한다. 초안보다 정확한 회전 꼭짓점 4개가 최종 기준이다.

라벨링 규칙:

- 클래스 이름은 정확히 `plate` 하나만 사용한다.
- 판 자체의 바깥 테두리만 감싸고 플라스틱 가이드는 제외한다.
- 두 줄 번호판도 하나의 회전 박스로 그린다.
- 절반 이상 보이면 보이는 영역까지, 절반 미만이면 빈 라벨로 둔다.
- 흐려도 번호판임을 알 수 있으면 라벨링한다.
- 여러 번호판이 있으면 모두 그린다.
- X-AnyLabeling의 LabelMe JSON 형식으로 저장한다.

초안 명령 예시:

```bash
yolo detect predict \
  model=/home/misys/cloudAIoT/plate_detector/runs/plate_blur_v1/weights/best.pt \
  source=/home/misys/cloudAIoT/CAR_dataset/plate_detection_work/sharp_sample/bundle_1/images \
  imgsz=640 conf=0.10 save_txt=True save_conf=True
```

`conf=0.10`은 라벨링 초안에서 놓침을 줄이기 위한 값이다. 오검출은 사람이 삭제한다.

## A-5. 라벨 검증과 1,700/300 분할

네 명의 JSON을 한 명의 라벨 디렉터리에 모으거나 경로를 여러 개 전달한다.

```bash
python convert_and_split_sharp.py \
  --selection /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/sharp_sample/selection.csv \
  --labels /path/to/person_a /path/to/person_b /path/to/person_c /path/to/person_d \
  --output /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/yolo_sharp \
  --eval-count 300
```

평가 300장은 다른 라벨러가 재검수한다. 스크립트는 번호 ID의 SHA-1 순서로 안정적으로 분할하므로 반복 실행해도 같은 평가 세트가 만들어진다. 회전 꼭짓점의 최소/최대 좌표로 축 정렬 YOLO 박스를 만든다. 원본 회전 JSON은 삭제하지 않으므로 향후 YOLO OBB 학습에 재사용할 수 있다.

## A-6. 혼합 파인튜닝

```bash
python make_mix_dataset.py \
  --blur /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/yolo_blur \
  --sharp /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/yolo_sharp \
  --output /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/yolo_mix \
  --sharp-repeat 5

yolo detect train \
  model=/home/misys/cloudAIoT/plate_detector/runs/plate_blur_v1/weights/best.pt \
  data=/home/misys/cloudAIoT/CAR_dataset/plate_detection_work/yolo_mix/data.yaml \
  imgsz=640 batch=16 epochs=20 device=0 workers=4 cache=False amp=True \
  project=/home/misys/cloudAIoT/plate_detector/runs name=plate_mix_v1 \
  degrees=10 perspective=0.0005 shear=5 scale=0.5 hsv_v=0.5 fliplr=0.0
```

## A-7. 동일 평가 세트 비교

```bash
python evaluate_models.py \
  --baseline runs/plate_blur_v1/weights/best.pt \
  --finetuned runs/plate_mix_v1/weights/best.pt \
  --data /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/yolo_sharp/data.yaml \
  --output runs/model_comparison.json
```

최우선 지표는 recall이며 목표는 0.95 이상이다. mAP50과 precision도 함께 보고, `selection.csv`의 `bucket`을 이용한 유형별 평가는 별도 집계한다. 전면/후면 정보는 원본 메타데이터에 없으므로 라벨링 시 `front`/`rear` 속성을 추가하지 않으면 자동 유형별 집계가 불가능하다. 발표에 앞뒤별 표가 반드시 필요하면 X-AnyLabeling 속성 또는 별도 CSV 열로 기록한다.

## A-8. OCR 전체 박스 CSV

```bash
python infer_all.py \
  --weights runs/plate_mix_v1/weights/best.pt \
  --source /home/misys/cloudAIoT/CAR_dataset/plate_ocr_train \
  --output /home/misys/cloudAIoT/CAR_dataset/plate_detection_work/ocr_boxes_train.csv \
  --batch 16 --conf 0.25
```

Validation 1만 장도 ZIP을 별도 디렉터리에 푼 뒤 같은 명령으로 실행한다. CSV에는 이미지명, 검출 순번, confidence, `x1,y1,x2,y2`가 들어가며 무검출 이미지는 `detection_index=-1`로 남아 누락을 추적할 수 있다.

## 품질 게이트

1. `prepare_blur_dataset.py`의 `manifest.json`에서 skipped와 train/val 수를 확인한다.
2. A-1 학습 전에 무작위 100장의 crop/박스를 시각 확인한다.
3. 2,000장 샘플의 중복 번호가 0인지 `selection.csv`로 확인한다.
4. 공통 20장으로 네 명의 라벨 기준을 맞춘다.
5. `convert_and_split_sharp.py`가 누락 JSON, 4점 미만 polygon, 범위 밖 박스를 실패 처리하게 둔다.
6. 평가 300장은 최초 라벨러와 다른 사람이 재검수한다.
7. recall 0.95 미만이면 누락 사례를 유형·크기·밝기·앞뒤로 분류한 뒤 데이터 보강 여부를 결정한다.

## 현재 상태

- 완료: 로컬 데이터 구조, ZIP 수량, GPU, Python, 기존 환경 점검
- 완료: A-0 CUDA 학습 환경 설치 및 CUDA/YOLO smoke test
- 완료: A-1 블러 데이터 34,979장 생성 및 전수 구조 검증
- 진행 중: A-1 `plate_blur_v1` 30 epoch 학습 (`batch=32`, 약 4.17GB VRAM)
- 완료: A-2 번호 중복 없는 선명 후보 2,000장과 500장씩 4묶음 생성
- 완료: A-5 변환/분할, A-6 혼합, A-7 비교, A-8 추론 스크립트 작성
- 대기: 사람이 수행할 회전 박스 라벨링·교차검수·평가 300장 재검수

학습은 epoch 1 체크포인트에서 정상 재개됐으며 메인 프로세스 PID는 시작 시점 기준 `51338`, GPU 사용량은 약 4.5GB였다. epoch 1의 블러 검증 결과는 precision 0.9868, recall 0.9822, mAP50 0.9868이다. 이 값은 **블러 검증 성능**일 뿐 최종 목표인 선명 평가 300장 성능이 아니다.

진행 확인:

```bash
pgrep -af 'yolo detect train resume'
nvidia-smi
tail -n 5 /home/misys/cloudAIoT/plate_detector/runs/plate_blur_v1/results.csv
```

---

# 2026-10-08 OCR 학습 및 기울기·두 줄 강건화 결과

> 이 절은 위의 오래된 `현재 상태`를 갱신하는 최신 실행 기록이다. 모든 수치는 실제 생성 파일과 체크포인트를 기준으로 기록했다.

## 최종 구성과 역할

현재 파이프라인은 다음처럼 역할을 분리한다.

1. 번호판 검출: YOLO가 차량 프레임에서 번호판을 찾는다.
2. 기울기 보정/줄 분리: 회전 박스 또는 번호판 사각형으로 정렬한 뒤 한 줄·두 줄을 나눈다.
3. 문자 인식: 48×192 입력의 경량 CNN + 2-layer BiGRU + CTC가 줄별 문자열과 timestep별 확률을 낸다.
4. 서버 매칭: CTC top-k 확률을 입차 버퍼 후보와 비교하고 여러 프레임을 누적한다.

이번에 학습한 인식기는 538,834 parameters, PyTorch 체크포인트 2.1MB이다. 지역명 17개는 Private Use Unicode 내부 토큰 한 개로 학습하고 출력 시 `서울`, `경기` 같은 원문으로 복원한다. CRAFT와 기존 `lp_det.pt`는 **오프라인 학습 데이터 제작용 teacher**이며 Pi 런타임 구성 요소가 아니다.

## 번호판 검출기 진행 결과

- 블러 원본 기반 YOLO 데이터: train 31,615장 / val 3,364장
- `YOLO11n plate_blur_v1` 30 epoch 완료
- 블러 val: precision 0.99509 / recall 0.99524 / mAP50 0.99395 / mAP50-95 0.61691
- 가중치: `runs/plate_blur_v1/weights/best.pt`
- 선명 OCR crop 200장 smoke test에서는 11장만 검출했다. 블러 데이터 점수가 높아도 선명 번호판 도메인에는 일반화되지 않는다는 것을 확인했다.
- 선명 번호판 2,000장, 고유 번호 2,000개, 500장씩 네 묶음은 생성 완료했다.
- 따라서 검출기의 다음 필수 단계는 사람이 2,000장 회전 박스를 교정한 뒤 블러+선명 혼합 파인튜닝하는 것이다. 수동 라벨 없이 blur 모델로 9만 장 전체를 자르는 것은 금지한다.

## OCR 데이터셋 제작

사용한 teacher:

- 번호판 crop: `EasyKoreanLpDetector/lp_det.pt` (기존 YOLOv5)
- 저비율 crop 줄 구조 검증: EasyOCR CRAFT
- 번호별 최대 5장
- 번호 문자열 SHA-1 기준 80/10/10 group split
- 같은 번호가 train/val/test에 동시에 들어가지 않음

최종 데이터 위치:

`/home/misys/cloudAIoT/CAR_dataset/plate_detection_work/ocr_ctc_v2`

최종 생성 통계:

| 항목 | 수량 |
| --- | ---: |
| 선택 원본 | 62,753 |
| long 번호판 | 46,228 |
| long_vregion 번호판 | 9,731 |
| tall 번호판 | 3,712 |
| train 줄 crop | 50,457 |
| val 줄 crop | 6,488 |
| test 줄 crop | 6,438 |
| 무검출 | 2,771 |
| 애매 비율 제외 | 196 |
| CRAFT text 없음 | 108 |
| 너무 작은 검출 제외 | 7 |

번호 ID 수는 train 27,804 / val 3,520 / test 3,532이고 세 split의 교집합은 모두 0이다. train 문자 집합은 65개이며 val/test에만 존재하는 미등록 문자는 0개다.

### 두 줄 오판 수정

처음에는 낮은 종횡비와 CRAFT의 수직 중심 차이만으로 두 줄을 판단했다. 이 규칙이 기울어진 한 줄 번호판 `23아9477`에서 차량 로고와 번호판 본문을 두 줄로 오인했다.

진짜 두 줄은 위·아래 text box가 x축에서 강하게 겹치고, 기울어진 한 줄의 분할 조각은 좌우로 어긋난다는 점을 이용했다. 두 줄로 인정하는 최소 수평 겹침을 짧은 박스 폭의 35%에서 65%로 높였다.

- `23아9477`: 두 줄 오판 → `23아9477` 한 줄로 복구
- `84소5409`: 기울어진 한 줄로 유지
- `인천75아2209`: 실제 두 줄로 유지
- tall 수량: 3,934 → 3,712
- CRAFT로 복구한 기울어진 한 줄: 15,052 → 15,299

무작위로 확인한 최종 tall 원본 8장은 모두 실제 두 줄 번호판이었다. 다만 자동 teacher 라벨이므로 제품 출시 전에는 test tall 392장을 사람이 전수 검수해야 한다.

## OCR 모델

구현 파일:

- `ocr_common.py`: 번호판 형식, 지역명 토큰, 두 줄 라벨 분리
- `build_ocr_dataset.py`: 검출, 줄 분리, 번호 단위 split, crop/TSV 생성
- `train_ctc_ocr.py`: 경량 CNN + BiGRU + CTC 학습
- `evaluate_ctc_ocr.py`: 줄/번호판 전체/종류별 평가와 스트레스 평가
- `infer_ctc_probabilities.py`: 서버 매칭용 timestep top-k 확률 JSONL
- `export_ctc_onnx.py`: ONNX fp32/int8 변환과 속도·오차 검증
- `evaluate_onnx_ctc.py`: 변환 모델 전수 정확도 검증

입력은 RGB 48×192이고 가로 시간축은 48 timestep이다. CNN은 높이를 강하게 줄이고 가로 해상도는 보존하며, 2-layer bidirectional GRU 뒤 CTC를 적용한다. 좌우 반전은 사용하지 않는다.

### 실패 실험: 처음부터 강한 증강

`plate_ctc_v1`은 처음부터 perspective 0.30, ±12° 회전, shear 7°, 큰 색 변화와 blur를 적용했다. epoch 15에도 검증 줄 완전일치 3.99%, CER 0.761에 머물렀고 여러 입력에 비슷한 번호를 출력했다. 저해상도 글자 형태를 배우기 전에 강한 변형을 적용한 것이 원인이므로 epoch 16 도중 중단했다. 실패 체크포인트와 history는 비교 근거로 보존했다.

### 성공 실험: 약한 증강 → 강한 증강 커리큘럼

1단계 `plate_ctc_v2_mild`:

- 약한 perspective, ±7° 회전, 작은 이동·색 변화, blur 확률 15%
- 30 epoch, batch 128, AdamW, 초기 lr 3e-4
- 최고 val 줄 완전일치 88.10%, CER 0.0320

독립 test 결과:

| 유형 | 번호판 수 | 번호판 전체 일치율 | CER |
| --- | ---: | ---: | ---: |
| 전체 | 6,046 | 87.18% | 3.06% |
| long | 4,640 | 86.85% | 3.01% |
| long_vregion | 1,014 | 88.95% | 2.65% |
| tall | 392 | 86.48% | 4.65% |

2단계 `plate_ctc_v3_strong`:

- `plate_ctc_v2_mild/best.pt`에서 시작
- 강한 perspective, ±12° 회전, shear, blur
- 10 epoch, lr 1e-4

clean test와 고정 시드 강한 스트레스 test 비교:

| 모델 | clean 전체 일치율 | strong 전체 일치율 | strong tall 일치율 |
| --- | ---: | ---: | ---: |
| v2 mild | 87.18% | 48.48% | 51.53% |
| v3 strong | 85.83% | 60.98% | 67.35% |

v3는 clean에서 1.35%p 손해를 보지만 강한 변형 전체에서 12.50%p, tall에서 15.82%p 개선됐다. 목표가 기울어진 번호판과 두 줄 번호판 대응이므로 최종 우선 모델은 다음 파일이다.

`/home/misys/cloudAIoT/plate_detector/runs/plate_ctc_v3_strong/best.pt`

스트레스 평가는 실제 카메라 평가셋이 아니라 고정된 합성 변형이라는 한계가 있다. 최종 선택은 데모 카메라로 촬영한 번호 단위 test set에서 다시 확인한다. clean 정확도가 더 중요한 배치에는 v2를 비교 후보로 유지한다.

## ONNX 배포 결과

산출물:

- fp32: `runs/plate_ctc_v3_strong/export/plate_ctc_fp32.onnx`
- 동적 int8: `runs/plate_ctc_v3_strong/export/plate_ctc_int8.onnx`
- 문자/입력 메타데이터: `runs/plate_ctc_v3_strong/export/model_metadata.json`
- 변환 보고서: `runs/plate_ctc_v3_strong/export/export_report.json`

| 항목 | fp32 ONNX | dynamic int8 ONNX |
| --- | ---: | ---: |
| 크기 | 2,163,163 bytes | 2,054,194 bytes |
| 개발 PC CPU, batch 1 | 1.24 ms | 2.64 ms |
| test 번호판 전체 일치율 | 85.83% | 85.40% |

PyTorch와 fp32 ONNX의 임의 입력 최대 절대 오차는 `9.54e-6`이며 test 정확도도 완전히 동일하다. 현재 dynamic int8은 크기 절감이 작고 더 느리며 정확도도 0.43%p 낮으므로 사용하지 않는다. 최종 Pi 후보는 fp32 ONNX다. 위 속도는 개발 PC 수치이며 Pi4 실측값이 아니다.

## 재현 명령

1단계 학습:

```bash
plate_detector/.venv/bin/python plate_detector/train_ctc_ocr.py \
  --data CAR_dataset/plate_detection_work/ocr_ctc_v2 \
  --output plate_detector/runs/plate_ctc_v2_mild \
  --epochs 30 --batch 128 --workers 4 --device cuda --augment mild
```

2단계 강건화:

```bash
plate_detector/.venv/bin/python plate_detector/train_ctc_ocr.py \
  --data CAR_dataset/plate_detection_work/ocr_ctc_v2 \
  --output plate_detector/runs/plate_ctc_v3_strong \
  --epochs 10 --batch 128 --workers 4 --device cuda --augment strong --lr 1e-4 \
  --init plate_detector/runs/plate_ctc_v2_mild/best.pt
```

서버 매칭용 CTC 확률 출력:

```bash
plate_detector/.venv/bin/python plate_detector/infer_ctc_probabilities.py \
  --weights plate_detector/runs/plate_ctc_v3_strong/best.pt \
  --images /path/to/plate_line_crop.jpg \
  --output /path/to/probabilities.jsonl --topk 5
```

## 현재 완료 상태와 남은 필수 작업

완료:

- CUDA/YOLO/OCR 학습 환경
- 블러 YOLO11n 기준 모델
- 선명 수동 라벨링 후보 2,000장/4묶음
- OCR 번호 단위 split 및 63,383개 줄 crop 생성
- 경량 CTC 학습, clean/강한 변형/종류별 평가
- CTC timestep top-k 출력
- fp32/int8 ONNX 변환과 전수 검증

남음:

1. 선명 2,000장 회전 박스 수동 교정과 평가 300장 이중 검수
2. YOLO blur+sharp 혼합 파인튜닝 및 선명 300장 recall 95% 확인
3. 검출 회전 꼭짓점으로 homography deskew를 적용해 OCR 입력 기울기를 먼저 제거
4. Pi 런타임용 한 줄/두 줄 분리 구현. CRAFT는 teacher로만 사용하고 PP-OCR mobile det 또는 더 작은 줄 분류/분할기를 비교
5. 데모 카메라로 앞·뒤·두 줄·야간·반사·큰 기울기를 포함한 번호 단위 test set 촬영 및 라벨링
6. Pi4에서 YOLO + deskew + 줄 분리 + fp32 ONNX의 실제 end-to-end 지연시간과 메모리 측정
7. 후보 N=10/50/200 버퍼 매칭, 다중 프레임 누적, ECE를 별도 평가

현재 85.83%는 **teacher가 잘라 준 AI Hub 번호판/줄 crop에서의 문자열 완전일치율**이다. 카메라 프레임부터 시작하는 end-to-end 성능이나 목표 검출 recall 95%를 의미하지 않는다. 수동 sharp detector 파인튜닝과 데모 카메라 평가가 완료돼야 실제 시스템 완료 조건을 판정할 수 있다.

## 웹캠 실시간 확인 도구

파일:

`/home/misys/cloudAIoT/plate_detector/webcam_plate_demo.py`

기본 실행:

```bash
cd /home/misys/cloudAIoT
plate_detector/.venv/bin/python plate_detector/webcam_plate_demo.py --camera 0
```

동작 순서:

1. `/dev/video0`에서 프레임 획득
2. `EasyKoreanLpDetector/lp_det.pt`로 선명 번호판 검출
3. 긴 판은 한 줄, 낮은 비율 판은 CRAFT로 두 줄 여부 확인
4. `plate_ctc_v3_strong/export/plate_ctc_fp32.onnx`로 줄별 OCR
5. 두 줄 결과를 위→아래 순서로 결합
6. 최근 12프레임 결과의 최빈값을 `안정화` 결과로 표시

조작키:

- `q` 또는 `ESC`: 종료
- `s`: 주석이 표시된 현재 프레임을 `plate_detector/webcam_captures/`에 저장
- `r`: 최근 결과 투표 기록 초기화

첫 실행 때 CRAFT 로딩 때문에 시작이 느릴 수 있다. 속도 우선 확인은 다음과 같이 비율 기반 줄 분리를 사용한다.

```bash
plate_detector/.venv/bin/python plate_detector/webcam_plate_demo.py \
  --camera 0 --line-mode ratio
```

두 줄이 없는 조건에서는 `--line-mode single`을 사용할 수 있다. 카메라가 다른 번호라면 `--camera 1`로 바꾼다. 검출을 더 민감하게 하려면 `--det-conf 0.10`, 흔들리는 출력의 안정화를 길게 하려면 `--history 20`을 사용한다.

창 없이 카메라와 전체 추론 경로만 검사:

```bash
plate_detector/.venv/bin/python plate_detector/webcam_plate_demo.py \
  --camera 0 --headless --max-frames 10 --line-mode ratio
```

실제 검증 결과:

- `/dev/video0`, `/dev/video1` 존재 확인
- OpenCV를 QT5 GUI 빌드로 정리
- `/dev/video0` 실제 프레임 읽기 성공
- YOLOv5 로드, 번호판 검출, ONNX OCR 호출 경로 성공
- headless 1프레임 정상 종료
- QT5 창 1프레임 표시 및 정상 종료
- 테스트 시 카메라 화면에 번호판이 없어서 OCR 문자열은 `-`로 출력됨

현재 웹캠 도구의 검출기는 기존 선명 번호판 teacher다. 수동 2,000장 혼합 파인튜닝이 끝나면 기본 `--detector`를 최종 `plate_mix_v1/best.pt`로 바꾸고 detector backend도 YOLO11에 맞춰 갱신해야 한다.

## Git 업로드용 독립 묶음

2026-10-09에 코드·모델·추가 학습 도구를 다음 한 폴더로 정리했다.

`/home/misys/cloudAIoT/SPASIBA_plate_ocr`

포함 항목:

- `src/`: 웹캠, 데이터 생성, 학습, 평가, ONNX 변환 코드 전체
- `models/detector/lp_det.pt`: 현재 웹캠용 선명 번호판 검출기
- `models/ocr/plate_ctc_v3_strong.pt`: 추가 학습 가능한 최종 PyTorch OCR
- `models/ocr/plate_ctc_fp32.onnx`: 배포용 최종 OCR
- `models/training/plate_blur_v1.pt`: sharp 혼합 검출기 학습 시작점
- `third_party/yolov5/`: 인터넷 다운로드 없이 `lp_det.pt`를 로드할 YOLOv5 소스와 AGPL-3.0 원문
- `reports/`: clean/strong/ONNX 평가 결과
- `README.md`, `.gitignore`, `.gitattributes`, 모델 SHA-256 목록

제외 항목:

- AI Hub 원본·라벨·OCR crop
- `CAR_dataset`과 모든 생성 학습 데이터
- `.venv`, `runs` 전체, cache와 웹캠 캡처

독립 검증 결과:

- 묶음 내부 fp32 ONNX 로드 성공: input `(1,3,48,192)`, output `(1,48,66)`
- 묶음 내부 YOLOv5와 `lp_det.pt` CPU 로드 성공
- 묶음 내부 기본 경로로 `/dev/video0` GPU 웹캠 한 프레임 처리 성공
- Python 전체 구문 검사 성공
- 전체 크기 약 27MB

다른 사용자는 AI Hub 데이터를 별도로 받아 README 형식으로 배치하면 최종 OCR 체크포인트에서 추가 학습하거나, 데이터셋 생성부터 다시 수행할 수 있다. 데이터 자체는 개인정보·이용조건 때문에 Git 묶음에 포함하지 않았다.

## 2026-10-14 Roboflow 추가 데이터, 균형 검출 학습, 웹캠 OCR 적응

### 입력 데이터 점검

`CAR_dataset`에 사용자가 내려받은 두 ZIP을 원본 그대로 보존하고 별도 디렉터리에 풀었다.

| 데이터 | 이미지 | 원래 라벨 | 처리 |
| --- | ---: | --- | --- |
| Korea CarPlate v3 | 1,291 | 2 classes, 대부분 segmentation polygon | 모두 `plate` 1 class AABB로 변환 |
| Korean license plate v2 | 2,381 | 1 class bbox, polygon 6개 | `plate` AABB로 통일 |

두 데이터 모두 Roboflow README 기준 CC BY 4.0이며 라이선스 원문을 생성 데이터셋의 `licenses/`에 복사했다. 문자열 OCR 정답은 없으므로 이 ZIP은 OCR 문자인식 모델이 아니라 **번호판 검출기**에만 사용했다.

Roboflow 증강본은 같은 원본 이름 뒤에 `.rf.<hash>`가 붙는다. 원본 이름 단위로 다시 묶어 80/10/10으로 결정론적 분할했고 train/val/test 원본 그룹 중복은 모두 0이다. 두 ZIP 사이의 같은 이름도 함께 그룹화했다. 빈 라벨 7장은 실제 번호판이 보이지만 정답 박스가 누락돼 제외했다.

최종 외부 데이터 수:

- train 2,913장
- val 404장
- test 348장, 번호판 349개
- polygon 1,290행을 축 정렬 bbox로 변환

재현 스크립트 `src/prepare_roboflow_detect_dataset.py`도 공유 폴더에 포함했다. 준비 과정에서 이미지 symlink를 쓰면 Ultralytics가 symlink 원본 경로의 다중 클래스 라벨을 읽는 문제가 확인됐다. 생성 이미지를 실제 파일로 복사하도록 수정했고 모든 라벨이 5필드 class 0인지 재검사했다.

### 검출 학습에서 발견한 실패와 수정

블러 31,830장과 외부 선명 train을 2회 반복해 한 번에 학습한 첫 시도는 통합 val 점수만 높고 외부 test 재현율이 11.5%에 불과했다. 블러 데이터가 검증·학습을 지배해 선명 도메인 실패가 가려진 것이다. 이 실행은 `plate_mix_roboflow_v2`에 보존하지만 사용하지 않는다.

수정한 학습 순서:

1. 일반 YOLO11n에서 외부 선명 데이터만 20 epoch 학습
2. 선명 모델을 시작점으로 선명 2,913장 + 블러 무작위 2,913장을 1:1로 구성해 통합 학습
3. 실제 웹캠 캡처 metadata의 최고 신뢰도 박스만 사용해 143 train / 36 val을 만들고, 균형 데이터와 함께 낮은 학습률로 6 epoch 적응

웹캠 캡처 분할은 번호판별 시간 순서 후반 20%를 val로 남겼다. 세 번호판의 연속 프레임이라 번호 단위 일반화 평가는 아니며, 휴대전화 화면 도메인에 맞추는 제한적 적응용이다. 생성 스크립트는 `src/prepare_webcam_pseudo_dataset.py`다.

최종 검출 성능:

| 모델/평가 | Precision | Recall | mAP50 | mAP50-95 |
| --- | ---: | ---: | ---: | ---: |
| 기존 `plate_blur_v1`, 외부 선명 test | 0% | 0% | 0% | 0% |
| 선명 전용 모델, 외부 test | 99.4% | 99.1% | 99.2% | 76.2% |
| 균형 모델, 외부 test | 99.4% | 99.1% | 99.2% | 74.9% |
| 균형 모델, 블러 val | 98.5% | 98.6% | 98.9% | 56.9% |
| **최종 웹캠 적응 모델, 외부 test** | **99.4%** | **99.1%** | **99.4%** | **75.5%** |
| **최종 웹캠 적응 모델, 블러 val** | **98.8%** | **98.4%** | **99.1%** | **57.1%** |
| **최종 웹캠 적응 모델, 웹캠 val** | **99.8%** | **100%** | **99.5%** | **71.4%** |

완료 기준인 선명 평가 재현율 95% 이상을 외부 test에서 99.1%로 충족했다. 최종 가중치는 `models/detector/plate_yolo11n_balanced_webcam_v1.pt`이며, 웹캠 도메인 적응 전 모델도 `plate_yolo11n_balanced_v1.pt`로 보존했다.

### 웹캠 코드 YOLO11 연결

`src/webcam_plate_demo.py`에 `--detector-backend auto|yolo11|yolov5`를 추가했다. 새 기본 가중치가 있으면 YOLO11을 자동 선택하고, 기존 `lp_det.pt`를 지정하면 YOLOv5 경로도 계속 사용할 수 있다. YOLO11 NMS IoU를 0.40으로 설정해 한 번호판의 중첩 검출을 제거했다.

세 대표 저장 프레임에서 적응 전 새 모델은 낮은 신뢰도와 배경 오검출이 있었지만, 최종 모델은 각 프레임에서 번호판 1개만 남겼다. 검출 신뢰도는 각각 0.846, 0.721, 0.829였다.

### OCR hard-example 파인튜닝

Roboflow ZIP에는 문자열 라벨이 없으므로 OCR에는 직접 사용할 수 없다. 대신 기존 캡처 metadata의 `expected_plate`를 이용했다. 검출 박스 비율이 2.6 미만이면 윗줄/아랫줄로 자르고 `split_two_line()`으로 정답도 나눴다. AI Hub OCR 50,457 train 줄에 웹캠 266 train 줄을 20회 반복해 55,777줄로 구성했다. 시간 후반 69줄/36프레임은 웹캠 val로 보류했다.

재현 스크립트: `src/prepare_webcam_ocr_adaptation.py`

기존 `plate_ctc_v3_strong.pt`에서 lr `5e-5`, mild augmentation, batch 256으로 5 epoch 학습했고 4 epoch 체크포인트가 최적이었다.

| OCR 평가 | 기존 | 최종 |
| --- | ---: | ---: |
| 웹캠 val 전체 번호판 일치율 | 0.00% | **83.33%** |
| 웹캠 tall 33장 전체 일치율 | 0.00% | **87.88%** |
| 웹캠 line 일치율 | 0.00% | **89.86%** |
| AI Hub val 전체 번호판 일치율 | 약 85.8~86.2% | **87.60%** |
| AI Hub tall 전체 일치율 | - | **89.30%** |

최종 PyTorch/ONNX/int8 모델은 `models/ocr_webcam_v1/`에 저장했다. 현재 개발 PC에서 fp32 ONNX는 약 1.87ms, dynamic int8은 약 4.59ms로 int8이 더 느렸으므로 Pi4에서 따로 측정하기 전에는 fp32를 기본으로 둔다. PyTorch와 fp32 ONNX 최대 절대 오차는 `1.53e-5`였다.

### 최종 end-to-end 확인

최종 YOLO11 검출 → 비율 기반 줄 분리 → 새 fp32 ONNX OCR을 실제 저장 프레임에 연결한 결과:

시간 후반 보류 프레임 36장 전체를 metadata 정답 crop이 아니라 최종 detector 출력부터 처리한 end-to-end 전체 일치율은 **30/36 = 83.33%**였고 검출 누락은 0장이었다. 번호판별로는 `경기51거2824` 14/15, `137로2805` 4/9, `서울12가3456` 12/12였다. 현재 남은 주 오류는 한 줄 `137로2805`의 각도·crop 변화다.

| 정답 | 최종 예측 | 검출 신뢰도 | OCR 신뢰도 | 결과 |
| --- | --- | ---: | ---: | --- |
| `서울12가3456` | `서울12가3456` | 0.846 | 0.878 | 정확 |
| `137로2805` | `137로2805` | 0.721 | 0.931 | 정확 |
| `경기51거2824` | `경기51거2824` | 0.829 | 0.955 | 정확 |

공유 폴더 기본 실행:

```bash
cd SPASIBA_plate_ocr
python src/webcam_plate_demo.py --camera 0 --line-mode ratio
```

전체 모델 파일 확인:

```bash
python verify_bundle.py
python verify_bundle.py --full
```

### 해석과 남은 제한

- 선명 외부 test의 99.1% recall은 Roboflow 두 데이터의 원본 그룹 중복을 막은 결과다.
- 웹캠 100% 검출 recall과 OCR 83.3%는 같은 세 번호판의 시간 분리 결과이며 새로운 번호판으로의 일반화 수치가 아니다.
- 대표 세 프레임은 모두 정확해졌지만 휴대전화 화면 특성을 외울 수 있다. 실제 데모가 인쇄물/모형 차량이면 그 환경의 새 번호판을 번호 단위 hold-out으로 추가 평가해야 한다.
- 현재 검출은 회전 증강을 적용한 AABB다. 심한 회전에서 판을 수평화하려면 검수된 OBB 또는 네 꼭짓점 라벨이 여전히 가장 올바른 장기 해법이다.
- 데이터·원본 캡처·학습 runs는 개인정보와 용량 때문에 공유 폴더에 넣지 않았고, 재학습 코드와 최종 체크포인트만 포함했다.
- 이번 작업 중 Git 명령, commit, push는 실행하지 않았다.

## 2026-10-14 최종 공유 묶음 확인

이번 작업의 최종 전달 위치는 `/home/misys/cloudAIoT/SPASIBA_plate_ocr/`이고 전체 크기는 약 43MB다. 원본 AI Hub/Roboflow 데이터와 웹캠 캡처는 개인정보·라이선스·용량 때문에 넣지 않았으며, 실행과 재학습에 필요한 코드·가중치·설명·평가 결과만 모았다.

최종 기본 파일:

- 검출기: `models/detector/plate_yolo11n_balanced_webcam_v1.pt`
- 배포 OCR: `models/ocr_webcam_v1/plate_ctc_fp32.onnx`
- 추가 학습 OCR: `models/ocr_webcam_v1/plate_ctc_webcam_v1.pt`
- 웹캠 실행: `src/webcam_plate_demo.py`
- Roboflow 변환: `src/prepare_roboflow_detect_dataset.py`
- 웹캠 검출 데이터 생성: `src/prepare_webcam_pseudo_dataset.py`
- 웹캠 OCR 데이터 생성: `src/prepare_webcam_ocr_adaptation.py`
- 실행·재학습 안내: `README.md`
- 모델 무결성 목록: `MODEL_SHA256SUMS.txt`

최종 검증 결과:

1. 수정 Python 파일 전체 구문 검사 통과
2. `MODEL_SHA256SUMS.txt`에 등록한 12개 모델·메타데이터 파일 전부 SHA-256 검사 통과
3. fp32 ONNX 입력 `(1, 3, 48, 192)`, 출력 `(1, 48, 66)` 확인
4. 최종 YOLO11 가중치 CPU 로드 및 더미 이미지 추론 통과
5. 세 대표 실제 프레임에서 최종 detector → 줄 분리 → ONNX OCR 결과 모두 정답
6. YOLO11 IoU 0.40 NMS 적용 후 대표 프레임마다 중복 없이 검출 1개만 반환

기본 실행 명령:

```bash
cd ~/cloudAIoT/SPASIBA_plate_ocr
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python verify_bundle.py --full
python src/webcam_plate_demo.py --camera 0 --line-mode ratio
```

CUDA 12.8 환경에서는 README에 적은 PyTorch CUDA wheel 설치 명령을 먼저 사용한다. 모델 파일은 `.gitattributes`에서 `*.pt`, `*.onnx`를 Git LFS 대상으로 지정했지만, 이 작업에서는 사용자의 명시적 지시가 없었으므로 Git 저장소 조작이나 업로드를 수행하지 않았다.

## 2026-10-14 웹캠 실행 환경 오류 수정

`source ../plate_detector/.venv/bin/activate` 실행 시 파일이 없고 시스템 Python에서 `ModuleNotFoundError: cv2`가 발생했다. 확인 결과 가상환경 디렉터리와 설치 패키지는 정상이지만 `bin/activate` 스크립트만 없었다. 가상환경 Python을 직접 실행하면 `cv2 5.0.0`, `torch 2.11.0+cu128`, CUDA, Ultralytics, ONNX Runtime을 모두 정상 로드했다.

`python3-venv` 시스템 패키지가 설치되지 않아 `python -m venv --upgrade`로 activate를 재생성할 수는 없었다. 기존 가상환경은 손상되지 않았고 실제 `/dev/video0` 한 프레임에서 최종 YOLO11과 OCR 경로가 정상 실행됐다.

사용자가 activate 경로를 알 필요가 없도록 `run_webcam.sh`를 추가했다. 이 스크립트는 다음 순서로 Python을 선택한다.

1. 공유 폴더의 `.venv/bin/python`
2. 현재 서버의 `../plate_detector/.venv/bin/python`
3. 시스템 `python3`

현재 서버 실행 명령:

```bash
cd ~/cloudAIoT/SPASIBA_plate_ocr
bash run_webcam.sh --camera 0 --line-mode ratio
```

직접 실행하려면 다음 명령도 동일하게 동작한다.

```bash
../plate_detector/.venv/bin/python src/webcam_plate_demo.py \
  --camera 0 --line-mode ratio
```
