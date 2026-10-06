"""번호판 OCR 학습: CRNN(CNN + BiLSTM) + CTC.

합성 번호판을 그 자리에서 만들어 학습한다(디스크에 쌓지 않음).
"""
import os, sys, time, random, argparse, json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth
from unfold import unfold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IMG_H, IMG_W = 32, 160

# ---------- 문자 집합 ----------
CHARS = sorted(set("0123456789") | set(synth.HANGUL) | set("".join(synth.REGION)))
# CTC: 0번은 blank
itos = ["_"] + CHARS
stoi = {c: i + 1 for i, c in enumerate(CHARS)}
NCLASS = len(itos)


def encode(s):
    return [stoi[c] for c in s]


def ctc_decode(logits):
    """greedy. logits: (T, C)"""
    ids = logits.argmax(1).tolist()
    out, prev = [], 0
    for i in ids:
        if i != prev and i != 0:
            out.append(itos[i])
        prev = i
    return "".join(out)


# ---------- 데이터 ----------
class PlateSet(Dataset):
    def __init__(self, n, aug=True, seed=None, use_unfold=True):
        self.n, self.aug, self.seed = n, aug, seed
        self.use_unfold = use_unfold

    def __len__(self):
        return self.n

    def __getitem__(self, i):
        if self.seed is not None:          # 검증셋은 고정
            random.seed(self.seed + i); np.random.seed((self.seed + i) % 2**31)
        img, label, _ = synth.sample(aug=self.aug)
        if self.use_unfold:
            img = unfold(img)
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (IMG_W, IMG_H), interpolation=cv2.INTER_AREA)
        x = torch.from_numpy(g).float().div_(127.5).sub_(1.0).unsqueeze(0)
        return x, torch.tensor(encode(label), dtype=torch.long), label


def collate(batch):
    xs = torch.stack([b[0] for b in batch])
    ys = torch.cat([b[1] for b in batch])
    lens = torch.tensor([len(b[1]) for b in batch], dtype=torch.long)
    return xs, ys, lens, [b[2] for b in batch]


# ---------- 모델 ----------
class CRNN(nn.Module):
    def __init__(self, nclass, nh=256):
        super().__init__()
        def blk(i, o, pool):
            return [nn.Conv2d(i, o, 3, 1, 1), nn.BatchNorm2d(o), nn.ReLU(True),
                    nn.MaxPool2d(*pool)]
        self.cnn = nn.Sequential(
            *blk(1, 64,  ((2, 2), (2, 2))),        # 32x160 -> 16x80
            *blk(64, 128, ((2, 2), (2, 2))),       # -> 8x40
            nn.Conv2d(128, 256, 3, 1, 1), nn.BatchNorm2d(256), nn.ReLU(True),
            *blk(256, 256, ((2, 1), (2, 1))),      # -> 4x40  (가로 길이 유지)
            nn.Conv2d(256, 512, 3, 1, 1), nn.BatchNorm2d(512), nn.ReLU(True),
            nn.MaxPool2d((4, 1), (4, 1)),          # -> 1x40
        )
        self.rnn = nn.LSTM(512, nh, num_layers=2, bidirectional=True,
                           batch_first=True, dropout=0.1)
        self.fc = nn.Linear(nh * 2, nclass)

    def forward(self, x):
        f = self.cnn(x)                 # (B,512,1,W')
        f = f.squeeze(2).permute(0, 2, 1)   # (B,W',512)
        f, _ = self.rnn(f)
        return self.fc(f)               # (B,T,C)


# ---------- 평가 ----------
def lev(a, b):
    if a == b: return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@torch.no_grad()
def evaluate(model, loader, dev):
    model.eval()
    exact = tot = ed = chars = 0
    samples = []
    for xs, _, _, labels in loader:
        out = model(xs.to(dev, non_blocking=True)).float().cpu()
        for i, lab in enumerate(labels):
            pred = ctc_decode(out[i])
            exact += (pred == lab); tot += 1
            ed += lev(pred, lab); chars += len(lab)
            if len(samples) < 12: samples.append((lab, pred))
    return exact / tot, 1 - ed / chars, samples


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=14)
    p.add_argument("--train-size", type=int, default=24000)
    p.add_argument("--val-size", type=int, default=2000)
    p.add_argument("--batch", type=int, default=128)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", default=os.path.join(ROOT, "runs", "crnn_v1"))
    p.add_argument("--no-unfold", action="store_true", help="두 줄 판 펴기 끄기")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={dev} {torch.cuda.get_device_name(0) if dev=='cuda' else ''}")
    print(f"문자 수={NCLASS-1} (+blank)  학습 {a.train_size}/epoch  검증 {a.val_size}")

    uf = not a.no_unfold
    print(f"두 줄 펴기(unfold)={uf}")
    tl = DataLoader(PlateSet(a.train_size, aug=True, use_unfold=uf), batch_size=a.batch, shuffle=False,
                    num_workers=a.workers, collate_fn=collate, drop_last=True,
                    pin_memory=True, persistent_workers=True)
    vl = DataLoader(PlateSet(a.val_size, aug=True, seed=777_000, use_unfold=uf), batch_size=256,
                    shuffle=False, num_workers=4, collate_fn=collate, pin_memory=True)

    model = CRNN(NCLASS).to(dev)
    print(f"파라미터 {sum(x.numel() for x in model.parameters())/1e6:.1f}M")
    crit = nn.CTCLoss(blank=0, zero_infinity=True)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    steps = a.epochs * (a.train_size // a.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr * 3, total_steps=steps,
                                                pct_start=0.25)
    scaler = torch.amp.GradScaler(dev, enabled=(dev == "cuda"))

    hist, best, t0 = [], 0.0, time.time()
    for ep in range(1, a.epochs + 1):
        model.train(); run = n = 0
        for xs, ys, lens, _ in tl:
            xs = xs.to(dev, non_blocking=True)
            with torch.amp.autocast(dev, enabled=(dev == "cuda")):
                out = model(xs)
                lp = out.log_softmax(2).permute(1, 0, 2).float()   # (T,B,C)
                il = torch.full((xs.size(0),), lp.size(0), dtype=torch.long)
                loss = crit(lp, ys, il, lens)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt); nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(opt); scaler.update(); sched.step()
            run += loss.item(); n += 1
        acc, cacc, samples = evaluate(model, vl, dev)
        el = time.time() - t0
        print(f"ep {ep:2d}/{a.epochs}  loss {run/n:.4f}  "
              f"완전일치 {acc*100:5.2f}%  글자정확도 {cacc*100:5.2f}%  ({el/60:.1f}분)", flush=True)
        hist.append(dict(epoch=ep, loss=run/n, exact=acc, char=cacc, min=el/60))
        if acc > best:
            best = acc
            torch.save(dict(model=model.state_dict(), itos=itos, unfold=uf,
                            img=(IMG_H, IMG_W), exact=acc, char=cacc), f"{a.out}/best.pt")

    print("\n--- 검증 샘플 (정답 → 예측) ---")
    for lab, pred in samples:
        print(f"  {lab:>12}  →  {pred:<12} {'OK' if lab==pred else 'X'}")
    json.dump(hist, open(f"{a.out}/history.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n최고 완전일치 {best*100:.2f}%   총 {(time.time()-t0)/60:.1f}분")
    print(f"가중치: {a.out}/best.pt")


if __name__ == "__main__":
    main()
