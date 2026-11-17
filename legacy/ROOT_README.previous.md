# SPASIBA

## 번호판 검출·OCR

번호판 검출, 한 줄/두 줄 분리, CTC OCR 학습 및 웹캠 데모는 [`detector/`](detector/)에 있습니다.

```bash
cd detector
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python verify_bundle.py --full
python src/webcam_plate_demo.py --camera 0
```

설치, 데이터 준비, 추가 학습 방법은 [`detector/README.md`](detector/README.md)를 확인하세요.
