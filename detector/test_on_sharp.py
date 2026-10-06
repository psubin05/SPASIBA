import json, re, random, sys
from collections import defaultdict
from pathlib import Path
import cv2, numpy as np
from ultralytics import YOLO

random.seed(0)
data = Path(sys.argv[1] if len(sys.argv) > 1 else "../../data")
weights = sys.argv[2] if len(sys.argv) > 2 else "runs/detect/runs/plate_blur_v1/weights/best.pt"
std    = re.compile(r"^\d{2,3}[가-힣]\d{4}$")
region = re.compile(r"^[가-힣]{2}\d{1,2}[가-힣]\d{4}$")

imgs = {p.name: p for p in data.rglob("*.jpg") if "원본이미지" not in str(p) and "yolo_plate" not in str(p)}
groups = defaultdict(list)
for p in data.rglob("*.json"):
    if "라벨링데이터" not in str(p) or "원본이미지" in str(p):
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    v = d["value"].replace(" ", "")
    k = "normal" if std.match(v) else "region" if region.match(v) else None
    if k and d["imagePath"] in imgs:
        groups[k].append(imgs[d["imagePath"]])
sample = random.sample(groups["normal"], 24) + random.sample(groups["region"], 24)

model = YOLO(weights)
found, tiles = 0, []
for path in sample:
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    r = model.predict(img, conf=0.25, verbose=False)[0]
    if len(r.boxes):
        found += 1
    for b, c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()):
        x1, y1, x2, y2 = map(int, b)
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(img, f"{c:.2f}", (x1, max(14, y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
    if not len(r.boxes):
        cv2.putText(img, "MISS", (3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    tiles.append(cv2.resize(img, (240, 120)))
print(f"번호판을 하나라도 찾은 이미지: {found}/{len(sample)}")
cv2.imwrite("sharp_test.png", np.vstack([np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]))
print("→ sharp_test.png 저장 (빨간 박스 = 예측, 숫자 = 확신도, MISS = 못 찾음)")
