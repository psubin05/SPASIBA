# SPASIBA

## OCR 성능 측정

`data/`에 AI Hub 번호판 OCR 학습/검증 ZIP이 있는 상태에서 실행합니다. 검증 데이터 1만 장은 학습에 쓰지 않습니다.

```bash
python3 -m venv .venv
.venv/bin/pip install paddlepaddle paddleocr
PADDLE_PDX_CACHE_HOME=data/.paddlex PADDLE_PDX_MODEL_SOURCE=BOS .venv/bin/python ocr/evaluate.py --method recognition --limit 300 --output reports/recognition.jsonl
PADDLE_PDX_CACHE_HOME=data/.paddlex PADDLE_PDX_MODEL_SOURCE=BOS .venv/bin/python ocr/evaluate.py --method pipeline --postprocess --limit 300 --output reports/pipeline.jsonl
```

첫 실행 때 PaddleOCR 한국어 인식 모델과 줄 검출 모델을 다운로드합니다. `recognition`은 원래 OCR 이미지를 한 줄로 간주해 읽고, `pipeline`은 이미지 안의 글자 줄을 검출해 위에서 아래로 합칩니다. `--postprocess`는 주변 로고 등에서 나온 글자를 제거하고 번호판 형식에 맞는 부분만 남깁니다. 같은 seed를 쓰면 두 실행은 같은 표본을 사용합니다. 결과는 이미지별 JSONL과 `.summary.json`에 저장되며, 전체 번호판 일치율과 문자 오류율을 일반·지역명 번호판별로 보여줍니다. 전체 검증 데이터 측정은 `--limit 0`을 사용합니다.

300장 탐색 표본에서 줄 검출 방식의 완전 일치율은 40.3%였고, 후처리 규칙을 정한 뒤 탐색 표본과 겹치지 않는 294장에서 40.1%에서 51.7%로 올랐습니다. 이는 학습 없이 수행한 OCR 개선이며 전체 검증셋이나 실제 주차장 영상의 성능을 뜻하지 않습니다.

현재 OCR 원천 이미지는 번호판에 차체와 배경이 함께 들어 있을 수 있습니다. 검출기에서 번호판만 자른 뒤의 OCR 성능과는 구별해서 해석해야 합니다. 두 줄 번호판의 정답에는 줄 정보가 없어, 이 평가에서는 두 줄만의 정확도를 따로 산출하지 않습니다.

## 웹캠에서 확인

```bash
.venv/bin/python ocr/webcam_demo.py
```

노트북 VS Code에서 **Remote SSH로 이미 서버에 연결한 경우**, VS Code의 **포트(Ports)** 보기에서 **포트 전달(Forward a Port)**을 눌러 서버 포트 `8765`를 입력합니다. VS Code가 표시하는 로컬 주소를 **노트북 브라우저**에서 엽니다. 대개 `http://localhost:8765`이지만 다른 로컬 포트를 배정할 수도 있습니다. VS Code의 원격 터미널은 서버에서 실행되므로 그 안에서 `ssh -L` 명령을 다시 실행하지 않습니다.

브라우저에서 **카메라 시작**을 누르면 노트북 웹캠을 사용하고, 초록색 상자 안의 영상만 서버 OCR로 보냅니다. 카메라 권한을 허용한 뒤에는 **카메라** 목록에서 다른 웹캠으로 바꿀 수 있습니다. `localhost` 주소로 열어야 브라우저에서 웹캠 권한을 사용할 수 있습니다. **중지**를 누르면 브라우저의 카메라 스트림을 닫습니다. 이 데모는 상자 안의 영상을 OCR로 읽는 용도이며, 차량 전체에서 번호판 위치를 찾는 검출기는 아직 연결하지 않았습니다.
