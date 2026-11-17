# 통합 작업 보고

## 구성

- 전체 흐름·검출·웹캠: soogguang `plate_v3` 방식
- OCR: subin `PP-OCRv5_mobile_det + korean_PP-OCRv5_mobile_rec`
- 추가: 그림자/빛번짐 전처리 후보, 한국 번호판 형식 필터, IoU 트랙별 투표
- Raspberry Pi Camera: `Picamera2` 기반 CSI 카메라 입력, headless/화면 표시 실행 지원

## 기존 파일 변경

없음. 모든 코드는 `SPASIBA_hybrid_subin_ocr/`에 새로 작성했다.

## 검증 상태

- 전체 Python 문법 검사: 통과
- 핵심 단위 테스트: 3/3 통과
- PaddleOCR detection/recognition 모델 초기화 및 로컬 캐시: 성공
- 합성 두 줄 `부산43자7634`: pipeline으로 정확히 인식, confidence 0.999
- 합성 한 줄 `423너4350`: recognition fallback으로 정확히 인식, confidence 0.960
- Roboflow `01조0261`: plate_v3 검출 confidence 0.800, 최종 OCR 정확히 인식 confidence 0.857
- 웹캠 `/dev/video0`: plate_v3와 두 PaddleOCR 모델 로딩, 960px 2프레임 headless 처리 정상 종료
- 먼 번호판 개선: OCR crop을 최소 640px 너비/128px 높이로 adaptive 확대, robust unsharp 후보, 1080p/MJPG 요청, crop 원본 크기 로그 추가
- 현재 `/dev/video0` 실측: MJPG로 1920x1080을 요청해도 실제 캡처는 1280x720. 따라서 현 카메라에서는 먼 번호판의 원본 픽셀 부족이 남는다.

실제로 실행하지 않은 항목은 성공으로 기록하지 않는다.
