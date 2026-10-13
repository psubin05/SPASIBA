"""카메라 화면 → 번호 읽기 (① 검출 → ② 줄 검출 → ③ 글자 인식 → ④ 이어 붙이기)

  python plate_reader.py <사진 폴더> [--out 결과폴더] [--ocr weights/ocr_v1.pt]
      → 결과 그림(박스 + 읽은 번호)과 results.csv

코드에서 쓰기:
  reader = PlateReader()
  for p in reader(image):      # image: BGR numpy
      p["text"], p["conf"], p["box"], p["char_probs"]

- ①은 detector/weights/plate_v3.pt, 박스에 사방 4% 여백 (OCR 학습 데이터와 같은 조건)
- ②④는 ocr/make_ocr_v1.py의 find_lines / unfold를 그대로 쓴다 (2줄이면 좌우로 펴서 한 번에 읽음)
- char_probs: 서버 버퍼 매칭용. 읽은 글자마다 상위 TOPK 후보와 확률
"""
import argparse, csv, sys
from pathlib import Path
import cv2, numpy as np, torch
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_ocr_v1 as prep                                         # noqa: E402  ② 줄 검출, ④ 펴기
from train_ocr import PlateOCR, to_input                          # noqa: E402  ③ 인식 모델

DET_W = HERE.parent / "detector/weights/plate_v3.pt"
OCR_W = HERE / "weights/ocr_v1.pt"
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
TOPK = 3


class PlateReader:
    def __init__(self, det_w=DET_W, ocr_w=OCR_W, device=None, det_conf=0.25):
        from ultralytics import YOLO
        self.dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.det, self.det_conf = YOLO(str(det_w)), det_conf
        ck = torch.load(ocr_w, map_location=self.dev)
        self.tokens = [t.strip("<>") for t in ck["tokens"]]
        self.ocr = PlateOCR(len(self.tokens) + 1).to(self.dev).eval()
        self.ocr.load_state_dict(ck["model"])
        prep.init()

    def detect(self, img):
        """① 번호판 박스 + crop 목록"""
        h, w = img.shape[:2]
        r = self.det.predict(img, conf=self.det_conf, verbose=False)[0]
        out = []
        for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist()):
            mx, my = (x2 - x1) * prep.MARGIN, (y2 - y1) * prep.MARGIN
            box = (int(max(0, x1 - mx)), int(max(0, y1 - my)), int(min(w, x2 + mx)), int(min(h, y2 + my)))
            out.append({"box": box, "det_conf": c, "crop": img[box[1]:box[3], box[0]:box[2]]})
        return out

    @torch.no_grad()
    def read(self, crop):
        """②③④ 번호판 crop → 번호, 글자별 확률"""
        lines = prep.find_lines(crop)
        x = to_input(prep.unfold(crop, lines[:2] if len(lines) >= 2 else lines))[None].to(self.dev)
        probs = self.ocr(x)[0].exp().cpu()                       # (T, C)
        best = probs.argmax(-1).tolist()
        text, conf, char_probs, prev = "", 1.0, [], 0
        for t, s in enumerate(best):
            if s != prev and s != 0:
                top = probs[t].topk(TOPK + 1)                     # blank 제외하고 상위 TOPK
                cand = [(self.tokens[i - 1], round(p, 4)) for p, i in zip(top.values.tolist(), top.indices.tolist()) if i != 0][:TOPK]
                text += self.tokens[s - 1]; conf *= probs[t, s].item(); char_probs.append(cand)
            prev = s
        return {"text": text, "conf": conf, "n_lines": len(lines), "char_probs": char_probs}

    def __call__(self, img):
        return [{**p, **self.read(p["crop"])} for p in self.detect(img) if p["crop"].size]


def draw(img, plates):
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    size = max(16, img.shape[1] // 40)
    font = ImageFont.truetype(FONT, size)
    for p in plates:
        x1, y1, x2, y2 = p["box"]
        d.rectangle((x1, y1, x2, y2), outline=(255, 0, 0), width=max(2, img.shape[1] // 400))
        label = f"{p['text']} ({p['conf']:.2f})"
        tw = d.textlength(label, font=font)
        ty = y1 - size - 6 if y1 > size + 6 else y2 + 2
        d.rectangle((x1, ty, x1 + tw + 6, ty + size + 4), fill=(255, 0, 0))
        d.text((x1 + 3, ty), label, font=font, fill=(255, 255, 255))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default="read_out")
    ap.add_argument("--ocr", default=str(OCR_W))
    a = ap.parse_args()
    reader = PlateReader(ocr_w=a.ocr)
    out = Path(a.out); out.mkdir(exist_ok=True)
    with open(out / "results.csv", "w", encoding="utf-8") as f:
        f.write("image,text,conf,n_lines,det_conf,x1,y1,x2,y2\n")
        for ip in sorted(p for p in Path(a.src).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")):
            img = prep.imread(ip)
            plates = reader(img)
            for p in plates:
                f.write(f"{ip.name},{p['text']},{p['conf']:.3f},{p['n_lines']},{p['det_conf']:.3f},{','.join(map(str, p['box']))}\n")
            vis = draw(img, plates)
            s = min(1.0, 1280 / max(vis.shape[:2]))
            cv2.imencode(".jpg", cv2.resize(vis, None, fx=s, fy=s))[1].tofile(str(out / f"{ip.stem}.jpg"))
            print(f"{ip.name}: " + (", ".join(f"{p['text']}({p['conf']:.2f})" for p in plates) or "번호판 없음"), flush=True)
    print(f"→ {out}/")
