"""AI Hub OCR crop(Training)에서 plate_v2가 거의 못 본 번호판 후보만 모으기 (라벨링은 나중에)

  python collect_aihub_rare.py       # → ~/sooin/spasiba/data/aihub_rare/

후보 기준 (하나라도 해당하면 후보, candidates.csv에 모든 표시를 남김)
  two_line   : PP-OCR 줄 검출(ocr/test_line_det.py와 같은 방식)로 큰 글자 줄이 2줄 이상
  green      : 사진 가운데 영역에 초록 픽셀이 많음 (구형 초록 번호판)
  old_format : 라벨이 옛 지역 번호판 형식 — 시·군 이름 포함(경기부천아0467) 또는 지역명+한 자리(서울4도9472)
폴더는 two_line > green > old_format 순서로 첫 번째 해당 항목에 복사한다.
같은 번호는 최대 2장, Validation은 OCR 평가용으로 남겨 두고 Training만 본다. 원본은 건드리지 않는다.
"""
import json, os, re, shutil, sys
os.environ.setdefault("OMP_NUM_THREADS", "2")
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path
import cv2, numpy as np

DATA = Path(__file__).resolve().parents[2] / "data"
ROOT = DATA / "103.자동차_차종-연식-번호판_인식용_데이터"
LABELS = ROOT / "추가_데이터_보완_건_211229(폴더구조수정)" / "1.Training"
IMAGES = ROOT / "01.데이터" / "1.Training"
OUT = DATA / "aihub_rare"
PER_NUMBER = 2
WORKERS = 8
GREEN_TH = 0.25
STD = re.compile(r"^\d{2,3}[가-힣]\d{4}$")
REGION = re.compile(r"^[가-힣]{2}\d{1,2}[가-힣]\d{4}$")
OLD_REGION = re.compile(r"^[가-힣]{2}\d[가-힣]\d{4}$")               # 서울4도9472

def merge_same_line(boxes):                                        # ocr/test_line_det.py와 동일
    boxes = sorted(boxes, key=lambda b: b[0])
    merged = []
    for b in boxes:
        for i, m in enumerate(merged):
            cy_b, cy_m = (b[1] + b[3]) / 2, (m[1] + m[3]) / 2
            h = max(b[3] - b[1], m[3] - m[1])
            if abs(cy_b - cy_m) < 0.3 * h and b[0] - m[2] < 0.5 * h:
                merged[i] = (min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3]))
                break
        else:
            merged.append(b)
    return merged

def clean_boxes(boxes):                                            # 가장 큰 글자 기준으로 로고·작은 글씨 제거
    boxes = merge_same_line(boxes)
    if not boxes:
        return []
    main = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    mw, mh = main[2] - main[0], main[3] - main[1]
    keep = []
    for b in boxes:
        w, h = b[2] - b[0], b[3] - b[1]
        x_overlap = min(b[2], main[2]) - max(b[0], main[0])
        v_gap = max(main[1] - b[3], b[1] - main[3], 0)
        if b is main or (w >= 0.4 * mw and h >= 0.3 * mh and x_overlap > 0.5 * w and v_gap < 0.5 * mh):
            keep.append(b)
    return keep

def count_lines(boxes):
    lines = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        cy, h = (b[1] + b[3]) / 2, b[3] - b[1]
        for ln in lines:
            if abs(cy - ln["cy"]) < 0.3 * max(h, ln["h"]):
                break
        else:
            lines.append({"cy": cy, "h": h})
    return len(lines)

def init():
    global model
    from paddleocr import TextDetection
    model = TextDetection(model_name="PP-OCRv5_mobile_det", enable_mkldnn=False,
                          cpu_threads=2)                           # 기본 8 × 프로세스 8개면 코어 16개를 두고 경쟁

def analyze(path):
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return path, -1, 0.0
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img[int(h * .2):int(h * .8), int(w * .15):int(w * .85)], cv2.COLOR_BGR2HSV)
    green = float(((hsv[..., 0] >= 35) & (hsv[..., 0] <= 85) & (hsv[..., 1] >= 60) & (hsv[..., 2] >= 50)).mean())
    small = cv2.resize(img, (320, max(32, int(h * 320 / w))))
    res = next(iter(model.predict(small, batch_size=1)))
    raw = []
    for poly in res["dt_polys"]:
        poly = np.array(poly, dtype=np.float32)
        (x1, y1), (x2, y2) = poly.min(0), poly.max(0)
        if (x2 - x1) * (y2 - y1) > 0.01 * small.shape[0] * small.shape[1]:
            raw.append((float(x1), float(y1), float(x2), float(y2)))
    return path, count_lines(clean_boxes(raw)), green

def grid(paths, cols=8, size=(240, 120)):
    tiles = []
    for p in paths:
        im = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
        tiles.append(cv2.resize(im, size))
    tiles += [np.full((size[1], size[0], 3), 40, np.uint8)] * (-len(tiles) % cols)
    return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])

if __name__ == "__main__":
    if OUT.exists():
        sys.exit(f"{OUT} 이 이미 있음 — 덮어쓰지 않고 멈춤")
    images = {p.name: p for p in IMAGES.rglob("*.jpg")}
    by_value = defaultdict(list)
    for jp in sorted(LABELS.rglob("*.json")):
        d = json.loads(jp.read_text(encoding="utf-8"))
        if d["imagePath"] in images:
            by_value[d["value"].replace(" ", "")].append(images[d["imagePath"]])
    todo = {p: v for v, ps in by_value.items() for p in ps[:PER_NUMBER]}
    print(f"번호 {len(by_value)}개, 검사할 사진 {len(todo)}장 (번호당 최대 {PER_NUMBER}장)", flush=True)

    rows = []
    with Pool(WORKERS, initializer=init) as pool:
        for i, (p, n_lines, green) in enumerate(pool.imap_unordered(analyze, todo, chunksize=32), 1):
            v = todo[p]
            old = not STD.match(v) and (not REGION.match(v) or bool(OLD_REGION.match(v)))
            flags = [f for f, ok in (("two_line", n_lines >= 2), ("green", green >= GREEN_TH), ("old_format", old)) if ok]
            if flags:
                rows.append((p, v, n_lines, green, flags))
            if i % 2000 == 0:
                print(f"  {i}/{len(todo)}  후보 {len(rows)}", flush=True)

    for f in ("two_line", "green", "old_format"):
        (OUT / f).mkdir(parents=True)
    with open(OUT / "candidates.csv", "w", encoding="utf-8") as fo:
        fo.write("folder,file,value,n_lines,green_ratio,flags,original\n")
        for p, v, n, g, flags in sorted(rows, key=lambda r: r[1]):
            shutil.copy2(p, OUT / flags[0] / p.name)
            fo.write(f"{flags[0]},{p.name},{v},{n},{g:.3f},{'|'.join(flags)},{p}\n")

    count = Counter(r[4][0] for r in rows)
    both = Counter("|".join(r[4]) for r in rows)
    print(f"\n후보 {len(rows)}장  폴더별 {dict(count)}")
    print(f"표시 조합: {dict(both.most_common())}")
    for f in count:                                                # 폴더마다 미리보기 최대 64장
        cv2.imwrite(str(OUT / f"preview_{f}.jpg"), grid([r[0] for r in rows if r[4][0] == f][:64]))
    print(f"→ {OUT}/  (candidates.csv, preview_*.jpg)")
