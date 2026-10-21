# Hybrid Subin ALPR: Raspberry Pi 설치 및 실행

이 문서는 `heewoo/plate_ocr` 브랜치의 `hybrid_subin`을 Raspberry Pi CSI
카메라로 실행하기 위한 전체 과정입니다.

## 이 폴더는 무엇인가요?

`hybrid_subin`은 Soogguang의 `plate_v3` 번호판 검출 모델과 Subin의
PaddleOCR 인식 방식을 합친 한국 자동차 번호판 인식 모듈입니다.

```text
Raspberry Pi Camera
  -> plate_v3 (YOLO11n) 번호판 검출
  -> 번호판 crop 및 작은 crop 확대
  -> PP-OCRv5 mobile 글자 영역 검출
  -> korean_PP-OCRv5 mobile 문자 인식
  -> 한국 번호판 형식 검사
  -> 번호판 트랙별 시간 투표
```

주요 파일은 다음과 같습니다.

```text
hybrid_subin/
├── src/                       # 이미지, USB 웹캠, Pi Camera 실행 코드
├── models/detector/           # Git LFS로 관리되는 plate_v3.pt
├── tests/                     # 후처리·추적·NMS 테스트
├── requirements_pi.txt        # Raspberry Pi용 Python 의존성
├── run_webcam.sh              # USB 웹캠 실행
└── run_pi_camera.sh           # Raspberry Pi CSI 카메라 실행
```

PaddleOCR 모델은 저장소에 넣지 않으며 최초 실행 때 `models/paddlex/`로
자동 다운로드됩니다.

## 권장 환경

- 64비트 Raspberry Pi OS
- `uname -m` 결과가 `aarch64`
- Raspberry Pi CSI Camera
- 패키지와 모델을 받을 수 있는 인터넷 연결
- 설치에 충분한 저장 공간

Pi 4B에서는 PaddleOCR와 PyTorch YOLO가 무거워 실시간 속도가 나오지 않을 수
있습니다. 먼저 기본 설정으로 기능을 확인하세요.

## 1. GitHub에서 처음 내려받기

라즈베리파이 터미널에서 실행합니다.

```bash
cd ~
sudo apt update
sudo apt install -y git git-lfs

git lfs install
git clone --branch heewoo/plate_ocr --single-branch \
  https://github.com/psubin05/SPASIBA.git

cd ~/SPASIBA
git lfs pull
```

이미 `~/SPASIBA`를 clone했다면 새로 clone하지 말고 다음처럼 받습니다. 추적
중인 파일을 수정한 상태라면 먼저 커밋하거나 stash해야 합니다.

```bash
cd ~/SPASIBA
git status
git fetch origin
git switch heewoo/plate_ocr
git pull --ff-only
git lfs install
git lfs pull
```

## 2. Git LFS 모델 확인

```bash
cd ~/SPASIBA/hybrid_subin

ls -lh models/detector/plate_v3.pt
file models/detector/plate_v3.pt
head -c 120 models/detector/plate_v3.pt
```

파일 앞부분에 `version https://git-lfs.github.com/spec/v1`이 보이거나 파일이
매우 작으면 실제 모델 대신 Git LFS 포인터만 받은 상태입니다.

```bash
cd ~/SPASIBA
git lfs install
git lfs pull
ls -lh hybrid_subin/models/detector/plate_v3.pt
```

## 3. 시스템 패키지와 카메라 준비

```bash
sudo apt update
sudo apt install -y python3-venv python3-picamera2 python3-opencv git-lfs

rpicam-hello --list-cameras
rpicam-hello -t 3000
```

두 번째 명령에서 약 3초 동안 미리보기가 나오면 카메라 연결이 정상입니다.

## 4. 저장 공간과 임시 디렉터리 준비

PyTorch와 PaddlePaddle 설치에는 넉넉한 임시 공간이 필요합니다.

```bash
df -h
mkdir -p ~/pip_tmp
export TMPDIR=~/pip_tmp
python3 -m pip cache purge
```

`No space left on device`가 발생하면 공간을 확보한 후 같은 터미널에서
`TMPDIR`을 다시 설정하고 설치를 재시도하세요. `export` 설정은 새 터미널을
열면 사라집니다.

## 5. 가상환경 생성

`Picamera2`와 OpenCV는 Raspberry Pi OS 시스템 패키지를 사용하므로 반드시
`--system-site-packages` 옵션을 붙입니다. `.venv`는 Git에 올라가지 않으므로
clone 후 라즈베리파이에서 직접 한 번 만들어야 합니다.

```bash
cd ~/SPASIBA/hybrid_subin

python3 -m venv --system-site-packages .venv
source .venv/bin/activate

python --version
uname -m
python -m pip install --upgrade pip
```

프롬프트 앞에 `(.venv)`가 보이면 활성화된 상태입니다.

## 6. CPU 전용 Python 패키지 설치

일반 PyTorch 패키지를 설치할 때 대용량 CUDA 패키지가 선택될 수 있으므로
Raspberry Pi에서는 CPU 전용 인덱스를 사용합니다. 아래 버전은 실제 설치에
사용한 조합입니다.

```bash
cd ~/SPASIBA/hybrid_subin
source .venv/bin/activate

mkdir -p ~/pip_tmp
export TMPDIR=~/pip_tmp

python -m pip install torch==2.13.0 torchvision==0.28.0 \
  --index-url https://download.pytorch.org/whl/cpu

python -m pip install paddlepaddle==3.3.1 \
  -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

python -m pip install -r requirements_pi.txt
```

`requirements_pi.txt`는 다음 항목을 설치합니다.

```text
paddleocr>=3.3,<4
ultralytics>=8.4,<9
numpy>=1.26,<3
Pillow>=10,<13
```

## 7. 전체 패키지 확인

```bash
python -c "import torch; print(torch.__version__); print('CUDA:', torch.cuda.is_available())"
python -c "from ultralytics import YOLO; print('YOLO OK')"
python -c "from paddleocr import PaddleOCR, TextRecognition; print('PaddleOCR OK')"
python -c "import paddle; print(paddle.__version__); paddle.utils.run_check()"

python -m pip show torch torchvision ultralytics paddleocr paddlepaddle
```

CPU 전용 Raspberry Pi에서는 `torch.cuda.is_available()` 결과가 `False`인 것이
정상입니다.

## 8. Raspberry Pi Camera 실행

### 데스크톱에서 화면 표시

```bash
cd ~/SPASIBA/hybrid_subin
source .venv/bin/activate

bash run_pi_camera.sh \
  --width 1920 --height 1080 --fps 15 \
  --det-size 640 --process-every 10 --min-votes 2 \
  --display
```

- `q` 또는 `ESC`: 종료
- `s`: 표시 중인 결과 프레임 저장

### SSH 또는 모니터 없는 환경

`--display`를 빼면 창 없이 터미널에 결과를 출력합니다.

```bash
cd ~/SPASIBA/hybrid_subin
source .venv/bin/activate

bash run_pi_camera.sh \
  --width 1920 --height 1080 --fps 15 \
  --det-size 640 --process-every 10 --min-votes 2
```

`Ctrl+C`로 종료합니다. 먼 번호판에는 `--tile-detect`를 추가할 수 있지만 Pi
4B에서는 매우 느릴 수 있습니다. `--robust` 역시 CPU 사용량을 크게 늘립니다.

## 9. 다음 부팅부터 실행

가상환경과 패키지는 다시 만들 필요가 없습니다.

```bash
cd ~/SPASIBA/hybrid_subin
source .venv/bin/activate
bash run_pi_camera.sh --display
```

필요하면 위의 1920x1080 실행 옵션을 그대로 붙입니다.

## 10. 설치 버전 저장

```bash
cd ~/SPASIBA/hybrid_subin
source .venv/bin/activate
mkdir -p outputs
python -m pip freeze > outputs/requirements_pi_frozen.txt
```

`outputs/requirements_pi_frozen.txt`는 해당 라즈베리파이의 설치 기록입니다.
`outputs/`는 Git에서 제외되므로 의존성 고정 파일로 채택하려면 충분히 검증한
후 별도 파일로 명시적으로 추가해야 합니다.

## 문제 해결

### `.venv/bin/activate: No such file or directory`

`.venv`는 clone되지 않습니다. 다음 명령으로 한 번 생성합니다.

```bash
cd ~/SPASIBA/hybrid_subin
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
```

### `No module named 'ultralytics'`

```bash
source ~/SPASIBA/hybrid_subin/.venv/bin/activate
python -m pip install "ultralytics>=8.4,<9"
```

### `No module named 'paddleocr'`

```bash
source ~/SPASIBA/hybrid_subin/.venv/bin/activate
python -m pip install "paddleocr>=3.3,<4"
```

### `plate_v3.pt invalid load key 'v'`

Git LFS 포인터 파일을 모델로 열었을 때 발생할 수 있습니다.

```bash
cd ~/SPASIBA
git lfs install
git lfs pull
```

### `No space left on device`

```bash
df -h
mkdir -p ~/pip_tmp
export TMPDIR=~/pip_tmp
python -m pip cache purge
```

공간을 확보한 뒤 실패한 설치 명령을 다시 실행합니다.

### 카메라가 보이지 않음

```bash
rpicam-hello --list-cameras
rpicam-hello -t 3000
```

여기에서도 카메라가 보이지 않으면 Python 코드보다 먼저 케이블 방향, CSI
커넥터, 카메라 활성화 상태와 Raspberry Pi OS 상태를 확인하세요.

## 개발자용: README 변경만 기존 브랜치에 올리기

아래처럼 파일 경로를 직접 지정해서 stage하면 README 두 파일만 커밋됩니다.
다른 로컬 변경사항이 함께 들어가지 않도록 `git add .`는 사용하지 않습니다.

```bash
cd ~/SPASIBA
git switch heewoo/plate_ocr
git status

git add hybrid_subin/README.md hybrid_subin/RASPBERRY_PI.md

git diff --cached --name-only
git diff --cached

git commit -m "Document Raspberry Pi hybrid ALPR setup"
git push origin heewoo/plate_ocr
```

`git diff --cached --name-only` 결과에 위 README 두 파일만 보여야 합니다.
