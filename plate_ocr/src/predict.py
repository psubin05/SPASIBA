"""학습한 CRNN으로 번호판 이미지를 읽는다.

사용법: python src/predict.py 이미지1.png 이미지2.jpg ...
"""
import sys, os
import numpy as np, cv2, torch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train import CRNN, ctc_decode, IMG_H, IMG_W
from unfold import unfold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CKPT = os.path.join(ROOT, "runs", "crnn_v2_unfold", "best.pt")

def load(ckpt=CKPT):
    d = torch.load(ckpt, map_location="cpu", weights_only=False)
    m = CRNN(len(d["itos"])); m.load_state_dict(d["model"]); m.eval()
    return m, d

def read(m, path, use_unfold=True):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None: return None
    if use_unfold: img = unfold(img)
    g = cv2.resize(img, (IMG_W, IMG_H), interpolation=cv2.INTER_AREA)
    x = torch.from_numpy(g).float().div_(127.5).sub_(1.0)[None, None]
    with torch.no_grad():
        out = m(x)[0]
    return ctc_decode(out)

if __name__ == "__main__":
    if not os.path.exists(CKPT):
        sys.exit(f"가중치 없음: {CKPT} — 먼저 학습하세요")
    m, d = load()
    print(f"체크포인트 완전일치 {d['exact']*100:.2f}% / 글자정확도 {d['char']*100:.2f}%\n")
    uf = d.get("unfold", True)
    ok = n = 0
    for p in sys.argv[1:]:
        pred = read(m, p, uf)
        base = os.path.basename(p)
        truth = base.rsplit("_", 1)[-1].rsplit(".", 1)[0] if "_" in base else None
        mark = ""
        if truth:
            n += 1; ok += (pred == truth); mark = "  OK" if pred == truth else "  X"
        print(f"{base:<42} → {pred}{mark}")
    if n: print(f"\n{ok}/{n} 정답")
