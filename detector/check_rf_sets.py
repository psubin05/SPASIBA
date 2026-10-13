"""Roboflow 번호판 데이터셋 5개 점검 (읽기 전용 — 원본 파일은 건드리지 않음)

  python check_rf_sets.py            # 통계 출력 + rf_check/ 에 샘플 그림 저장

1. 데이터셋별 통계: 장수, 해상도, 흑백 비율, 클래스별 박스 수·폭(px)·가로세로 비율, 이미지 전체를 덮는 박스
2. 중복: 데이터셋 안 거의 같은 사진(dHash), 데이터셋끼리 / 기존 roboflow_korea_plate / 테스트 21장과 겹치는 사진
3. 샘플 그림: 데이터셋마다 24장에 클래스별 색으로 박스 표시, alpr은 클래스별 crop 모음
"""
import random
from collections import Counter, defaultdict
from pathlib import Path
import cv2, numpy as np

random.seed(0)
DATA = Path(__file__).resolve().parents[2] / "data"
OUT = Path(__file__).resolve().parent / "rf_check"; OUT.mkdir(exist_ok=True)
SETS = ["rf_lp_detect", "rf_plate_night", "rf_alpr", "rf_car_with_plate", "rf_korean_license"]
EXTRA = {"roboflow_korea_plate": DATA / "roboflow_korea_plate", "test21": DATA / "image"}
COLORS = [(0, 0, 255), (0, 200, 0), (255, 0, 0), (0, 200, 255), (255, 0, 255), (255, 255, 0)]
DUP_TH = 3                                                         # dHash 해밍 거리 이하면 같은 사진으로 봄

def imread(p):
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)

def dhash(img):                                                    # 9x8로 줄여 가로 밝기 변화 64비트
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
    return np.packbits((g[:, 1:] > g[:, :-1]).flatten())

POP = np.array([bin(i).count("1") for i in range(256)], np.uint8)
def hamming(h, H):                                                 # h 하나와 H 전체의 해밍 거리
    return POP[np.bitwise_xor(H, h)].sum(1)

def read_labels(lp):
    boxes = []
    if lp.exists():
        for ln in lp.read_text().split("\n"):
            p = ln.split()
            if len(p) == 5:
                boxes.append((int(p[0]), *map(float, p[1:])))
            elif len(p) > 5:                                       # 다각형이면 감싸는 박스로
                xy = np.array(list(map(float, p[1:]))).reshape(-1, 2)
                (x1, y1), (x2, y2) = xy.min(0), xy.max(0)
                boxes.append((int(p[0]), (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1))
    return boxes

def load(root):
    items = []                                                     # (split, 이미지 경로, 박스들)
    for split in ("train", "valid", "test"):
        for ip in sorted((root / split / "images").glob("*")):
            items.append((split, ip, read_labels(root / split / "labels" / f"{ip.stem}.txt")))
    return items

def dup_groups(H):                                                 # 거리 DUP_TH 이하끼리 묶은 그룹 수
    parent = list(range(len(H)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(H)):
        for j in np.nonzero(hamming(H[i], H[i + 1:]) <= DUP_TH)[0] + i + 1:
            parent[find(j)] = find(i)
    return len({find(i) for i in range(len(H))})

def bins(vals, edges):
    c = Counter(np.digitize(vals, edges))
    labels = [f"<{edges[0]}"] + [f"{a}~{b}" for a, b in zip(edges, edges[1:])] + [f"≥{edges[-1]}"]
    return "  ".join(f"{l}:{c.get(i, 0)}" for i, l in enumerate(labels))

def tile(img, boxes, names, size=320):
    h, w = img.shape[:2]
    vis = img.copy()
    t = max(2, int(max(h, w) / 300))
    for c, cx, cy, bw, bh in boxes:
        x1, y1, x2, y2 = int((cx - bw / 2) * w), int((cy - bh / 2) * h), int((cx + bw / 2) * w), int((cy + bh / 2) * h)
        cv2.rectangle(vis, (x1, y1), (x2, y2), COLORS[c % len(COLORS)], t)
        cv2.putText(vis, str(c), (x1, max(15, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, t * 0.4, COLORS[c % len(COLORS)], t)
    s = size / max(h, w)
    vis = cv2.resize(vis, (int(w * s), int(h * s)))
    canvas = np.full((size, size, 3), 40, np.uint8)
    canvas[:vis.shape[0], :vis.shape[1]] = vis
    return canvas

def grid(tiles, cols):
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 40))
    return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])

hashes = {}                                                        # 출처 이름 → dHash 배열
for name in SETS:
    root = DATA / name
    names = [l.split(":", 1)[1].strip() for l in (root / "data.yaml").read_text().split("\n") if l.startswith("names:")]
    items = load(root)
    print(f"\n{'=' * 70}\n{name}  클래스 {names}")
    print(f"  장수: {len(items)}  분할 {dict(Counter(s for s, _, _ in items))}")
    sizes, gray, H = Counter(), 0, []
    per_cls = defaultdict(lambda: {"n": 0, "w": [], "ar": [], "full": 0})
    no_box = 0
    for _, ip, boxes in items:
        img = imread(ip)
        h, w = img.shape[:2]
        sizes[(w, h)] += 1
        b, g, r = cv2.split(img.astype(np.int16))
        gray += (np.abs(b - g).mean() < 2 and np.abs(g - r).mean() < 2)
        H.append(dhash(img))
        no_box += not boxes
        for c, cx, cy, bw, bh in boxes:
            d = per_cls[c]
            d["n"] += 1; d["w"].append(bw * w); d["ar"].append(bw * w / max(bh * h, 1e-6))
            d["full"] += (bw > 0.95 and bh > 0.95)
    hashes[name] = H = np.array(H)
    print(f"  해상도 상위: {sizes.most_common(3)}")
    print(f"  흑백 사진: {gray} ({gray / len(items):.0%})   박스 없는 사진: {no_box}")
    for c in sorted(per_cls):
        d = per_cls[c]
        print(f"  [클래스 {c}] 박스 {d['n']}개  사진당 {d['n'] / len(items):.2f}  이미지 전체 덮는 박스 {d['full']}")
        print(f"      폭(px)  {bins(d['w'], [20, 50, 100, 200])}")
        print(f"      가로/세로 {bins(d['ar'], [1.5, 2.5, 3.5, 6])}   (두 줄 ≈ 1.5~2.5, 한 줄 ≈ 3.5~6)")
    uniq = dup_groups(H)
    print(f"  거의 같은 사진 묶으면: {len(items)} → {uniq}장 (중복 {len(items) - uniq})")
    if name == "rf_alpr":                                          # 파일명 두 번째 칸 = 번호(한글 빠짐)
        plates = Counter(ip.name.split("_jpg.rf.")[0].split("_")[1] for _, ip, _ in items)
        print(f"  파일명 번호 종류: {len(plates)}개  (한 번호 최대 {plates.most_common(1)[0][1]}장)")

    pick = random.sample(items, min(24, len(items)))
    cv2.imwrite(str(OUT / f"{name}.jpg"), grid([tile(imread(ip), bx, names) for _, ip, bx in pick], 6))
    if name == "rf_alpr":                                          # 클래스별 crop 16개씩
        rows = []
        for c in sorted(per_cls):
            crops = []
            for _, ip, boxes in random.sample(items, len(items)):
                for bc, cx, cy, bw, bh in boxes:
                    if bc == c and len(crops) < 16:
                        img = imread(ip); h, w = img.shape[:2]
                        x1, y1 = max(0, int((cx - bw / 2) * w)), max(0, int((cy - bh / 2) * h))
                        x2, y2 = int((cx + bw / 2) * w), int((cy + bh / 2) * h)
                        cr = img[y1:y2, x1:x2]
                        if cr.size:
                            crops.append(cv2.resize(cr, (160, 80)))
                if len(crops) >= 16:
                    break
            row = np.hstack(crops + [np.full((80, 160, 3), 40, np.uint8)] * (16 - len(crops)))
            cv2.putText(row, f"class {c}", (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            rows.append(row)
        cv2.imwrite(str(OUT / "rf_alpr_class_crops.jpg"), np.vstack(rows))

for name, root in EXTRA.items():
    files = [p for p in root.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png") and "labels" not in p.parts]
    hashes[name] = np.array([dhash(imread(p)) for p in files])

print(f"\n{'=' * 70}\n출처끼리 겹치는 사진 수 (행 사진 중 열 출처에 거의 같은 사진이 있는 장수, dHash ≤ {DUP_TH})")
srcs = list(hashes)
print(" " * 22 + "".join(f"{s[3:16] if s.startswith('rf_') else s[:13]:>14}" for s in srcs))
for a in srcs:
    row = []
    for b in srcs:
        if a == b:
            row.append("-")
        else:
            row.append(str(sum((hamming(h, hashes[b]) <= DUP_TH).any() for h in hashes[a])))
    print(f"{a:>22}" + "".join(f"{v:>14}" for v in row))
print(f"\n샘플 그림 → {OUT}/")
