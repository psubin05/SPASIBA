#!/usr/bin/env python3
"""Evaluate a trained CTC recognizer by line, whole plate and plate type."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from ocr_common import decode_regions
from train_ctc_ocr import OCRDataset, PlateCTC, collate, edit_distance, greedy_decode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "val", "test"), default="test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--augment", choices=("none", "mild", "strong"), default="none",
                        help="apply a deterministic stress augmentation during evaluation")
    parser.add_argument("--seed", type=int, default=103)
    return parser.parse_args()


def ratio_metrics(pairs: list[tuple[str, str]]) -> dict[str, float | int]:
    exact = sum(prediction == target for prediction, target in pairs)
    edits = sum(edit_distance(prediction, target) for prediction, target in pairs)
    chars = sum(len(target) for _, target in pairs)
    return {
        "count": len(pairs),
        "exact": exact / max(1, len(pairs)),
        "cer": edits / max(1, chars),
    }


@torch.no_grad()
def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    checkpoint = torch.load(args.weights, map_location="cpu", weights_only=False)
    characters = checkpoint["characters"]
    charset = {char: index + 1 for index, char in enumerate(characters)}
    use_augmentation = args.augment != "none"
    dataset = OCRDataset(args.data, args.data / f"{args.split}.tsv", charset,
                         use_augmentation, checkpoint["width"], checkpoint["height"],
                         augment=args.augment)
    loader = DataLoader(dataset, args.batch, shuffle=False, num_workers=args.workers,
                        pin_memory=True, collate_fn=collate,
                        persistent_workers=args.workers > 0)
    device = torch.device(args.device)
    model = PlateCTC(len(characters) + 1).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    line_pairs: list[tuple[str, str]] = []
    rows = []
    offset = 0
    for images, _, _, texts, plate_ids, plate_types in loader:
        predictions = greedy_decode(model(images.to(device)).transpose(0, 1), characters)
        for prediction, target, plate_id, plate_type in zip(
                predictions, texts, plate_ids, plate_types):
            relative = dataset.rows[offset][0]
            offset += 1
            line_pairs.append((decode_regions(prediction), decode_regions(target)))
            rows.append((relative, decode_regions(prediction), decode_regions(target),
                         plate_id, plate_type))

    grouped: dict[str, list[tuple[str, str, str, str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row[0].rsplit("__L", 1)[0]].append(row)
    plate_pairs: list[tuple[str, str]] = []
    by_type: dict[str, list[tuple[str, str]]] = defaultdict(list)
    prediction_rows = []
    for key, parts in grouped.items():
        parts.sort(key=lambda row: row[0])
        prediction = "".join(part[1] for part in parts)
        target = parts[0][3]
        plate_type = parts[0][4]
        pair = (prediction, target)
        plate_pairs.append(pair)
        by_type[plate_type].append(pair)
        prediction_rows.append((key, prediction, target, plate_type,
                                str(int(prediction == target))))

    metrics = {
        "split": args.split,
        "augmentation": args.augment,
        "line": ratio_metrics(line_pairs),
        "plate": ratio_metrics(plate_pairs),
        "by_type": {name: ratio_metrics(pairs) for name, pairs in sorted(by_type.items())},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    predictions_path = args.output.with_suffix(".predictions.tsv")
    with predictions_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(("image", "prediction", "target", "plate_type", "exact"))
        writer.writerows(prediction_rows)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
