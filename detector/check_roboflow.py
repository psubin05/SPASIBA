import random, sys
from collections import Counter
from pathlib import Path
import cv2, numpy as np

random.seed(0)
root = Path(sys.argv[1] if len(sys.argv) > 1 else "../../data/roboflow_korea_plate")
items = []
for split in ("train", "valid", "test"):
    for ip in sorted((root / split / "images").glob("*")):
        lp = root / split / "labels" / f"{ip.stem}.txt"
        boxes = []
        if lp.exists():
            for ln in lp.read_text().split("\n"):
                p = ln.split()
                if len(p) == 5:                                    # 일반 박스 (class cx cy w h)
                    boxes.append(tuple(map(float, p[1:])))
                elif len(p) > 5:                                   # 다각형이면 감싸는 박스로
                    xy = np.array(list(map(float, p[1:]))).reshape(-1, 2)
                    (x1, y1), (x2, y2) = xy.min(0), xy.max(0)
                    boxes.append(((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1))
        items.append((split, ip, boxes))

sizes, areas, ratios = Counter(), [], []
for _, ip, boxes in items:
    h, w = cv2.imread(str(ip)).shape[:2]
    sizes[(w, h)] += 1
    for cx, cy, bw, bh in boxes:
        areas.append(bw * bh)                                      # 이미지 대비 박스 면적
        ratios.append((bw * w) / max(bh * h, 1e-6))                # 실제 픽셀 기준 가로/세로

q = lambda v, k: sorted(v)[int(len(v) * k)]
print(f"전체 {len(items)}장 / split별:", dict(Counter(s for s, _, _ in items)))
print("이미지당 박스 수:", dict(sorted(Counter(len(b) for _, _, b in items).items())))
print("이미지 크기 상위 5개:", sizes.most_common(5))
print(f"박스 면적 비율 10/50/90%: {q(areas,.1):.2f} / {q(areas,.5):.2f} / {q(areas,.9):.2f}")
print(f"박스 가로/세로 10/50/90%: {q(ratios,.1):.2f} / {q(ratios,.5):.2f} / {q(ratios,.9):.2f}")

tiles = []
for split, ip, boxes in random.sample(items, min(32, len(items))):
    im = cv2.imread(str(ip)); h, w = im.shape[:2]
    for cx, cy, bw, bh in boxes:
        cv2.rectangle(im, (int((cx - bw / 2) * w), int((cy - bh / 2) * h)),
                      (int((cx + bw / 2) * w), int((cy + bh / 2) * h)), (0, 0, 255), 2)
    if not boxes:
        cv2.putText(im, "NO BOX", (3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    tiles.append(cv2.resize(im, (240, 120)))
tiles += [np.full((120, 240, 3), 255, np.uint8)] * (-len(tiles) % 4)
cv2.imwrite("roboflow_check.png", np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]))
print("→ roboflow_check.png 저장")
