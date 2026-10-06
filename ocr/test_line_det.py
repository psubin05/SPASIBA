import json, re, random, sys
from collections import Counter, defaultdict
from pathlib import Path
import cv2, numpy as np
from paddleocr import TextDetection

random.seed(0)
data = Path(sys.argv[1] if len(sys.argv) > 1 else "../../data")
model_name = sys.argv[2] if len(sys.argv) > 2 else "PP-OCRv5_mobile_det"
std    = re.compile(r"^\d{2,3}[가-힣]\d{4}$")
region = re.compile(r"^[가-힣]{2}\d{1,2}[가-힣]\d{4}$")

imgs = {p.name: p for p in data.rglob("*.jpg")}
groups = defaultdict(list)
for p in data.rglob("*.json"):
    if "라벨링데이터" not in str(p):
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    v = d["value"].replace(" ", "")
    k = "normal" if std.match(v) else "region" if region.match(v) else "etc"
    if d["imagePath"] in imgs:
        groups[k].append((imgs[d["imagePath"]], v))
sample = []
for k, n in (("normal", 300), ("region", 300), ("etc", 100)):
    sample += [(k, *x) for x in random.sample(groups[k], min(n, len(groups[k])))]

model = TextDetection(model_name=model_name, enable_mkldnn=False)

def merge_same_line(boxes):
    """세로 중심이 비슷하고 좌우로 붙어 있는 박스를 하나로 합치기"""
    boxes = sorted(boxes, key=lambda b: b[0])
    merged = []
    for b in boxes:
        for i, m in enumerate(merged):
            cy_b, cy_m = (b[1] + b[3]) / 2, (m[1] + m[3]) / 2
            h = max(b[3] - b[1], m[3] - m[1])
            gap = b[0] - m[2]
            if abs(cy_b - cy_m) < 0.3 * h and gap < 0.5 * h:
                merged[i] = (min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3]))
                break
        else:
            merged.append(b)
    return merged

def clean_boxes(boxes):
    """같은 줄 합치기 → 가장 큰 박스 기준으로 로고/작은 글씨 제거"""
    boxes = merge_same_line(boxes)
    if not boxes:
        return []
    main = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    mw, mh = main[2] - main[0], main[3] - main[1]
    keep = []
    for b in boxes:
        if b is main:
            keep.append(b); continue
        w, h = b[2] - b[0], b[3] - b[1]
        x_overlap = min(b[2], main[2]) - max(b[0], main[0])
        v_gap = max(main[1] - b[3], b[1] - main[3], 0)
        if w >= 0.4 * mw and h >= 0.3 * mh and x_overlap > 0.5 * w and v_gap < 0.5 * mh:
            keep.append(b)
    return keep

def count_lines(boxes):
    """박스 중심 높이 차이로 줄 구분"""
    lines = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        cy, h = (b[1] + b[3]) / 2, b[3] - b[1]
        for ln in lines:
            if abs(cy - ln["cy"]) < 0.3 * max(h, ln["h"]):
                ln["boxes"].append(b)
                break
        else:
            lines.append({"cy": cy, "h": h, "boxes": [b]})
    return lines

stat = defaultdict(Counter)
vis = defaultdict(list)
for kind, path, v in sample:
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    scale = 320 / img.shape[1]
    img = cv2.resize(img, (320, max(32, int(img.shape[0] * scale))))
    res = next(iter(model.predict(img, batch_size=1)))
    raw = []
    for poly in res["dt_polys"]:
        poly = np.array(poly, dtype=np.float32)
        x1, y1 = poly.min(0); x2, y2 = poly.max(0)
        if (x2 - x1) * (y2 - y1) > 0.01 * img.shape[0] * img.shape[1]:
            raw.append((float(x1), float(y1), float(x2), float(y2)))
    boxes = clean_boxes(raw)
    n = len(count_lines(boxes))
    stat[kind][f"{n}줄"] += 1
    for b in raw:                                   # 버린 박스는 회색
        cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (160, 160, 160), 1)
    for b in boxes:                                 # 남은 박스는 빨강
        cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 0, 255), 2)
    cv2.putText(img, f"{n}L", (3, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
    key = f"{kind}_2L" if kind == "normal" and n >= 2 else kind
    if len(vis[key]) < 32:
        vis[key].append(cv2.resize(img, (200, 100)))

print(f"모델: {model_name}")
for kind, c in stat.items():
    total = sum(c.values())
    print(f"[{kind}] " + ", ".join(f"{k}: {m}장 ({m/total*100:.0f}%)" for k, m in sorted(c.items())))
for key, ims in vis.items():
    ims += [np.full((100, 200, 3), 255, np.uint8)] * (-len(ims) % 8)
    cv2.imwrite(f"linedet_{key}.png", np.vstack([np.hstack(ims[i:i+8]) for i in range(0, len(ims), 8)]))
print("→ linedet_*.png 저장 (빨강 = 사용한 박스, 회색 = 잡음으로 버린 박스)")
