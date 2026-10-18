"""외부 사전학습 모델 파인튜닝 — team-lucid/trocr-small-korean (Apache 2.0)

왜 이걸 가져왔나
  우리 학습 데이터는 5.5만 장이다. 이 모델은 SynthTIGER로 만든 한국어 텍스트
  600만 장으로 이미 학습돼 있어서, 한글 글자 모양에 대한 지식이 비교가 안 되게 많다.
  기대: 어/고, 모/오 처럼 생김새가 비슷해서 틀리는 오류에 강할 것.

  python train_trocr.py --epochs 4 --batch 12
  python train_trocr.py --eval-only --init runs/trocr/best.pt
"""
import argparse, json, random, sys, time
from collections import defaultdict
from pathlib import Path
import cv2, numpy as np, torch
from torch.utils.data import DataLoader, Dataset
from transformers import VisionEncoderDecoderModel, TrOCRProcessor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "ocr"))
from train_ocr import augment, edit

DATA = HERE.parents[2] / "data" / "ocr_v1"
MODEL = "team-lucid/trocr-small-korean"


class Plates(Dataset):
    def __init__(self, split, proc, aug=None, limit=0):
        rows = [l.split("\t") for l in (DATA / f"{split}.tsv").read_text(encoding="utf-8").splitlines()]
        if limit:
            random.Random(0).shuffle(rows); rows = rows[:limit]
        self.rows, self.proc, self.aug = rows, proc, aug

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        rel, text, kind, nl = self.rows[i]
        img = cv2.imread(str(DATA / rel))
        if self.aug:
            img = augment(img, self.aug)
        px = self.proc(images=cv2.cvtColor(img, cv2.COLOR_BGR2RGB), return_tensors="pt").pixel_values[0]
        ids = self.proc.tokenizer(text, return_tensors="pt").input_ids[0]
        return px, ids, text, f"{kind}/{'2줄' if nl=='2' else '1줄'}"


def collate(b, pad):
    px, ids, tx, kd = zip(*b)
    n = max(len(i) for i in ids)
    lab = torch.full((len(ids), n), -100, dtype=torch.long)
    for j, i in enumerate(ids):
        lab[j, :len(i)] = i
    return torch.stack(px), lab, list(tx), list(kd)


@torch.no_grad()
def run_eval(model, loader, proc, dev, max_batches=0):
    model.eval()
    per = defaultdict(lambda: [0, 0, 0, 0])
    for n, (px, lab, texts, kinds) in enumerate(loader, 1):
        out = model.generate(px.to(dev), max_new_tokens=16, num_beams=1)
        preds = proc.tokenizer.batch_decode(out, skip_special_tokens=True)
        for p, t, k in zip(preds, texts, kinds):
            p = p.replace(" ", "")
            for key in ("전체", k):
                a = per[key]; a[0] += (p == t); a[1] += 1; a[2] += edit(p, t); a[3] += len(t)
        if max_batches and n >= max_batches:
            break
    return {k: {"exact": a[0]/a[1], "cer": a[2]/a[3], "n": a[1]} for k, a in per.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--train-limit", type=int, default=0)
    ap.add_argument("--init", default="")
    ap.add_argument("--eval-only", action="store_true")
    a = ap.parse_args()

    dev = "cuda"
    proc = TrOCRProcessor.from_pretrained(MODEL)
    model = VisionEncoderDecoderModel.from_pretrained(MODEL).to(dev)
    model.config.decoder_start_token_id = proc.tokenizer.cls_token_id or proc.tokenizer.bos_token_id
    model.config.pad_token_id = proc.tokenizer.pad_token_id
    if a.init:
        model.load_state_dict(torch.load(a.init, map_location=dev))
    print(f"{MODEL}  파라미터 {sum(p.numel() for p in model.parameters()):,}", flush=True)

    out = HERE.parent / "runs" / "trocr"; out.mkdir(parents=True, exist_ok=True)
    cf = lambda b: collate(b, proc.tokenizer.pad_token_id)
    mk = lambda s, aug, lim=0: DataLoader(Plates(s, proc, aug, lim), batch_size=a.batch,
                                          shuffle=(s == "train"), num_workers=8, collate_fn=cf, pin_memory=True)
    if a.eval_only:
        res = run_eval(model, mk("test", None), proc, dev)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        json.dump(res, open(out / "test.json", "w"), ensure_ascii=False, indent=1)
        return

    tl = mk("train", "mild", a.train_limit)
    vl = mk("val", None, 1200)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    sch = torch.optim.lr_scheduler.OneCycleLR(opt, a.lr, total_steps=a.epochs * len(tl), pct_start=0.1)
    scaler = torch.amp.GradScaler(dev)
    best, t0 = 0.0, time.time()
    for ep in range(1, a.epochs + 1):
        model.train(); tot = n = 0
        for px, lab, *_ in tl:
            px, lab = px.to(dev, non_blocking=True), lab.to(dev)
            with torch.amp.autocast(dev):
                loss = model(pixel_values=px, labels=lab).loss
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward(); scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt); scaler.update(); sch.step()
            tot += loss.item(); n += 1
            if n % 400 == 0:
                print(f"   ep{ep} {n}/{len(tl)} loss {tot/n:.4f} ({(time.time()-t0)/60:.1f}분)", flush=True)
        res = run_eval(model, vl, proc, dev)
        ex = res["전체"]["exact"]
        print(f"epoch {ep}/{a.epochs}  loss {tot/n:.4f}  val {ex*100:.2f}%  CER {res['전체']['cer']*100:.2f}%  ({(time.time()-t0)/60:.1f}분)", flush=True)
        if ex > best:
            best = ex; torch.save(model.state_dict(), out / "best.pt")
    print(f"\n최고 val {best*100:.2f}%  {(time.time()-t0)/60:.1f}분")


if __name__ == "__main__":
    main()
