# deploy — 라즈베리파이에서 번호판 읽기

서버에서 학습한 세 모델을 ONNX로 바꿔 **onnxruntime + OpenCV + numpy만으로** 돌립니다. PyTorch·Paddle·Ultralytics는 Pi에 필요 없습니다.

```
카메라 → ① 번호판 검출 (plate_*.onnx) → ② 줄 검출 (line_det.onnx) → 펴기 → ③ 인식 (ocr_v1.onnx) → 번호 + 글자별 확률
```

| 파일 | 하는 일 |
|---|---|
| `export_onnx.py` | **서버에서** 세 모델을 ONNX로 변환 → `models/` |
| `pi_reader.py` | **Pi에서** 사진·카메라로 번호 읽기, 속도 측정 (`ocr/plate_reader.py`와 같은 결과) |
| `check_onnx.py` | **서버에서** ONNX 버전과 서버 버전 결과 비교 |
| `requirements_pi.txt` | Pi에 설치할 패키지 |

## 1. 서버: ONNX 만들기

```bash
source ~/sooin/spasiba/venv/bin/activate
cd ~/sooin/spasiba/SPASIBA/deploy
python export_onnx.py      # → models/plate_640.onnx, plate_416.onnx, plate_320.onnx, line_det.onnx, ocr_v1.onnx, ocr_v1.json
python check_onnx.py       # ONNX 버전 확인 (선택)
```

## 2. Pi: 준비

64비트 Raspberry Pi OS가 필요합니다 (`uname -m` → `aarch64`).

```bash
git clone -b soogguang https://github.com/psubin05/SPASIBA.git && cd SPASIBA
python3 -m venv venv && source venv/bin/activate
pip install -r deploy/requirements_pi.txt
scp -r <서버>:~/sooin/spasiba/SPASIBA/deploy/models deploy/      # ONNX 파일은 저장소에 없으므로 서버에서 복사
```

## 3. Pi: 실행과 속도 측정

```bash
cd deploy
python pi_reader.py <사진 폴더>                          # 사진마다 읽은 번호
python pi_reader.py <사진 폴더> --bench --size 416        # 단계별 속도
python pi_reader.py --camera 0 --bench --frames 50        # 카메라 프레임으로 속도
```

`--size`는 검출 입력 크기(640 / 416 / 320), `--threads`는 CPU 스레드 수(Pi 4는 4)입니다.

## 4. 측정 결과

### 정확도 (서버, AI Hub test 번호 원본 500장, 사진 전체 → 번호)

| | 번호 전체 일치 |
|---|---|
| 서버 버전 (PyTorch + Paddle) | 93.4% |
| **ONNX 버전 (pi_reader, 640)** | **94.2%** |
| 두 버전 결과가 같음 / 줄 수가 같음 | 96.0% / 99.4% |

### 속도 (서버 CPU i5-13400 참고값, 웹 사진 21장)

| 입력 | 스레드 | ① 검출 | ② 줄 검출 | ③ 인식 | 사진 1장 | 찾은 번호판 |
|---|---|---|---|---|---|---|
| 640 | 4 | 38.5 ms | 17.4 ms | 7.7 ms | 69.8 ms | 26 |
| 416 | 4 | 15.1 ms | 13.5 ms | 5.7 ms | 36.8 ms | 24 |
| 320 | 4 | 8.2 ms | 12.8 ms | 5.0 ms | 26.8 ms | 22 |
| 640 | 1 | 70.7 ms | 23.6 ms | 7.6 ms | 109.6 ms | 26 |

- 입력을 줄이면 빨라지지만 **멀리 있는 작은 번호판부터 놓칩니다** (640: 26개 → 320: 22개). 가까운 주차장 카메라에서는 416도 충분할 가능성이 큽니다.
- ②③은 번호판 하나마다 한 번씩 돌기 때문에, 화면에 번호판이 많으면 그만큼 늘어납니다.
- **Pi 4 실측은 아직 없습니다.** Pi 4는 이 서버 CPU보다 훨씬 느리므로 위 표보다 몇 배 오래 걸립니다. `--bench`로 직접 재야 합니다.
