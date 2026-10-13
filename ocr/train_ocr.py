"""번호판 글자 인식(③) 학습 — 경량 CNN + BiGRU + CTC

  python train_ocr.py --name ocr_v1_mild --augment mild --epochs 30
  python train_ocr.py --name ocr_v1_strong --augment strong --epochs 10 --lr 3e-4 --init runs/ocr_v1_mild/best.pt
  python train_ocr.py --eval-only --init runs/ocr_v1_mild/best.pt      # test 평가만

- 입력: make_ocr_v1.py가 만든 높이 48 이미지 (두 줄은 이미 좌우로 펴져 있음) → 비율 유지해 48×W_IN으로 맞춤
- 글자: CTC blank + 숫자 10 + 한글 + 지역명 17개(토큰 1개씩, 결정 2)
- 좌우 반전 증강은 쓰지 않는다. 약한 증강으로 먼저 학습한 뒤 강한 증강으로 이어서 학습한다
- 평가: 번호판 전체 일치율, 글자 오류율(CER), 종류(일반/지역명 × 1줄/2줄)별
"""
import argparse, json, math, random, time
from collections import defaultdict
from pathlib import Path
import cv2, numpy as np, torch, torch.nn as nn
from torch.utils.data import DataLoader, Dataset

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data" / "ocr_v1"
H_IN, W_IN = 48, 256


class Charset:
    def __init__(self, meta):
        self.regions = meta["regions"]
        self.tokens = list("0123456789") + meta["hangul"] + [f"<{r}>" for r in self.regions]
        self.index = {t: i + 1 for i, t in enumerate(self.tokens)}             # 0 = CTC blank

    def encode(self, text):
        out = []
        for r in self.regions:                                     # 지역명은 맨 앞에만 온다
            if text.startswith(r):
                out.append(self.index[f"<{r}>"]); text = text[len(r):]; break
        return out + [self.index[c] for c in text]

    def decode(self, ids):
        return "".join(self.tokens[i - 1].strip("<>") for i in ids)

    def __len__(self):
        return len(self.tokens) + 1


def augment(img, strength):
    h, w = img.shape[:2]
    deg, persp, blur_p = (4, 0.04, 0.15) if strength == "mild" else (10, 0.10, 0.35)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jit = np.random.uniform(-persp, persp, (4, 2)) * [w, h]
    m = cv2.getPerspectiveTransform(src, (src + jit).astype(np.float32))
    rot = cv2.getRotationMatrix2D((w / 2, h / 2), random.uniform(-deg, deg), random.uniform(0.92, 1.05))
    m = np.vstack([rot, [0, 0, 1]]) @ m
    img = cv2.warpPerspective(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE)
    img = cv2.convertScaleAbs(img, alpha=random.uniform(0.6, 1.4), beta=random.uniform(-40, 40))
    if random.random() < blur_p:
        k = random.choice([3, 5]) if strength == "strong" else 3
        img = cv2.GaussianBlur(img, (k, k), 0)
    if strength == "strong" and random.random() < 0.3:          # 저해상도 흉내
        f = random.uniform(0.35, 0.7)
        img = cv2.resize(cv2.resize(img, None, fx=f, fy=f), (w, h))
    if random.random() < 0.2:
        img = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    return img


def to_input(img):
    """비율을 유지해 높이 H_IN으로 줄이고 오른쪽을 회색으로 채움 (너무 길면 W_IN으로 눌러 맞춤)"""
    h, w = img.shape[:2]
    nw = min(W_IN, max(8, round(w * H_IN / h)))
    canvas = np.full((H_IN, W_IN, 3), 127, np.uint8)
    canvas[:, :nw] = cv2.resize(img, (nw, H_IN))
    return torch.from_numpy(canvas).permute(2, 0, 1).float().div(255).sub(0.5).div(0.5)


class PlateSet(Dataset):
    def __init__(self, split, charset, aug=None):
        self.rows = [ln.split("\t") for ln in (DATA / f"{split}.tsv").read_text(encoding="utf-8").splitlines()]
        self.charset, self.aug = charset, aug

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        rel, text, kind, nl = self.rows[i]
        img = cv2.imread(str(DATA / rel))
        if self.aug:
            img = augment(img, self.aug)
        return to_input(img), torch.tensor(self.charset.encode(text)), text, f"{kind}/{'2줄' if nl == '2' else '1줄'}"


def collate(batch):
    imgs, targets, texts, kinds = zip(*batch)
    return torch.stack(imgs), torch.cat(targets), torch.tensor([len(t) for t in targets]), texts, kinds


def block(cin, cout, k=3, p=1):
    return nn.Sequential(nn.Conv2d(cin, cout, k, padding=p, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True))


class PlateOCR(nn.Module):
    def __init__(self, n_classes):
        super().__init__()
        self.cnn = nn.Sequential(                                  # 48×256 → 1×64 (가로 64칸)
            block(3, 32), nn.MaxPool2d(2),                         # 24×128
            block(32, 64), nn.MaxPool2d(2),                        # 12×64
            block(64, 128), block(128, 128), nn.MaxPool2d((2, 1)),  # 6×64
            block(128, 192), block(192, 192), nn.MaxPool2d((2, 1)),  # 3×64
            block(192, 192, k=(3, 1), p=0),                        # 1×64
        )
        self.rnn = nn.GRU(192, 128, num_layers=2, bidirectional=True, batch_first=True, dropout=0.1)
        self.fc = nn.Linear(256, n_classes)

    def forward(self, x):                                          # → (B, T, C) log 확률
        f = self.cnn(x).squeeze(2).permute(0, 2, 1)
        return self.fc(self.rnn(f)[0]).log_softmax(-1)


def greedy(logp):
    out = []
    for seq in logp.argmax(-1).tolist():
        ids, prev = [], 0
        for s in seq:
            if s != prev and s != 0:
                ids.append(s)
            prev = s
        out.append(ids)
    return out


def edit(a, b):
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (ca != cb))
    return d[-1]


@torch.no_grad()
def evaluate(model, loader, charset, dev, show=0):
    model.eval()
    st = defaultdict(lambda: [0, 0, 0, 0])                         # 종류 → [맞음, 전체, 글자 오류, 글자 수]
    wrong = []
    for x, _, _, texts, kinds in loader:
        preds = [charset.decode(p) for p in greedy(model(x.to(dev)))]
        for p, t, k in zip(preds, texts, kinds):
            for key in (k, "전체"):
                s = st[key]; s[0] += p == t; s[1] += 1; s[2] += edit(p, t); s[3] += len(t)
            if p != t and len(wrong) < show:
                wrong.append((t, p, k))
    return {k: {"exact": v[0] / v[1], "cer": v[2] / v[3], "n": v[1]} for k, v in st.items()}, wrong


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="ocr_v1_mild")
    ap.add_argument("--augment", choices=["mild", "strong"], default="mild")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--init", default="")
    ap.add_argument("--eval-only", action="store_true")
    a = ap.parse_args()
    random.seed(0); torch.manual_seed(0)
    dev = "cuda"
    charset = Charset(json.loads((DATA / "meta.json").read_text(encoding="utf-8")))
    model = PlateOCR(len(charset)).to(dev)
    if a.init:
        model.load_state_dict(torch.load(a.init, map_location=dev)["model"])
    print(f"글자 {len(charset) - 1}개 + blank, 파라미터 {sum(p.numel() for p in model.parameters()):,}", flush=True)
    mk = lambda split, aug, sh: DataLoader(PlateSet(split, charset, aug), a.batch, shuffle=sh, num_workers=8,
                                           collate_fn=collate, pin_memory=True, persistent_workers=not a.eval_only)
    test = mk("test", None, False)
    if a.eval_only:
        res, wrong = evaluate(model, test, charset, dev, show=30)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        for t, p, k in wrong:
            print(f"  {k:<10} 정답 {t:<12} 예측 {p}")
        return

    out = HERE / "runs" / a.name; out.mkdir(parents=True, exist_ok=False)
    train, val = mk("train", a.augment, True), mk("val", None, False)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, a.lr, total_steps=a.epochs * len(train), pct_start=0.15)
    ctc = nn.CTCLoss(blank=0, zero_infinity=True)
    scaler = torch.amp.GradScaler()
    best, hist, t0 = -1, [], time.time()
    for ep in range(1, a.epochs + 1):
        model.train(); tot = 0
        for x, y, yl, _, _ in train:
            with torch.autocast("cuda", dtype=torch.float16):
                logp = model(x.to(dev, non_blocking=True))
            logp = logp.float().permute(1, 0, 2)                   # (T, B, C)
            loss = ctc(logp, y, torch.full((x.size(0),), logp.size(0), dtype=torch.long), yl)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt); nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(opt); scaler.update(); sched.step()
            tot += loss.item()
        res, _ = evaluate(model, val, charset, dev)
        hist.append({"epoch": ep, "loss": tot / len(train), **{k: v for k, v in res["전체"].items()}})
        print(f"epoch {ep:>2}/{a.epochs}  loss {tot / len(train):.4f}  val 전체 일치 {res['전체']['exact']:.4f}  "
              f"CER {res['전체']['cer']:.4f}  ({(time.time() - t0) / 60:.1f}분)", flush=True)
        if res["전체"]["exact"] > best:
            best = res["전체"]["exact"]
            torch.save({"model": model.state_dict(), "tokens": charset.tokens, "h": H_IN, "w": W_IN}, out / "best.pt")
        (out / "history.json").write_text(json.dumps(hist, ensure_ascii=False, indent=1))

    model.load_state_dict(torch.load(out / "best.pt", map_location=dev)["model"])
    res, wrong = evaluate(model, test, charset, dev, show=30)
    (out / "test.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"\n[test] best val {best:.4f} 모델")
    for k in sorted(res, key=lambda k: (k != "전체", k)):
        print(f"  {k:<10} {res[k]['n']:>6}장  전체 일치 {res[k]['exact']:.4f}  CER {res[k]['cer']:.4f}")
    print("틀린 예:")
    for t, p, k in wrong:
        print(f"  {k:<10} 정답 {t:<12} 예측 {p}")
    print(f"→ {out}/best.pt  ({(time.time() - t0) / 60:.1f}분)")


if __name__ == "__main__":
    main()
