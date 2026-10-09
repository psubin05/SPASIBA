#!/usr/bin/env python3
"""Train a compact anisotropic CNN + BiGRU CTC recognizer for Korean plates."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import ColorJitter, GaussianBlur, RandomAffine, RandomPerspective
from torchvision.transforms import functional as TF
from tqdm import tqdm

from ocr_common import decode_regions


class DepthwiseBlock(nn.Module):
    def __init__(self, source: int, target: int, stride: tuple[int, int]):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(source, source, 3, stride=stride, padding=1, groups=source, bias=False),
            nn.BatchNorm2d(source), nn.SiLU(),
            nn.Conv2d(source, target, 1, bias=False), nn.BatchNorm2d(target), nn.SiLU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class PlateCTC(nn.Module):
    def __init__(self, classes: int):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, stride=(2, 2), padding=1, bias=False), nn.BatchNorm2d(32), nn.SiLU(),
            DepthwiseBlock(32, 48, (2, 2)),
            DepthwiseBlock(48, 64, (2, 1)),
            DepthwiseBlock(64, 96, (2, 1)),
            DepthwiseBlock(96, 128, (2, 1)),
        )
        self.sequence = nn.GRU(128, 128, num_layers=2, dropout=0.1, bidirectional=True, batch_first=True)
        self.classifier = nn.Linear(256, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.features(x).mean(dim=2).transpose(1, 2)
        sequence, _ = self.sequence(features)
        return self.classifier(sequence).log_softmax(dim=-1)


class OCRDataset(Dataset):
    def __init__(self, root: Path, index: Path, charset: dict[str, int], train: bool,
                 width: int, height: int, limit: int = 0, augment: str = "mild"):
        self.root, self.charset, self.train, self.width, self.height = root, charset, train, width, height
        with index.open(encoding="utf-8") as handle:
            self.rows = list(csv.reader(handle, delimiter="\t"))
        if limit:
            self.rows = self.rows[:limit]
        self.augment = augment
        if augment == "strong":
            self.perspective = RandomPerspective(0.30, p=0.65)
            self.affine = RandomAffine(12, translate=(0.06, 0.08), scale=(0.80, 1.20), shear=7)
            self.color = ColorJitter(brightness=.45, contrast=.45, saturation=.25, hue=.04)
        else:
            self.perspective = RandomPerspective(0.15, p=0.25)
            self.affine = RandomAffine(7, translate=(0.03, 0.04), scale=(0.90, 1.10), shear=3)
            self.color = ColorJitter(brightness=.25, contrast=.25, saturation=.15, hue=.02)
        self.blur = GaussianBlur(3, sigma=(0.1, 1.0))

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        relative, text, plate_id, plate_type = self.rows[index]
        with Image.open(self.root / relative) as opened:
            image = opened.convert("RGB")
        if self.train and self.augment != "none":
            image = self.perspective(image)
            if self.augment == "strong" or random.random() < .50:
                image = self.affine(image)
            if self.augment == "strong" or random.random() < .60:
                image = self.color(image)
            if random.random() < (.25 if self.augment == "strong" else .15):
                image = self.blur(image)
        scale = min(self.width / image.width, self.height / image.height)
        resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
        canvas = Image.new("RGB", (self.width, self.height), (127, 127, 127))
        canvas.paste(resized, ((self.width - resized.width) // 2, (self.height - resized.height) // 2))
        tensor = TF.to_tensor(canvas)
        tensor = TF.normalize(tensor, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
        target = torch.tensor([self.charset[char] for char in text], dtype=torch.long)
        return tensor, target, text, plate_id, plate_type


def collate(batch):
    images, targets, texts, plate_ids, plate_types = zip(*batch)
    lengths = torch.tensor([len(target) for target in targets], dtype=torch.long)
    return torch.stack(images), torch.cat(targets), lengths, texts, plate_ids, plate_types


def greedy_decode(log_probs: torch.Tensor, characters: list[str]) -> list[str]:
    indices = log_probs.argmax(-1).transpose(0, 1).cpu().tolist()
    decoded = []
    for sequence in indices:
        result, previous = [], -1
        for index in sequence:
            if index != 0 and index != previous:
                result.append(characters[index - 1])
            previous = index
        decoded.append("".join(result))
    return decoded


def edit_distance(left: str, right: str) -> int:
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        new = [i]
        for j, b in enumerate(right, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = new
    return row[-1]


@torch.no_grad()
def evaluate(model, loader, characters, device):
    model.eval(); exact = total = edits = chars = 0
    for images, _, _, texts, _, _ in loader:
        predictions = greedy_decode(model(images.to(device)).transpose(0, 1), characters)
        for prediction, target in zip(predictions, texts):
            exact += prediction == target; total += 1
            edits += edit_distance(prediction, target); chars += len(target)
    return {"exact": exact / max(total, 1), "cer": edits / max(chars, 1)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--width", type=int, default=192)
    parser.add_argument("--height", type=int, default=48)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--augment", choices=("none", "mild", "strong"), default="mild")
    parser.add_argument("--init", type=Path,
                        help="initialize model weights from a PlateCTC checkpoint")
    parser.add_argument("--train-limit", type=int, default=0,
                        help="use only this many training rows (0 means all; useful for smoke tests)")
    parser.add_argument("--val-limit", type=int, default=0,
                        help="use only this many validation rows (0 means all)")
    return parser.parse_args()


def main() -> None:
    args = parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    train_rows = list(csv.reader((args.data / "train.tsv").open(encoding="utf-8"), delimiter="\t"))
    characters = sorted({char for row in train_rows for char in row[1]})
    charset = {char: index + 1 for index, char in enumerate(characters)}
    (args.output / "charset.json").write_text(json.dumps(characters, ensure_ascii=False), encoding="utf-8")
    train_data = OCRDataset(args.data, args.data / "train.tsv", charset, True, args.width,
                            args.height, args.train_limit, args.augment)
    val_data = OCRDataset(args.data, args.data / "val.tsv", charset, False, args.width,
                          args.height, args.val_limit)
    train_loader = DataLoader(train_data, args.batch, shuffle=True, num_workers=args.workers,
                              pin_memory=True, collate_fn=collate, persistent_workers=args.workers > 0)
    val_loader = DataLoader(val_data, args.batch, shuffle=False, num_workers=args.workers,
                            pin_memory=True, collate_fn=collate, persistent_workers=args.workers > 0)
    device = torch.device(args.device); model = PlateCTC(len(characters) + 1).to(device)
    if args.init:
        initial = torch.load(args.init, map_location="cpu", weights_only=False)
        if initial["characters"] != characters:
            raise ValueError("initial checkpoint charset differs from this dataset")
        model.load_state_dict(initial["model"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, args.epochs)
    criterion = nn.CTCLoss(blank=0, zero_infinity=True)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    history, best_exact = [], -1.0
    for epoch in range(1, args.epochs + 1):
        model.train(); loss_sum = 0.0
        bar = tqdm(train_loader, desc=f"epoch {epoch}/{args.epochs}")
        for images, targets, target_lengths, _, _, _ in bar:
            images, targets = images.to(device, non_blocking=True), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                output = model(images).transpose(0, 1)
                input_lengths = torch.full((images.size(0),), output.size(0), dtype=torch.long)
                loss = criterion(output, targets, input_lengths, target_lengths)
            scaler.scale(loss).backward(); scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer); scaler.update()
            loss_sum += float(loss.item()); bar.set_postfix(loss=f"{loss.item():.3f}")
        scheduler.step(); metrics = evaluate(model, val_loader, characters, device)
        record = {"epoch": epoch, "loss": loss_sum / max(len(train_loader), 1), **metrics}
        history.append(record); print(json.dumps(record))
        checkpoint = {"model": model.state_dict(), "characters": characters,
                      "width": args.width, "height": args.height, "metrics": metrics,
                      "augment": args.augment, "epoch": epoch}
        torch.save(checkpoint, args.output / "last.pt")
        if metrics["exact"] > best_exact:
            best_exact = metrics["exact"]; torch.save(checkpoint, args.output / "best.pt")
        (args.output / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    print("best_exact", best_exact)


if __name__ == "__main__":
    main()
