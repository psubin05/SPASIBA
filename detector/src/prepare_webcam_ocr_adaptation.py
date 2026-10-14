#!/usr/bin/env python3
"""Build CTC line crops from webcam detector labels and known plate text."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from PIL import Image

from ocr_common import encode_regions, split_two_line


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webcam-detect", type=Path, required=True)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--base-ocr", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--webcam-repeat", type=int, default=20)
    parser.add_argument("--split-overlap", type=float, default=0.04)
    return parser.parse_args()


def read_base_rows(root: Path, split: str) -> list[list[str]]:
    rows = []
    with (root / f"{split}.tsv").open(encoding="utf-8") as handle:
        for relative, text, plate_id, plate_type in csv.reader(handle, delimiter="\t"):
            rows.append([str((root / relative).resolve()), text, plate_id, plate_type])
    return rows


def expected_text(captures: Path, stem: str) -> str:
    metadata = json.loads((captures / stem / "metadata.json").read_text(encoding="utf-8"))
    for plate in metadata.get("plates", []):
        expected = str(plate.get("expected_plate", "")).strip()
        if expected:
            return expected
    raise ValueError(f"expected plate missing: {stem}")


def make_webcam_rows(args: argparse.Namespace, split: str) -> list[list[str]]:
    rows = []
    image_dir = args.webcam_detect / "images" / split
    label_dir = args.webcam_detect / "labels" / split
    target_dir = args.output / "images" / f"webcam_{split}"
    target_dir.mkdir(parents=True, exist_ok=True)
    for frame_path in sorted(image_dir.glob("*.jpg")):
        expected = expected_text(args.captures, frame_path.stem)
        fields = [float(value) for value in
                  (label_dir / f"{frame_path.stem}.txt").read_text().split()]
        _, xc, yc, bw, bh = fields
        with Image.open(frame_path) as opened:
            frame = opened.convert("RGB")
        left = max(0, round((xc - bw / 2) * frame.width))
        right = min(frame.width, round((xc + bw / 2) * frame.width))
        top = max(0, round((yc - bh / 2) * frame.height))
        bottom = min(frame.height, round((yc + bh / 2) * frame.height))
        plate = frame.crop((left, top, right, bottom))
        ratio = plate.width / max(1, plate.height)
        if ratio < 2.6:
            texts = split_two_line(expected)
            cut = plate.height // 2
            overlap = max(1, round(plate.height * args.split_overlap))
            images = [plate.crop((0, 0, plate.width, min(plate.height, cut + overlap))),
                      plate.crop((0, max(0, cut - overlap), plate.width, plate.height))]
            plate_type = "webcam_tall"
        else:
            texts, images, plate_type = (encode_regions(expected),), (plate,), "webcam_long"
        for line_index, (image, text) in enumerate(zip(images, texts)):
            target = target_dir / f"{frame_path.stem}__L{line_index}.jpg"
            image.save(target, quality=95)
            rows.append([str(target.resolve()), text, expected, plate_type])
    return rows


def write_rows(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerows(rows)


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base_train = read_base_rows(args.base_ocr, "train")
    base_val = read_base_rows(args.base_ocr, "val")
    base_test = read_base_rows(args.base_ocr, "test")
    webcam_train = make_webcam_rows(args, "train")
    webcam_val = make_webcam_rows(args, "val")
    write_rows(args.output / "train.tsv", base_train + webcam_train * args.webcam_repeat)
    write_rows(args.output / "val.tsv", base_val + webcam_val)
    write_rows(args.output / "test.tsv", base_test)
    write_rows(args.output / "webcam_train.tsv", webcam_train)
    write_rows(args.output / "webcam_val.tsv", webcam_val)
    report = {
        "base_train_lines": len(base_train),
        "base_val_lines": len(base_val),
        "webcam_train_lines": len(webcam_train),
        "webcam_val_lines": len(webcam_val),
        "webcam_repeat": args.webcam_repeat,
        "combined_train_lines": len(base_train) + len(webcam_train) * args.webcam_repeat,
        "combined_val_lines": len(base_val) + len(webcam_val),
    }
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
