"""plate_v3 준비: AI Hub 두 줄·초록 번호판 1,000장 + 초록 평가 세트

  python make_plate_v3.py

1. test_green: data/green_plate의 X-AnyLabeling json → YOLO 라벨 (22번은 9번과 같은 사진이라 제외). 평가 전용
2. aihub_sel_1000: aihub_rare 후보에서 고르고 박스를 자동 생성
   - 제외: 시·군 이름이 들어간 번호(경기부천아0467 = 대부분 이륜차·건설기계, 결정 3)
   - 같은 번호는 1장
   - 박스: ft_rf_v1과 plate_v2의 확신도 1등 박스가 IoU ≥ IOU_TH로 일치할 때만 채택 (박스는 ft_rf_v1 것)
     crop 전체를 덮는 박스, 한쪽만 찾은 경우는 버리고 rejected.csv에 남김
   - 초록 후보는 채택된 것 전부, 나머지는 무작위로 채워 TOTAL장. 번호 단위로 10%는 val
3. plate_v3/data.yaml: plate_v2 + aihub_sel_1000 (폴더 목록만 묶음, 파일 복사 없음)
원본은 건드리지 않고, 만들 폴더가 이미 있으면 멈춘다.
"""
import csv, json, random, re, shutil, sys
from pathlib import Path
import cv2, numpy as np
from ultralytics import YOLO

random.seed(0)
DET = Path(__file__).resolve().parent
DATA = DET.parents[1] / "data"
RARE, GREEN_SRC = DATA / "aihub_rare", DATA / "green_plate"
SEL, TEST, V3 = DATA / "aihub_sel_1000", DATA / "test_green", DATA / "plate_v3"
ARCHIVE = DET.parents[1] / "archive/detector_20261013/runs/detect/runs"        # 지난 모델은 저장소 밖에 보관
FT_RF = ARCHIVE / "plate_ft_rf_v1/weights/best.pt"
V2 = ARCHIVE / "plate_v2/weights/best.pt"
TOTAL, VAL_RATIO, IOU_TH, CONF = 1000, 0.1, 0.7, 0.25
GREEN_SKIP = {"green_plate_22"}
STD = re.compile(r"^\d{2,3}[가-힣]\d{4}$")
REGION = re.compile(r"^[가-힣]{2}\d{1,2}[가-힣]\d{4}$")

for d in (SEL, TEST, V3):
    if d.exists():
        sys.exit(f"{d} 이 이미 있음 — 덮어쓰지 않고 멈춤")

def imread(p):
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)

def yolo_line(x1, y1, x2, y2, w, h):
    return f"0 {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)

# 1. test_green
(TEST / "images/test").mkdir(parents=True); (TEST / "labels/test").mkdir(parents=True)
n_box = 0
for jp in sorted(GREEN_SRC.glob("*.json")):
    if jp.stem in GREEN_SKIP:
        continue
    d = json.loads(jp.read_text(encoding="utf-8"))
    w, h = d["imageWidth"], d["imageHeight"]
    lines = []
    for s in d["shapes"]:
        xy = np.array(s["points"], dtype=float)
        (x1, y1), (x2, y2) = xy.min(0), xy.max(0)
        lines.append(yolo_line(max(0, x1), max(0, y1), min(w, x2), min(h, y2), w, h))
    img = GREEN_SRC / d["imagePath"]
    shutil.copy2(img, TEST / "images/test" / img.name)
    (TEST / "labels/test" / f"{img.stem}.txt").write_text("\n".join(lines) + "\n")
    n_box += len(lines)
(TEST / "data.yaml").write_text(f"path: {TEST}\ntrain: images/test\nval: images/test\nnames:\n  0: plate\n")
print(f"[test_green] {len(list((TEST / 'images/test').iterdir()))}장, 박스 {n_box}개")

# 2. aihub_sel_1000
rows, seen = [], set()
for r in csv.DictReader(open(RARE / "candidates.csv", encoding="utf-8")):
    v = r["value"]
    if not (STD.match(v) or REGION.match(v)) or v in seen:
        continue
    seen.add(v)
    rows.append(r)
print(f"[aihub] 후보 {len(rows)}장 (시·군 번호 제외, 번호당 1장)")

ft, v2 = YOLO(str(FT_RF)), YOLO(str(V2))
paths = [str(RARE / r["folder"] / r["file"]) for r in rows]
accepted, rejected = [], []
for i in range(0, len(paths), 64):
    rf = ft.predict(paths[i:i + 64], conf=CONF, verbose=False)
    rv = v2.predict(paths[i:i + 64], conf=CONF, verbose=False)
    for r, a, b in zip(rows[i:i + 64], rf, rv):
        h, w = a.orig_shape
        ba = a.boxes.xyxy[a.boxes.conf.argmax()].tolist() if len(a.boxes) else None
        bb = b.boxes.xyxy[b.boxes.conf.argmax()].tolist() if len(b.boxes) else None
        if ba is None or bb is None:
            reason = "ft_rf만" if ba else "plate_v2만" if bb else "둘 다 못 찾음"
        elif (ba[2] - ba[0]) * (ba[3] - ba[1]) > 0.95 * w * h:
            reason = "crop 전체"
        elif iou(ba, bb) < IOU_TH:
            reason = f"불일치 IoU {iou(ba, bb):.2f}"
        else:
            accepted.append((r, ba, w, h)); continue
        rejected.append((r, reason))

green = [x for x in accepted if "green" in x[0]["flags"]]
others = [x for x in accepted if "green" not in x[0]["flags"]]
picked = green + random.sample(others, max(0, min(len(others), TOTAL - len(green))))
random.shuffle(picked)
n_val = int(len(picked) * VAL_RATIO)
for s in ("train", "val"):
    (SEL / "images" / s).mkdir(parents=True); (SEL / "labels" / s).mkdir(parents=True)
with open(SEL / "selected.csv", "w", encoding="utf-8") as f:
    f.write("split,file,value,green,n_lines,x1,y1,x2,y2,original\n")
    for k, (r, (x1, y1, x2, y2), w, h) in enumerate(picked):
        s = "val" if k < n_val else "train"
        src = RARE / r["folder"] / r["file"]
        shutil.copy2(src, SEL / "images" / s / r["file"])
        (SEL / "labels" / s / f"{Path(r['file']).stem}.txt").write_text(yolo_line(x1, y1, x2, y2, w, h) + "\n")
        f.write(f"{s},{r['file']},{r['value']},{'green' in r['flags']},{r['n_lines']},"
                f"{x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f},{r['original']}\n")
with open(SEL / "rejected.csv", "w", encoding="utf-8") as f:
    f.write("file,value,flags,reason,original\n")
    for r, reason in rejected:
        f.write(f"{r['file']},{r['value']},{r['flags']},{reason},{r['original']}\n")
(SEL / "data.yaml").write_text(f"path: {SEL}\ntrain: images/train\nval: images/val\nnames:\n  0: plate\n")

reasons = {}
for _, reason in rejected:
    key = "불일치" if reason.startswith("불일치") else reason
    reasons[key] = reasons.get(key, 0) + 1
print(f"[aihub] 박스 채택 {len(accepted)}장 (초록 {len(green)}), 버림 {len(rejected)}장 {reasons}")
print(f"[aihub] 선택 {len(picked)}장 = 초록 {len(green)} + 나머지 {len(picked) - len(green)}  → train {len(picked) - n_val} / val {n_val}")

tiles = []                                                         # 검수 그림: 초록 32 + 나머지 32, 박스 빨강
for r, (x1, y1, x2, y2), w, h in green[:32] + [x for x in picked if x not in green][:32]:
    im = imread(RARE / r["folder"] / r["file"])
    cv2.rectangle(im, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), max(2, w // 150))
    tiles.append(cv2.resize(im, (240, 120)))
tiles += [np.full((120, 240, 3), 40, np.uint8)] * (-len(tiles) % 8)
cv2.imwrite(str(SEL / "preview_selected.jpg"), np.vstack([np.hstack(tiles[i:i + 8]) for i in range(0, len(tiles), 8)]))

# 3. plate_v3
V3.mkdir()
v2d = DATA / "plate_v2"
(V3 / "data.yaml").write_text(
    f"train:\n  - {v2d}/images/train\n  - {SEL}/images/train\n"
    f"val:\n  - {v2d}/images/val\n  - {SEL}/images/val\nnames:\n  0: plate\n")
print(f"[plate_v3] {V3}/data.yaml  (plate_v2 + aihub_sel_1000)")
