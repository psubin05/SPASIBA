# detector — 번호판 검출기

SPASIBA 파이프라인의 **① 번호판 찾기** 단계를 담당하는 YOLO 번호판 검출기 코드입니다.

```
카메라 화면 → [① 번호판 검출 (여기)] → ② 모양 판단 → ③ 줄 검출 → ④ 글자 인식 → 서버 버퍼 매칭
```

---

## 1. 이 폴더가 해결하는 일 두 가지

| | 일 1: 실제 시스템 | 일 2: OCR 학습 데이터 정리 |
|---|---|---|
| 입력 | 카메라 화면 (차 전체가 보임) | AI Hub OCR crop (번호판 위주 이미지) |
| 하는 일 | 차에서 번호판 위치 찾기 → crop → OCR로 전달 | crop 안에서 번호판만 딱 맞게 다시 자르기 |
| 필요한 학습 데이터 | 선명한 번호판 + 차 전체 맥락 | 선명한 번호판 위주 이미지 + 박스 |

두 일은 입력 모습이 완전히 달라서 **같은 모델 하나로 해결할 수 없습니다** (6장 실험 결과 참고).

---

## 2. 파일 구성

| 파일 | 하는 일 | 상태 |
|---|---|---|
| `make_yolo_dataset.py` | AI Hub 원본 프레임 + 라벨 → 차량 주변 crop + YOLO 라벨 (`yolo_plate/`) | 실행 완료 |
| `test_on_sharp.py` | 학습한 모델을 선명한 OCR crop 48장에 돌려 결과 그림 저장 | 실행 완료 |
| `test_world.py` | YOLO-World(학습 없이 "license plate"로 검출)를 같은 48장에 시험 | 작성됨, 미실행 |
| `make_synth.py` | 블러 번호판 자리에 선명한 OCR 번호판을 붙여 합성 데이터 생성 | 작성됨, 미실행 |
| `runs/` | YOLO 학습 결과 (가중치, 그래프) — **Git에 올리지 않음** | - |

---

## 3. 데이터

모든 데이터는 저장소 밖 `~/sooin/spasiba/data/`에 있습니다. **데이터와 가중치는 GitHub에 올리지 않습니다.**

| 데이터 | 경로 | 내용 |
|---|---|---|
| AI Hub 원본 라벨 | `data/103.자동차_…/추가_데이터_보완_건_220114(원본이미지추가개방)/원본이미지(추가개방)/라벨링데이터/merged/` | 차량·번호판 박스 50만 개 (번호판 박스 491,194개) |
| AI Hub 원본 프레임 | `…/원본이미지(추가개방)/원천데이터/` | 원천데이터11만 받음, 34,980장 |
| AI Hub OCR crop | `data/103.자동차_…/01.데이터/` | 선명한 번호판 crop 9만 장 + 번호 텍스트 |
| YOLO 데이터셋 (블러) | `data/yolo_plate/` | 학습 31,830장 / 검증 3,037장 |
| 합성 데이터셋 | `data/yolo_plate_synth/` | `make_synth.py` 실행 시 생성 |
| Roboflow korea car plat | `data/roboflow_korea_plate/` | 받을 예정. OCR crop + 번호판 박스 약 1,000장 |

### AI Hub 원본 데이터의 특징 (중요)

- **한 프레임에 가장 크게 보이는 차 1대만 라벨링**되어 있다. 프레임 전체로 학습하면 다른 차 번호판이 배경으로 학습되므로, **라벨된 차량 주변만 잘라서** 학습한다.
- **번호판이 전부 블러(모자이크) 처리**되어 있다. 이것만으로 학습하면 "뿌연 사각형"을 번호판으로 배운다.
- 거의 **전면** 사진이다 (교차로 CCTV).

---

## 4. 환경

```bash
source ~/sooin/spasiba/venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install ultralytics opencv-python-headless
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

서버: AIX408-35 (RTX 4090), Ultralytics 8.4.173, torch 2.11.0+cu128

---

## 5. 사용법

### 5.1 YOLO 데이터셋 만들기

```bash
cd ~/sooin/spasiba/SPASIBA/detector
python make_yolo_dataset.py ../../data
```

- 원본 라벨과 프레임을 파일명(`imagePath`)으로 매칭한다.
- 차량 박스를 상하좌우 `MARGIN`(기본 5%)만큼 넓혀 자른다.
- crop 안에 60% 이상 들어온 번호판을 모두 정답으로 넣는다. 폭 20px 미만 번호판은 제외한다.
- 긴 변이 640px보다 크면 줄여서 저장한다.
- **영상(videoName) 단위로** 학습 90% / 검증 10%를 나눈다.
- 결과: `data/yolo_plate/` (`data.yaml`, `preview.jpg` 포함). 10~20분 소요.

### 5.2 기준 모델 학습

```bash
yolo detect train model=yolo11n.pt data=$HOME/sooin/spasiba/data/yolo_plate/data.yaml \
     imgsz=640 batch=64 epochs=30 device=0 workers=8 project=runs name=plate_blur_v1 \
     degrees=10 perspective=0.0005 shear=5 scale=0.5 hsv_v=0.5 fliplr=0.0
```

| 옵션 | 의미 |
|---|---|
| `degrees=10` | ±10° 회전 증강 |
| `perspective`, `shear` | 비스듬히 본 효과 |
| `scale=0.5` | 크기 변화 |
| `hsv_v=0.5` | 밝기 변화 (어두운 주차장 대비) |
| `fliplr=0.0` | 좌우 반전 끔 (글자가 뒤집히면 안 됨) |

가중치 위치: `runs/detect/runs/plate_blur_v1/weights/best.pt` (`project=runs` 옵션 때문에 `runs`가 두 번 들어감)

### 5.3 선명한 번호판 시험

```bash
python test_on_sharp.py ../../data                 # 기준 모델로 OCR crop 48장 → sharp_test.png
python test_world.py ../../data                    # YOLO-World로 같은 48장 → world_test.png
```

`test_world.py`에서 `clip` 관련 에러가 나면:

```bash
pip install git+https://github.com/ultralytics/CLIP.git
```

### 5.4 합성 데이터로 실제 환경 흉내 내기

```bash
python make_synth.py ../../data val
yolo detect val model=runs/detect/runs/plate_blur_v1/weights/best.pt \
     data=$HOME/sooin/spasiba/data/yolo_plate_synth/data.yaml split=val device=0 \
     project=runs name=blur_v1_on_synth
```

블러 번호판 자리에 OCR crop의 선명한 번호판(가장자리를 대충 잘라냄)을 크기와 밝기를 맞춰 붙인다. 박스 위치는 원래 라벨 그대로다.

---

## 6. 실험 기록

| 날짜 | 실험 | 결과 | 해석 |
|---|---|---|---|
| 10/05 | `plate_blur_v1` 학습 (블러 3.2만 장, 30 epoch, 29분) | 블러 검증: P 0.997 / R 0.998 / mAP50 0.994 / mAP50-95 0.654 | 블러 번호판끼리라 점수가 높음. 실제 성능을 뜻하지 않음 |
| 10/05 | `plate_blur_v1`을 선명한 OCR crop 48장에 적용 | **사실상 0/48** (엉뚱한 작은 박스 2개뿐) | 모델이 "번호판"이 아니라 "모자이크 사각형"을 배움. OCR crop은 차 맥락도 없어 조건이 전혀 다름 |

---

## 7. 앞으로 할 일

> **라벨링 방침:** AI Hub OCR crop을 우리가 직접 2,000장 라벨링하는 계획은 **보류**한다. 먼저 Roboflow `korea car plat`(이미 번호판 박스가 그려진 OCR crop 약 1,000장)을 받아 보고, 품질이 괜찮으면 **손 라벨링을 이걸로 대체**한다. 직접 라벨링은 Roboflow 데이터가 부족하거나 품질이 나쁠 때만 한다.

1. **Roboflow `korea car plat` 데이터 받기** (OCR crop + 번호판 박스 약 1,000장)
   - 라벨 품질 확인 (느슨한 박스가 있음) → 쓸 만한지 판단
   - 원본이 AI Hub 데이터로 보이므로, 우리 평가 세트와 **같은 번호가 겹치지 않게** 숫자로 대조
   - 괜찮으면: 이 데이터로 학습 + 평가 세트만 소량(약 300장) 직접 검수
   - 부족하면: 모자란 종류(두 줄, 후면 등)만 직접 라벨링해서 보충
2. **일 2용 검출기**: 기준 모델에서 출발해 Roboflow 데이터로 파인튜닝 → OCR crop 9만 장에 번호판 박스 자동 생성 (일부 사람이 검수)
3. **일 1용 검출기**: 2번에서 잘라낸 선명한 번호판을 블러 자리에 합성 (`make_synth.py` 확장) → 학습
4. **실제 차 사진 평가 세트**: 팀원 차량이나 데모 모형 차를 직접 찍어 100~200장 (앞·뒤, 여러 각도, 어두운 조명). **학습에는 섞지 않음**
5. **데모 사진 파인튜닝**: 모형 차 + 확대 번호판 환경에 맞추기
6. 기울어진 번호판이 많으면 회전 박스 라벨로 **YOLO OBB** 모델 시험

---

## 8. 주의 사항

- 선명한 번호판은 **개인정보**다. 데이터는 팀 내부에서만 쓰고, 공개 웹 라벨링 도구나 저장소에 올리지 않는다. 발표 자료에서는 번호판을 가린다.
- AI Hub 데이터는 이용 조건(학습·연구 목적, 재배포 금지) 안에서 사용한다.
- Roboflow 다운로드 링크에는 개인 API 키가 들어 있다. 공용 서버 명령어 기록에 남지 않게 주의한다.
- 공용 서버라 `git config --global` 대신 저장소 안에서만 사용자 설정을 한다.

### `.gitignore`에 들어가야 할 것

```gitignore
runs/
*.pt
*.png
*.jpg
```