import sys
from pathlib import Path
import cv2, numpy as np
from ultralytics import YOLO

src = Path(sys.argv[1] if len(sys.argv) > 1 else "../../data/image")
mode = sys.argv[2] if len(sys.argv) > 2 else "two_stage"           # two_stage 또는 direct
plate_w = sys.argv[3] if len(sys.argv) > 3 else "weights/plate_v3.pt"
out = Path(f"real_test_out_{mode}"); out.mkdir(exist_ok=True)
plate_model = YOLO(plate_w)
car_model = YOLO("yolo11n.pt") if mode == "two_stage" else None     # COCO: 2=car, 5=bus, 7=truck
MARGIN = 0.05

def draw_plate(vis, r, ox, oy):                                     # conf 0.25 이상 번호판을 전부 그림
    global n_plates
    for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.cpu().numpy().astype(int), r.boxes.conf.cpu().numpy()):
        cv2.rectangle(vis, (ox + x1, oy + y1), (ox + x2, oy + y2), (0, 0, 255), 3)      # 빨강 = 번호판
        cv2.putText(vis, f"{c:.2f}", (ox + x1, max(20, oy + y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    n_plates += len(r.boxes)
    return len(r.boxes) > 0

found = total = n_plates = 0
for ip in sorted(p for p in src.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")):
    img = cv2.imdecode(np.fromfile(str(ip), np.uint8), cv2.IMREAD_COLOR)
    H, W = img.shape[:2]
    vis = img.copy()
    if mode == "direct":
        total += 1
        found += draw_plate(vis, plate_model.predict(img, conf=0.25, verbose=False)[0], 0, 0)
    else:
        cars = car_model.predict(img, classes=[2, 5, 7], conf=0.3, verbose=False)[0].boxes.xyxy.cpu().numpy()
        if len(cars) == 0:
            cv2.putText(vis, "NO CAR", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 0, 0), 3)
        for x1, y1, x2, y2 in cars:
            mw, mh = (x2 - x1) * MARGIN, (y2 - y1) * MARGIN
            cx1, cy1 = int(max(0, x1 - mw)), int(max(0, y1 - mh))
            cx2, cy2 = int(min(W, x2 + mw)), int(min(H, y2 + mh))
            total += 1
            cv2.rectangle(vis, (cx1, cy1), (cx2, cy2), (255, 0, 0), 2)                 # 파랑 = 차
            r = plate_model.predict(img[cy1:cy2, cx1:cx2], conf=0.25, verbose=False)[0]
            found += draw_plate(vis, r, cx1, cy1)
    s = min(1.0, 1280 / max(H, W))
    cv2.imwrite(str(out / f"{ip.stem}.jpg"), cv2.resize(vis, None, fx=s, fy=s))
print(f"[{mode}] 대상 {total}개 중 번호판을 찾은 것: {found}개 (그린 번호판 박스 총 {n_plates}개)")
print(f"→ {out}/ 에 저장 (파랑 = 차, 빨강 = 번호판)")
