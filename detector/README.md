# detector — 번호판 검출기

SPASIBA 파이프라인의 **① 번호판 검출** 단계입니다. 카메라 화면 전체에서 번호판 영역을 박스 하나로 잡아 OCR로 넘깁니다.

```
[Pi] 카메라 → ① 번호판 검출 (여기) → ② 한 줄/두 줄 판단 → ③ 줄 검출(PP-OCR det) → ④ 글자 인식(CTC) → 서버
```

| 항목 | 값 |
|---|---|
| 기본 모델 | **`weights/plate_v3.pt`** (YOLO11n, 클래스 `plate` 1개, 5.5MB) |
| 입력 | 카메라 화면 전체 (차를 따로 자르지 않음, `direct` 방식) |
| 출력 | 번호판 박스 (두 줄 번호판도 박스 하나) |
| 학습 데이터 | Roboflow 차량 사진 4종 7,779장 + AI Hub 두 줄·초록 번호판 900장 |

자세한 실험 과정과 판단 근거는 [`docs/plate_detector_v2.md`](../docs/plate_detector_v2.md)에 있습니다.

---

## 1. 왜 검출기를 따로 두나

OCR만 화면 전체에 돌리면 생기는 문제 두 가지를 막습니다.

| 문제 | 검출기가 하는 일 |
|---|---|
| 번호판이 아닌 글자를 읽음 (차 로고·모델명, 매장 간판, 택시 표시등, 광고) | 번호판 박스 안에서만 OCR을 돌림 |
| 두 줄 번호판(초록 구형, 노란 영업용, 화물차)의 위아래 줄이 같은 번호판인지 모름 | 두 줄 전체를 **박스 하나**로 잡음 → 그 crop 안의 글자는 전부 한 번호판 |

검출기는 글자를 읽지 않습니다. 한 줄/두 줄 판단(②)은 crop 안에서 ③이 센 줄 수로 합니다.

---

## 2. 바로 써보기

```bash
source ~/sooin/spasiba/venv/bin/activate
cd ~/sooin/spasiba/SPASIBA/detector
```

```python
from ultralytics import YOLO

model = YOLO("weights/plate_v3.pt")
r = model.predict("car.jpg", conf=0.25, verbose=False)[0]
for x1, y1, x2, y2 in r.boxes.xyxy.int().tolist():
    plate_crop = r.orig_img[y1:y2, x1:x2]        # → ③ 줄 검출 / ④ 글자 인식으로 넘김
```

여러 사진에 돌려 결과 그림을 보려면:

```bash
python test_real.py <사진 폴더> direct                  # → real_test_out_direct/ (빨강 = 번호판, 숫자 = 확신도)
python test_real.py <사진 폴더> direct <다른 가중치.pt>  # 다른 모델과 비교할 때
```

- 확신도 0.25 이상인 번호판을 **전부** 그립니다 (배경 차 번호판 포함).
- `two_stage`(COCO 모델로 차를 먼저 찾고 그 안에서 번호판 찾기)도 있지만, 결과가 같고 계산만 늘어서 쓰지 않습니다.

---

## 3. 성능

### 검증 세트 (출처별, 학습과 겹치지 않게 번호·유사 사진 단위로 분할)

| 출처 | 장면 | 이미지 | Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|---|---|
| rf_alpr | 서울 거리 CCTV, 컬러 | 588 | 0.975 | 0.969 | 0.989 | 0.788 |
| rf_lp_detect | 주차장 고정 카메라, 흑백 | 216 | 0.999 | 0.960 | 0.983 | 0.809 |
| rf_korean_license | 블랙박스, 길가 주차 차량 | 40 | 0.949 | 0.833 | 0.931 | 0.572 |
| rf_plate_night | 야간 고정 카메라, 흑백 | 31 | 0.998 | 1.000 | 0.995 | 0.802 |
| AI Hub 두 줄·초록 crop | 번호판 crop | 100 | 0.999 | 1.000 | 0.995 | 0.851 |

rf_korean_license의 Recall이 낮은 이유는 폭 20px 미만의 먼 번호판이 많아서입니다.

### 실제 사진 (학습에 쓰지 않은 웹 사진)

| 세트 | 결과 |
|---|---|
| 일반 차량 21장 (`data/image/`) | 21장 모두 번호판 검출 (박스 26개, 배경 차 번호판 포함). v2에서 놓친 초록 구형 번호판도 검출 |
| 초록 번호판 26장 (`data/test_green/`, 직접 라벨링) | 폭 30px 이상 번호판 **30/30**을 덮는 박스 검출 |

알려진 한계:

- **초록 번호판 박스가 넉넉합니다** (정답 박스의 약 1.6배). 번호판 거치 홈까지 잡히지만 두 줄을 모두 덮으므로 OCR에는 지장이 없습니다.
- **폭 30px 미만의 아주 작은 번호판**은 대부분 놓칩니다. 가까운 거리의 주차장 카메라에서는 영향이 작습니다.
- **실제 지하주차장 + 데모 모형 환경**의 사진으로는 아직 평가하지 않았습니다.

---

## 4. 학습 데이터

모든 데이터는 저장소 밖 `~/sooin/spasiba/data/`에 있습니다 (스크립트는 `../../data`를 기본 경로로 씁니다).

| 데이터 | 경로 | 내용 |
|---|---|---|
| Roboflow 4종 | `data/rf_alpr/`, `rf_lp_detect/`, `rf_korean_license/`, `rf_plate_night/` | 차 + 선명한 번호판 사진. 출처·버전은 `download_rf.py` 참고 |
| `plate_v2` | `data/plate_v2/` | 위 4종을 `plate` 클래스 하나로 합침. train 7,779 / val 875 (이미지는 원본 링크) |
| `aihub_rare` | `data/aihub_rare/` | AI Hub OCR crop 중 두 줄·초록 번호판 후보 3,688장 |
| `aihub_sel_1000` | `data/aihub_sel_1000/` | 그중 1,000장 + 자동 생성 박스. train 900 / val 100 |
| `plate_v3` | `data/plate_v3/data.yaml` | `plate_v2` + `aihub_sel_1000` |
| `test_green` | `data/test_green/` | 초록 번호판 평가 세트 26장. **학습 금지** |

쓰지 않는 데이터와 이유:

| 데이터 | 이유 |
|---|---|
| AI Hub 원본 프레임 (`yolo_plate/`) | 번호판이 전부 블러 → 모자이크를 번호판으로 배움 (v1의 실패 원인) |
| Roboflow `car_with_plate` | 물체 하나씩 잘린 crop이고 번호판이 모자이크 |
| AI Hub OCR crop 전체 | 차 맥락이 없는 crop이라 많이 넣으면 "번호판 = 화면을 채우는 것"을 배움. 두 줄·초록만 1,000장(약 11%) 사용 |

---

## 5. 처음부터 다시 만들기

```bash
python download_rf.py list                    # Roboflow 버전 확인 (API 키는 실행할 때 입력)
python download_rf.py get lp_detect=11 plate_night=3 alpr=1 korean_license=6
python check_rf_sets.py                       # 데이터 점검: 통계, 중복, 샘플 그림 → rf_check/
python make_plate_v2.py                       # → data/plate_v2/
python collect_aihub_rare.py                  # AI Hub 두 줄·초록 후보 → data/aihub_rare/
python make_plate_v3.py                       # test_green, aihub_sel_1000, plate_v3 생성
```

`make_plate_v3.py`는 AI Hub crop에 박스를 만들 때 `plate_ft_rf_v1`과 `plate_v2`가 필요합니다 (archive에 보관, 아래 7장).

학습 (tmux 안에서, RTX 4090 기준 약 15분):

```bash
yolo detect train model=yolo11n.pt data=$HOME/sooin/spasiba/data/plate_v3/data.yaml \
     imgsz=640 batch=64 epochs=50 device=0 workers=8 project=runs name=plate_v3 \
     degrees=10 perspective=0.0005 shear=5 scale=0.5 hsv_v=0.5 fliplr=0.0
```

| 옵션 | 이유 |
|---|---|
| `model=yolo11n.pt` | COCO 사전학습에서 시작. Pi 4에서 돌릴 수 있는 가장 작은 크기 |
| `degrees=10`, `perspective`, `shear` | 기울어지거나 비스듬히 본 번호판 |
| `scale=0.5` | 거리에 따른 크기 변화 |
| `hsv_v=0.5` | 어두운 주차장 |
| `fliplr=0.0` | 좌우 반전 금지 (글자가 뒤집힘) |

평가:

```bash
yolo detect val model=weights/plate_v3.pt data=$HOME/sooin/spasiba/data/test_green/data.yaml
yolo detect val model=weights/plate_v3.pt data=$HOME/sooin/spasiba/data/plate_v2/eval/val_rf_alpr.yaml  # 출처별
```

---

## 6. 파일 구성

| 파일 | 하는 일 |
|---|---|
| `weights/plate_v3.pt` | **기본 검출기** |
| `weights/plate_v3_train/` | 학습 설정(`args.yaml`)과 epoch별 기록(`results.csv`, `results.png`) |
| `test_real.py` | 사진 폴더에 모델을 돌려 결과 그림 저장 |
| `download_rf.py` | Roboflow 데이터셋 버전 확인·다운로드 |
| `check_rf_sets.py` | Roboflow 데이터 점검 (통계, 중복, 테스트 세트와 겹침, 샘플 그림) |
| `make_plate_v2.py` | `plate_v2` 데이터셋 생성 |
| `collect_aihub_rare.py` | AI Hub OCR crop에서 두 줄·초록 번호판 후보 모으기 (PP-OCR 줄 검출 + 색) |
| `make_plate_v3.py` | 초록 평가 세트, AI Hub 1,000장 자동 박스, `plate_v3` 생성 |
| `make_yolo_dataset.py`, `make_synth.py`, `test_on_sharp.py`, `check_roboflow.py` | v1 시기 스크립트 (블러 데이터셋, 합성, Roboflow crop 점검) |

---

## 7. 지난 모델

| 모델 | 학습 데이터 | 결과 | 상태 |
|---|---|---|---|
| `plate_blur_v1` | AI Hub 원본 프레임 (번호판 블러) | 선명한 번호판 0/48 | 사용 안 함 |
| `plate_ft_rf_v1` | blur_v1 + Roboflow 번호판 crop | crop 안에서 번호판 박스 잡기에 사용 (AI Hub 자동 박스) | 보조 도구 |
| `plate_mix_v1`, `v1-2` | 블러 + crop 섞기 | 실제 사진에서 대부분 놓침 | 사용 안 함 |
| `plate_v2` | Roboflow 4종 | 실제 사진 20/21, 초록 구형 번호판 놓침 | v3로 대체 |
| **`plate_v3`** | v2 + AI Hub 두 줄·초록 900장 | v2 성능 유지 + 초록 구형 번호판 검출 | **기본** |

지난 모델 가중치와 결과 그림은 저장소 밖 `~/sooin/spasiba/archive/detector_20261013/`에 있습니다.

---

## 8. 주의 사항

- **선명한 번호판은 개인정보입니다.** 데이터와 결과 그림(`*.jpg`, `*.png`)은 커밋하지 않고, 외부 라벨링 서비스에 올리지 않습니다. 발표 자료에서는 번호판을 가립니다.
- AI Hub 데이터는 이용 조건(학습·연구 목적, 재배포 금지) 안에서 씁니다. Roboflow 데이터는 각 데이터셋 페이지의 라이선스를 따릅니다.
- `download_rf.py`는 API 키를 실행할 때 입력받습니다. 키를 명령어나 파일에 적지 않습니다.
- 학습·대량 처리는 `tmux` 안에서 실행하고, GPU를 쓰기 전에 `nvidia-smi`로 다른 사용자를 확인합니다.
