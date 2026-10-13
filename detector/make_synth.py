import random, sys, shutil
from pathlib import Path
import cv2, numpy as np

random.seed(0)
data = Path(sys.argv[1] if len(sys.argv) > 1 else "../../data").resolve()
split = sys.argv[2] if len(sys.argv) > 2 else "val"
src = data / "yolo_plate"
out = data / "yolo_plate_synth"
ocr_root = data / "103.자동차_차종-연식-번호판_인식용_데이터" / "01.데이터"
plates = sorted(ocr_root.rglob("*.jpg"))
print(f"선명한 번호판 crop {len(plates)}장")
(out / "images" / split).mkdir(parents=True, exist_ok=True)
(out / "labels" / split).mkdir(parents=True, exist_ok=True)

def trim(img):                                     # OCR crop 가장자리 여백 대충 잘라내기
    h, w = img.shape[:2]
    return img[int(h * 0.15):int(h * 0.85), int(w * 0.08):int(w * 0.92)]

n = 0
for ip in sorted((src / "images" / split).glob("*.jpg")):
    lp = src / "labels" / split / f"{ip.stem}.txt"
    img = cv2.imread(str(ip)); H, W = img.shape[:2]
    for line in lp.read_text().split("\n"):
        if not line:
            continue
        _, cx, cy, bw, bh = map(float, line.split())
        x1, y1 = max(0, int((cx - bw / 2) * W)), max(0, int((cy - bh / 2) * H))
        x2, y2 = min(W, int((cx + bw / 2) * W)), min(H, int((cy + bh / 2) * H))
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        pl = cv2.imdecode(np.fromfile(str(random.choice(plates)), np.uint8), cv2.IMREAD_COLOR)
        pl = cv2.resize(trim(pl), (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA).astype(np.float32)
        region = img[y1:y2, x1:x2].astype(np.float32)
        pl = pl * (region.mean() / max(pl.mean(), 1)) ** 0.5          # 밝기 대충 맞추기
        img[y1:y2, x1:x2] = np.clip(cv2.GaussianBlur(pl, (3, 3), 0), 0, 255).astype(np.uint8)
    cv2.imwrite(str(out / "images" / split / ip.name), img)
    shutil.copy(lp, out / "labels" / split / lp.name)
    n += 1
(out / "data.yaml").write_text(f"path: {out}\ntrain: images/{split}\nval: images/{split}\nnames:\n  0: plate\n")
print(f"→ {out} 에 {n}장 저장")
