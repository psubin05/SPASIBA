import json, sys, zlib, random
from collections import defaultdict, Counter
from multiprocessing import Pool
from pathlib import Path
import cv2, numpy as np

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "../../data").resolve()
BASE = ROOT / "103.자동차_차종-연식-번호판_인식용_데이터/추가_데이터_보완_건_220114(원본이미지추가개방)/원본이미지(추가개방)"
OUT = ROOT / "yolo_plate"
MARGIN, MIN_PLATE_W, MAX_SIDE, VAL_MOD = 0.15, 20, 640, 10   # VAL_MOD=10 → 검증 약 10%

def to_box(b):
    (ax, ay), (bx, by) = b
    return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)

def work(task):
    img_path, labels, split = task
    img = cv2.imdecode(np.fromfile(str(img_path), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return []
    H, W = img.shape[:2]
    plates = [to_box(d["plate"]["bbox"]) for d in labels if (d.get("plate") or {}).get("bbox")]
    results = []
    for k, d in enumerate(labels):
        pb = (d.get("plate") or {}).get("bbox")
        if not pb:
            continue
        px1, py1, px2, py2 = to_box(pb)
        if px2 - px1 < MIN_PLATE_W:
            continue
        cx1, cy1, cx2, cy2 = to_box(d["car"]["bbox"])
        mw, mh = (cx2 - cx1) * MARGIN, (cy2 - cy1) * MARGIN
        x1, y1 = max(0, int(cx1 - mw)), max(0, int(cy1 - mh))
        x2, y2 = min(W, int(cx2 + mw)), min(H, int(cy2 + mh))
        cw, ch = x2 - x1, y2 - y1
        if cw < 32 or ch < 32:
            continue
        lines = []
        for a, b, c, e in plates:                      # crop 안에 60% 이상 들어온 번호판만
            ix1, iy1, ix2, iy2 = max(a, x1), max(b, y1), min(c, x2), min(e, y2)
            if ix2 <= ix1 or iy2 <= iy1 or (ix2 - ix1) * (iy2 - iy1) < 0.6 * (c - a) * (e - b):
                continue
            lines.append(f"0 {((ix1 + ix2) / 2 - x1) / cw:.6f} {((iy1 + iy2) / 2 - y1) / ch:.6f} "
                         f"{(ix2 - ix1) / cw:.6f} {(iy2 - iy1) / ch:.6f}")
        if not lines:
            continue
        crop = img[y1:y2, x1:x2]
        s = MAX_SIDE / max(crop.shape[:2])
        if s < 1:
            crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        name = f"{img_path.stem}_{k}"
        cv2.imwrite(str(OUT / "images" / split / f"{name}.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        (OUT / "labels" / split / f"{name}.txt").write_text("\n".join(lines) + "\n")
        results.append((split, len(lines), d["car"]["attributes"].get("brand", "")))
    return results

if __name__ == "__main__":
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    images = {p.name: p for p in (BASE / "원천데이터").rglob("*.jpg")}
    print(f"원본 이미지 {len(images)}장, 라벨 읽는 중...")
    by_frame = defaultdict(list)
    for p in (BASE / "라벨링데이터" / "merged").rglob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("imagePath") in images:
            by_frame[d["imagePath"]].append(d)
    print(f"라벨이 매칭된 프레임 {len(by_frame)}장")
    tasks = []
    for name, labels in by_frame.items():
        split = "val" if zlib.crc32(labels[0]["videoName"].encode()) % VAL_MOD == 0 else "train"
        tasks.append((images[name], labels, split))
    stat, brands = Counter(), Counter()
    with Pool(8) as pool:
        for i, res in enumerate(pool.imap_unordered(work, tasks, chunksize=32)):
            for split, n, brand in res:
                stat[split] += 1; stat[f"{split}_plates"] += n; brands[brand] += 1
            if i % 5000 == 0:
                print(f"{i}/{len(tasks)}")
    (OUT / "data.yaml").write_text(f"path: {OUT}\ntrain: images/train\nval: images/val\nnames:\n  0: plate\n")
    print(f"\n학습 {stat['train']}장 (번호판 {stat['train_plates']}개) / 검증 {stat['val']}장 (번호판 {stat['val_plates']}개)")
    print("차종 분포:", dict(brands.most_common(8)))
    # 미리보기: 검증 crop 16장에 박스 그리기
    vals = sorted((OUT / "images" / "val").glob("*.jpg"))
    random.seed(0)
    tiles = []
    for ip in random.sample(vals, min(16, len(vals))):
        im = cv2.imread(str(ip)); h, w = im.shape[:2]
        for ln in (OUT / "labels" / "val" / f"{ip.stem}.txt").read_text().split("\n"):
            if ln:
                _, cx, cy, bw, bh = map(float, ln.split())
                cv2.rectangle(im, (int((cx - bw / 2) * w), int((cy - bh / 2) * h)),
                              (int((cx + bw / 2) * w), int((cy + bh / 2) * h)), (0, 0, 255), 2)
        tiles.append(cv2.resize(im, (240, 180)))
    tiles += [np.full((180, 240, 3), 255, np.uint8)] * (-len(tiles) % 4)
    cv2.imwrite(str(OUT / "preview.jpg"), np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]))
    print(f"→ {OUT}/data.yaml, preview.jpg 저장")
