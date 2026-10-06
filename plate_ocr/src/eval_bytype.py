"""학습된 모델을 번호판 종류별로 평가한다 (계획서 A-7 '종류별 비교'에 해당)."""
import sys, os, random, argparse
from collections import defaultdict
import numpy as np, cv2, torch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth
from train import CRNN, ctc_decode, lev, IMG_H, IMG_W
from unfold import unfold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", default=os.path.join(ROOT, "runs", "crnn_v2_unfold", "best.pt"))
    p.add_argument("--n", type=int, default=400, help="종류당 장수")
    a = p.parse_args()

    d = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    itos = d["itos"]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    m = CRNN(len(itos)).to(dev); m.load_state_dict(d["model"]); m.eval()
    uf = d.get("unfold", False)
    print(f"두 줄 펴기(unfold)={uf}")

    print(f"체크포인트: 전체 완전일치 {d['exact']*100:.2f}% / 글자정확도 {d['char']*100:.2f}%\n")
    rows, wrong = [], defaultdict(list)
    for pt in synth.PLATE_TYPES:
        random.seed(hash(pt) % 2**31); np.random.seed(hash(pt) % 2**31)
        ex = ed = ch = 0
        for i in range(a.n):
            label, lines = synth.make_text(pt)
            img = synth.augment(synth.render(pt, lines))
            if uf: img = unfold(img)
            g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (IMG_W, IMG_H),
                           interpolation=cv2.INTER_AREA)
            x = torch.from_numpy(g).float().div_(127.5).sub_(1.0)[None, None].to(dev)
            with torch.no_grad():
                pred = ctc_decode(m(x)[0].float().cpu())
            ex += (pred == label); ed += lev(pred, label); ch += len(label)
            if pred != label and len(wrong[pt]) < 5:
                wrong[pt].append((label, pred))
        rows.append((pt, ex / a.n, 1 - ed / ch))

    w = max(len(r[0]) for r in rows)
    print(f"{'종류'.ljust(w)}   완전일치   글자정확도")
    print("-" * (w + 24))
    for pt, e, c in rows:
        print(f"{pt.ljust(w)}   {e*100:6.2f}%   {c*100:6.2f}%")
    print(f"\n{'평균'.ljust(w)}   {sum(r[1] for r in rows)/len(rows)*100:6.2f}%   "
          f"{sum(r[2] for r in rows)/len(rows)*100:6.2f}%")

    print("\n--- 종류별 오답 예시 (정답 → 예측) ---")
    for pt in synth.PLATE_TYPES:
        if wrong[pt]:
            print(f"[{pt}]")
            for lab, pr in wrong[pt]:
                print(f"   {lab:>12}  →  {pr}")

if __name__ == "__main__":
    main()
