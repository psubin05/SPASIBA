"""일 1(실제 시스템)용 번호판 검출 학습 데이터셋 plate_v2 만들기

  python make_plate_v2.py            # → ~/sooin/spasiba/data/plate_v2/

구성 (모두 '선명한 번호판 + 차 맥락', 클래스는 plate 하나)
  rf_alpr           번호판(클래스 2)만 남김. 차(0)·얼굴(1) 박스는 버림
  rf_plate_night    전부
  rf_korean_license 전부
  rf_lp_detect      192x144 저해상도라 거의 같은 사진은 하나만 남기고 LP_DETECT_MAX장까지
블러 데이터(yolo_plate)와 rf_car_with_plate(물체 crop + 모자이크)는 쓰지 않는다.

검증 10%는 같은 차가 학습/검증에 갈라지지 않게 묶어서 나눈다.
  rf_alpr: 파일명 번호(한글 빠짐) 단위 / 나머지: dHash로 거의 같은 사진끼리 묶은 단위
원본은 건드리지 않는다. 이미지는 심볼릭 링크, 라벨은 새로 쓴다. plate_v2가 이미 있으면 멈춘다.
"""
import random, sys
from collections import Counter, defaultdict
from pathlib import Path
import cv2, numpy as np

random.seed(0)
DATA = Path(__file__).resolve().parents[2] / "data"
OUT = DATA / "plate_v2"
SOURCES = {"rf_alpr": 2, "rf_plate_night": 0, "rf_korean_license": 0, "rf_lp_detect": 0}  # 폴더: 번호판 클래스
LP_DETECT_MAX = 2000
VAL_RATIO = 0.1
DUP_TH = 3

if OUT.exists():
    sys.exit(f"{OUT} 이 이미 있음 — 덮어쓰지 않고 멈춤")

POP = np.array([bin(i).count("1") for i in range(256)], np.uint8)
def dhash(p):
    img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_GRAYSCALE)
    g = cv2.resize(img, (9, 8), interpolation=cv2.INTER_AREA)
    return np.packbits((g[:, 1:] > g[:, :-1]).flatten())

def dup_groups(paths):                                             # 거의 같은 사진끼리 같은 그룹 번호
    H = np.array([dhash(p) for p in paths])
    parent = list(range(len(H)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(H)):
        for j in np.nonzero(POP[np.bitwise_xor(H[i + 1:], H[i])].sum(1) <= DUP_TH)[0] + i + 1:
            parent[find(j)] = find(i)
    return [find(i) for i in range(len(H))]

def plate_boxes(lp, cls):
    out = []
    for ln in lp.read_text().split("\n") if lp.exists() else []:
        p = ln.split()
        if len(p) < 5 or int(p[0]) != cls:
            continue
        if len(p) == 5:
            cx, cy, w, h = map(float, p[1:])
        else:                                                      # 다각형이면 감싸는 박스로
            xy = np.array(list(map(float, p[1:]))).reshape(-1, 2)
            (x1, y1), (x2, y2) = xy.min(0), xy.max(0)
            cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
        out.append(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return out

rows = []                                                          # (출처, 그룹, 이미지 경로, 라벨 줄들)
for src, cls in SOURCES.items():
    items = []
    for split in ("train", "valid", "test"):
        for ip in sorted((DATA / src / split / "images").glob("*")):
            items.append((ip, plate_boxes(DATA / src / split / "labels" / f"{ip.stem}.txt", cls)))
    if src == "rf_alpr":
        groups = [ip.name.split("_jpg.rf.")[0].split("_")[1] for ip, _ in items]
    else:
        groups = dup_groups([ip for ip, _ in items])
    if src == "rf_lp_detect":                                      # 그룹마다 1장 → 최대 LP_DETECT_MAX장
        first = {}
        for (ip, lb), g in zip(items, groups):
            first.setdefault(g, (ip, lb, g))
        picked = random.sample(list(first.values()), min(LP_DETECT_MAX, len(first)))
        items, groups = [(ip, lb) for ip, lb, _ in picked], [g for _, _, g in picked]
    print(f"{src}: {len(items)}장, 그룹 {len(set(groups))}개, 번호판 {sum(len(lb) for _, lb in items)}개, "
          f"번호판 없는 사진 {sum(not lb for _, lb in items)}장")
    rows += [(src, f"{src}:{g}", ip, lb) for (ip, lb), g in zip(items, groups)]

all_groups = sorted({g for _, g, _, _ in rows})
random.shuffle(all_groups)
val_groups = set(all_groups[:int(len(all_groups) * VAL_RATIO)])

count = defaultdict(Counter)
for split in ("train", "val"):
    (OUT / "images" / split).mkdir(parents=True)
    (OUT / "labels" / split).mkdir(parents=True)
with open(OUT / "sources.csv", "w") as f:
    f.write("split,source,group,new_name,original\n")
    for i, (src, g, ip, lb) in enumerate(rows):
        split = "val" if g in val_groups else "train"
        name = f"{src[3:]}_{i:05d}{ip.suffix.lower()}"
        (OUT / "images" / split / name).symlink_to(ip)
        (OUT / "labels" / split / f"{Path(name).stem}.txt").write_text("\n".join(lb) + ("\n" if lb else ""))
        f.write(f"{split},{src},{g},{name},{ip}\n")
        count[split][src] += 1

(OUT / "data.yaml").write_text(f"path: {OUT}\ntrain: images/train\nval: images/val\nnames:\n  0: plate\n")
print(f"\n{'출처':<20}{'train':>8}{'val':>8}")
for src in SOURCES:
    print(f"{src:<20}{count['train'][src]:>8}{count['val'][src]:>8}")
print(f"{'합계':<20}{sum(count['train'].values()):>8}{sum(count['val'].values()):>8}")
print(f"\n→ {OUT}/data.yaml  (출처 대조표: sources.csv)")
