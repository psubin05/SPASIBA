#!/usr/bin/env python3
"""Evaluate an exported PlateCTC ONNX model using the same plate metrics."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import onnxruntime as ort
import torch
from torch.utils.data import DataLoader

from evaluate_ctc_ocr import ratio_metrics
from ocr_common import decode_regions
from train_ctc_ocr import OCRDataset, collate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--split", choices=("val", "test"), default="test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def decode(outputs, characters: list[str]) -> list[str]:
    results = []
    for sequence in outputs.argmax(-1):
        result, previous = [], -1
        for index in sequence.tolist():
            if index != 0 and index != previous:
                result.append(characters[index - 1])
            previous = index
        results.append(decode_regions("".join(result)))
    return results


def main() -> None:
    args = parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    characters = metadata["characters"]
    charset = {char: index + 1 for index, char in enumerate(characters)}
    dataset = OCRDataset(args.data, args.data / f"{args.split}.tsv", charset, False,
                         metadata["width"], metadata["height"])
    loader = DataLoader(dataset, args.batch, shuffle=False, num_workers=args.workers,
                        collate_fn=collate, persistent_workers=args.workers > 0)
    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    rows, offset = [], 0
    for images, _, _, texts, plate_ids, plate_types in loader:
        predictions = decode(session.run(None, {"images": images.numpy()})[0], characters)
        for prediction, target, plate_id, plate_type in zip(
                predictions, texts, plate_ids, plate_types):
            relative = dataset.rows[offset][0]
            offset += 1
            rows.append((relative, prediction, decode_regions(target), plate_id, plate_type))
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[0].rsplit("__L", 1)[0]].append(row)
    line_pairs = [(row[1], row[2]) for row in rows]
    plate_pairs, by_type = [], defaultdict(list)
    for parts in grouped.values():
        parts.sort(key=lambda row: row[0])
        pair = ("".join(part[1] for part in parts), parts[0][3])
        plate_pairs.append(pair)
        by_type[parts[0][4]].append(pair)
    metrics = {
        "model": str(args.model), "split": args.split,
        "line": ratio_metrics(line_pairs), "plate": ratio_metrics(plate_pairs),
        "by_type": {name: ratio_metrics(pairs) for name, pairs in sorted(by_type.items())},
    }
    args.output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
