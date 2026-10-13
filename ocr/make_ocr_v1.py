"""OCR 학습 데이터 ocr_v1 만들기 — 실제 파이프라인(① 검출 → ② 줄 검출 → 두 줄 펴기)과 같은 방식으로 자른다

  python make_ocr_v1.py              # → ~/sooin/spasiba/data/ocr_v1/

1. AI Hub OCR crop(Training + Validation 9만 장)에서 지원 형식만 남긴다
   일반 `12가3456`/`123가4567`, 지역명 `서울12가3456`·`서울4도9472` (17개 시·도). 그 외(이륜차·건설기계 등)는 제외 (결정 3)
2. 같은 번호는 최대 PER_NUMBER장, 번호 단위로 train/val/test = 8:1:1 (번호 문자열 해시로 고정, 결정 4)
3. ① plate_v3로 번호판을 잘라낸다 (확신도 1등 박스, 사방 MARGIN 여백). 못 찾으면 제외
4. ② PP-OCR 줄 검출로 줄을 센다. 2줄이면 윗줄·아랫줄을 같은 높이로 맞춰 좌우로 이어 붙인다 (펴기)
   1줄(또는 줄을 못 찾음)이면 번호판 crop을 그대로 쓴다. 3줄 이상은 제외
5. 높이 OUT_H로 줄여 저장, {split}.tsv에 `경로<TAB>번호<TAB>종류<TAB>줄 수` 기록
원본은 건드리지 않고, ocr_v1이 이미 있으면 멈춘다.
"""
import hashlib, json, os, re, sys
os.environ.setdefault("OMP_NUM_THREADS", "2")
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path
import cv2, numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data"
ROOT = DATA / "103.자동차_차종-연식-번호판_인식용_데이터"
LABELS = ROOT / "추가_데이터_보완_건_211229(폴더구조수정)"
IMAGES = ROOT / "01.데이터"
OUT = DATA / "ocr_v1"
DET = HERE.parent / "detector/weights/plate_v3.pt"
PER_NUMBER, MARGIN, OUT_H, WORKERS = 5, 0.04, 48, 8
REGIONS = "서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
STD = re.compile(r"^\d{2,3}[가-힣]\d{4}$")
REGION = re.compile(rf"^({REGIONS})\d{{1,3}}[가-힣]\d{{4}}$")

def imread(p):
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)

def split_of(value):                                               # 번호 → 항상 같은 split
    h = int(hashlib.sha1(value.encode()).hexdigest(), 16) % 10
    return "test" if h == 0 else "val" if h == 1 else "train"

# ── ② 줄 검출: ocr/test_line_det.py, detector/collect_aihub_rare.py와 같은 규칙 ──
def merge_same_line(boxes):
    boxes = sorted(boxes, key=lambda b: b[0])
    merged = []
    for b in boxes:
        for i, m in enumerate(merged):
            h = max(b[3] - b[1], m[3] - m[1])
            if abs((b[1] + b[3]) / 2 - (m[1] + m[3]) / 2) < 0.3 * h and b[0] - m[2] < 0.5 * h:
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

def group_lines(boxes):                                            # 줄마다 박스를 합쳐 위→아래 순서로
    lines = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        cy, h = (b[1] + b[3]) / 2, b[3] - b[1]
        for ln in lines:
            if abs(cy - ln["cy"]) < 0.3 * max(h, ln["h"]):
                x = ln["box"]
                ln["box"] = (min(x[0], b[0]), min(x[1], b[1]), max(x[2], b[2]), max(x[3], b[3]))
                break
        else:
            lines.append({"cy": cy, "h": h, "box": b})
    return [ln["box"] for ln in sorted(lines, key=lambda l: l["cy"])]

def init():
    global line_model
    from paddleocr import TextDetection
    line_model = TextDetection(model_name="PP-OCRv5_mobile_det", enable_mkldnn=False, cpu_threads=2)

def find_lines(plate):
    """번호판 crop → 큰 글자 줄 박스 목록 (crop 좌표, 위→아래)"""
    h, w = plate.shape[:2]
    s = 320 / w
    small = cv2.resize(plate, (320, max(32, int(h * s))))
    res = next(iter(line_model.predict(small, batch_size=1)))
    raw = []
    for poly in res["dt_polys"]:
        poly = np.array(poly, dtype=np.float32)
        (x1, y1), (x2, y2) = poly.min(0), poly.max(0)
        if (x2 - x1) * (y2 - y1) > 0.01 * small.shape[0] * small.shape[1]:
            raw.append((x1 / s, y1 / small.shape[0] * h, x2 / s, y2 / small.shape[0] * h))
    return group_lines(clean_boxes(raw))

def unfold(plate, lines, out_h=OUT_H):
    """2줄이면 윗줄·아랫줄을 같은 높이로 맞춰 좌우로 이어 붙이고, 아니면 crop 그대로"""
    if len(lines) != 2:
        return cv2.resize(plate, (max(1, round(plate.shape[1] * out_h / plate.shape[0])), out_h))
    h, w = plate.shape[:2]
    parts = []
    for x1, y1, x2, y2 in lines:
        py, px = 0.08 * (y2 - y1), 0.03 * w                       # 글자 가장자리가 잘리지 않게 여백
        crop = plate[max(0, int(y1 - py)):min(h, int(y2 + py)), max(0, int(x1 - px)):min(w, int(x2 + px))]
        parts.append(cv2.resize(crop, (max(1, round(crop.shape[1] * out_h / crop.shape[0])), out_h)))
    gap = np.full((out_h, out_h // 4, 3), 127, np.uint8)
    return np.hstack([parts[0], gap, parts[1]])

def work(job):
    i, path, box, value, split = job
    img = imread(path)
    x1, y1, x2, y2 = box
    plate = img[int(y1):int(y2), int(x1):int(x2)]
    if plate.size == 0:
        return i, None, 0
    lines = find_lines(plate)
    if len(lines) > 2:
        return i, None, len(lines)
    out = unfold(plate, lines)
    rel = f"images/{split}/{i:06d}.jpg"
    cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(OUT / rel))
    return i, rel, len(lines)

if __name__ == "__main__":
    if OUT.exists():
        sys.exit(f"{OUT} 이 이미 있음 — 덮어쓰지 않고 멈춤")
    images = {p.name: p for p in IMAGES.rglob("*.jpg")}
    by_value = defaultdict(list)
    skipped = Counter()
    for jp in sorted(LABELS.rglob("*.json")):
        d = json.loads(jp.read_text(encoding="utf-8"))
        v = d["value"].replace(" ", "")
        if not (STD.match(v) or REGION.match(v)):
            skipped["지원 안 하는 형식"] += 1; continue
        if d["imagePath"] not in images:
            skipped["이미지 없음"] += 1; continue
        by_value[v].append(images[d["imagePath"]])
    todo = [(p, v) for v, ps in sorted(by_value.items()) for p in ps[:PER_NUMBER]]
    print(f"번호 {len(by_value)}개, 사용할 사진 {len(todo)}장 (번호당 최대 {PER_NUMBER}), 제외 {dict(skipped)}", flush=True)

    # ① plate_v3로 번호판 박스 (GPU)
    from ultralytics import YOLO
    det = YOLO(str(DET))
    jobs, no_det = [], 0
    for k in range(0, len(todo), 128):
        chunk = todo[k:k + 128]
        for (p, v), r in zip(chunk, det.predict([imread(p) for p, _ in chunk], conf=0.25, verbose=False)):
            if not len(r.boxes):
                no_det += 1; continue
            h, w = r.orig_shape
            bx1, by1, bx2, by2 = r.boxes.xyxy[r.boxes.conf.argmax()].tolist()
            mx, my = (bx2 - bx1) * MARGIN, (by2 - by1) * MARGIN
            box = (max(0, bx1 - mx), max(0, by1 - my), min(w, bx2 + mx), min(h, by2 + my))
            jobs.append((len(jobs), str(p), box, v, split_of(v)))
        if k % 12800 == 0:
            print(f"  ① 검출 {k}/{len(todo)}", flush=True)
    print(f"① 검출 완료: {len(jobs)}장, 번호판 못 찾음 {no_det}장", flush=True)

    # ② 줄 검출 + 펴기 (CPU 여러 프로세스)
    for s in ("train", "val", "test"):
        (OUT / "images" / s).mkdir(parents=True)
    rows, n_lines_count, too_many = {}, Counter(), 0
    with Pool(WORKERS, initializer=init) as pool:
        for n, (i, rel, nl) in enumerate(pool.imap_unordered(work, jobs, chunksize=32), 1):
            n_lines_count[nl] += 1
            if rel is None:
                too_many += 1; continue
            rows[i] = (rel, nl)
            if n % 10000 == 0:
                print(f"  ② 줄 검출 {n}/{len(jobs)}", flush=True)

    files = {s: open(OUT / f"{s}.tsv", "w", encoding="utf-8") for s in ("train", "val", "test")}
    stat = defaultdict(Counter)
    for i, _, _, v, s in jobs:
        if i not in rows:
            continue
        rel, nl = rows[i]
        kind = "region" if REGION.match(v) else "std"
        files[s].write(f"{rel}\t{v}\t{kind}\t{nl}\n")
        stat[s][f"{kind}/{'2줄' if nl == 2 else '1줄'}"] += 1
    for f in files.values():
        f.close()
    charset = sorted({c for _, v in todo for c in re.sub(rf"^({REGIONS})", "", v)} - set("0123456789"))
    (OUT / "meta.json").write_text(json.dumps({"regions": REGIONS.split("|"), "hangul": charset, "out_h": OUT_H},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n줄 수 분포: {dict(sorted(n_lines_count.items()))}  (3줄 이상 제외 {too_many})")
    for s in ("train", "val", "test"):
        print(f"{s:<6} {sum(stat[s].values()):>6}장  {dict(sorted(stat[s].items()))}")
    print(f"한글 {len(charset)}자: {''.join(charset)}")
    print(f"→ {OUT}/")
