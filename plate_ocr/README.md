# 번호판 OCR (CRNN + CTC)

계획서 `OCR 기반 자동차 번호판 인식 모델`의 인식(OCR) 쪽 최소 동작 버전.
AI Hub 데이터 승인과 2,000장 수동 라벨링이 필요한 부분을 빼고, **합성 번호판**으로 학습한다.

## 결과

| 실험 | 두 줄 펴기 | 완전일치 | 글자정확도 | 시간 |
|---|---|---|---|---|
| `runs/crnn_v1`        | 없음 | 68.85% | 87.01% | 9.2분 |
| `runs/crnn_v2_unfold` | 적용 | **99.90%** | **99.99%** | 9.4분 |

종류별 (v2, 종류당 500장)

| 종류 | 완전일치 | 글자정확도 |
|---|---|---|
| 흰색 긴형   |  99.80% | 99.97% |
| 노란 긴형   | 100.00% | 100.00% |
| 노란 두줄   |  99.40% | 99.93% |
| 초록 두줄   |  99.40% | 99.93% |

v1에서 두 줄 번호판 정확도가 0%였다. CNN이 세로를 1로 누르면서 윗줄(지역명)이
아랫줄에 묻혀, 모델이 아랫줄만 읽고 윗줄은 최빈값 `경남17`로 찍었다.

```
경북39사6894  →  경남17사6894
제주23아9022  →  경남17아9022
```

`unfold.py`가 가로세로비로 두 줄을 판별해(두 줄 ~2.0, 긴형 ~4.7) 윗줄·아랫줄을
좌우로 이어 붙인다. 모델과 하이퍼파라미터는 그대로 두고 이 전처리만 넣어 99.9%가 됐다.
실제 파이프라인에서도 검출기 박스의 비율로 같은 판별이 가능하다.

## 구성
- `src/synth.py`      — 한국 번호판 합성 (흰 긴형 / 노란 긴형 / 노란 두줄 / 초록 두줄,
                        비율은 계획서 A-2 구성 1000:400:300:300을 따름)
                        증강: 원근·회전·밝기·블러·저해상도·노이즈·JPEG
- `src/unfold.py`     — 두 줄 번호판을 한 줄로 펴기
- `src/train.py`      — CRNN(CNN 6층 + 2층 BiLSTM, 5.3M) + CTCLoss, AMP, OneCycleLR
- `src/eval_bytype.py`— 번호판 종류별 평가 (계획서 A-7 '종류별 비교'에 해당)
- `src/predict.py`    — 학습된 가중치로 이미지 읽기

## 환경 만들기
python 3.10, torch 2.11.0+cu128 기준. RTX 3070 Ti Laptop 8GB에서 14 epoch 약 9분.

```bash
cd plate_ocr
python3 -m venv venv
# ubuntu 에서 python3-venv 가 없어 pip 이 빠지면:
#   curl -sS -o /tmp/get-pip.py https://bootstrap.pypa.io/pip/get-pip.py && ./venv/bin/python /tmp/get-pip.py
./venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128
./venv/bin/pip install opencv-python-headless pillow numpy
```

한글 폰트가 필요하다 (`src/synth.py`의 `FONT`). 우분투 기본 `Noto Sans CJK`를 쓴다.
```bash
fc-list :lang=ko | head     # 없으면: sudo apt install fonts-noto-cjk
```

## 실행
```bash
cd plate_ocr
./venv/bin/python src/synth.py                      # 합성 미리보기 -> data/preview/
./venv/bin/python src/train.py --out runs/my_run    # 학습 (14 epoch, 약 9분)
./venv/bin/python src/eval_bytype.py --ckpt runs/my_run/best.pt
./venv/bin/python src/predict.py data/preview/*.png # 파일명의 정답과 자동 대조
./venv/bin/python src/train.py --no-unfold          # 두 줄 펴기 끈 비교 실험
```

학습된 가중치는 `runs/crnn_v1/best.pt`(펴기 없음)와 `runs/crnn_v2_unfold/best.pt`(펴기 적용)로
같이 올려두었다. `src/predict.py`와 `src/eval_bytype.py`는 기본으로 v2를 쓴다.

## 실제 데이터로 옮길 때
1. 계획서 A-8 결과(번호판 박스 CSV)로 AI Hub OCR crop 9만 장을 잘라낸다
2. `train.py`의 `PlateSet`을 합성 대신 그 crop + 번호 라벨을 읽도록 바꾼다
   (`unfold`는 그대로 쓴다 — 실제 두 줄 판에도 같은 문제가 생긴다)
3. 합성 데이터는 섞어 두면 드문 종류(두 줄, 어두운 사진) 보강에 쓸 수 있다

## 한계
합성 데이터만으로 학습했으므로 99.9%는 **합성 분포 안에서의 점수**다.
실제 사진은 폰트·조명·오염·각도가 더 다양해서 그대로 나오지 않는다.
실제 성능은 AI Hub crop으로 다시 재야 한다.

이 폴더에는 AI Hub 데이터가 들어 있지 않다. `data/preview/`의 이미지는 전부
`src/synth.py`가 만든 합성 번호판이다.
