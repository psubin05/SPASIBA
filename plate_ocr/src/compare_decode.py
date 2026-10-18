"""같은 가중치, 디코딩 방식만 바꿔서 비교 — 학습 없이 얻는 개선분 측정"""
import json, sys, time
from collections import defaultdict
from pathlib import Path
import cv2, numpy as np, torch
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / "ocr"))
import grammar as G
from train_ocr import Charset, PlateOCR, to_input, edit

DATA = HERE.parents[2] / "data" / "ocr_v1"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
CKPT = sys.argv[2] if len(sys.argv) > 2 else str(HERE.parents[1] / "ocr/weights/ocr_v1.pt")

torch.set_num_threads(8)
cs = Charset(json.loads((DATA / "meta.json").read_text(encoding="utf-8")))
types = G.token_types(cs.tokens)
model = PlateOCR(len(cs)); model.load_state_dict(torch.load(CKPT, map_location="cpu")["model"]); model.eval()

import random as _r
rows = [l.split("\t") for l in (DATA / "test.tsv").read_text(encoding="utf-8").splitlines()]
_r.seed(0); rows = _r.sample(rows, min(N, len(rows)))
modes = ["greedy", "beam", "grammar"]
per = {m: defaultdict(lambda: [0, 0]) for m in modes}
bad_format = 0
t0 = time.time()
with torch.no_grad():
    for n, (rel, txt, kind, nl) in enumerate(rows, 1):
        img = cv2.imread(str(DATA / rel))
        lp = model(to_input(img)[None]).log_softmax(2)[0].numpy()
        kd = f"{kind}/{'2줄' if nl=='2' else '1줄'}"
        for m in modes:
            if m == "greedy":
                ids = lp.argmax(1); out, prev = [], 0
                for k in ids:
                    if k != prev and k != 0: out.append(k)
                    prev = k
            else:
                out, _ = G.beam_decode(lp, types, beam=8, use_grammar=(m == "grammar"))
            pred = cs.decode(out)
            if m == "greedy":
                st = G.START
                for c in out:
                    st = G.step(st, types[c - 1]) if st else None
                    if st is None: break
                if st is None or not G.accepting(st): bad_format += 1
            for key in ("전체", kd):
                per[m][key][0] += (pred == txt); per[m][key][1] += 1
        if n % 300 == 0: print(f"  {n}/{len(rows)}  ({time.time()-t0:.0f}초)", flush=True)

print(f"\n=== 디코딩 방식 비교 ({len(rows)}장, 같은 가중치) ===")
keys = ["전체", "std/1줄", "region/1줄", "region/2줄", "std/2줄"]
print(f"{'종류':<12}{'장수':>6}  " + "".join(f"{m:>10}" for m in modes))
for k in keys:
    if per["greedy"][k][1] == 0: continue
    n_ = per["greedy"][k][1]
    print(f"{k:<12}{n_:>6}  " + "".join(f"{per[m][k][0]/n_*100:9.2f}%" for m in modes))
g = per["greedy"]["전체"]; gr = per["grammar"]["전체"]
print(f"\ngreedy 출력 중 번호판 형식을 어긴 것: {bad_format}장 ({bad_format/len(rows)*100:.2f}%)")
print(f"문법 제약으로 바뀐 정확도: {g[0]/g[1]*100:.2f}% → {gr[0]/gr[1]*100:.2f}%  ({(gr[0]-g[0])/g[1]*100:+.2f}%p)")
