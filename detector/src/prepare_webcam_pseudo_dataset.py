#!/usr/bin/env python3
"""Create a small YOLO detection set from reviewed webcam capture metadata.

The capture tool stores the source frame and detector boxes together.  This
script keeps one highest-confidence plate box per frame, stratifies by the
expected plate, and reserves the chronologically latest examples for
validation.  It is intended for camera-domain adaptation, not OCR training.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--balanced-root", type=Path, required=True,
                        help="dataset containing balanced_train.txt and balanced_val.txt")
    parser.add_argument("--min-confidence", type=float, default=0.30)
    parser.add_argument("--val-ratio", type=float, default=0.20)
    parser.add_argument("--webcam-repeat", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    grouped: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    for metadata_path in sorted(args.captures.glob("*/metadata.json")):
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        candidates = [plate for plate in data.get("plates", [])
                      if plate.get("box") and
                      float(plate.get("detection_confidence", 0)) >= args.min_confidence]
        if not candidates:
            continue
        plate = max(candidates, key=lambda item: float(item["detection_confidence"]))
        expected = str(plate.get("expected_plate", "")).strip()
        frame = metadata_path.parent / "frame_raw.jpg"
        if expected and frame.exists():
            grouped[expected].append((frame, plate))

    output = args.output.resolve()
    counts = defaultdict(int)
    plate_counts: dict[str, dict[str, int]] = {}
    for expected, samples in sorted(grouped.items()):
        samples.sort(key=lambda item: item[0].parent.name)
        val_count = max(1, round(len(samples) * args.val_ratio))
        split_at = max(1, len(samples) - val_count)
        plate_counts[expected] = {"train": split_at, "val": len(samples) - split_at}
        for index, (frame, plate) in enumerate(samples):
            split = "train" if index < split_at else "val"
            with Image.open(frame) as image:
                width, height = image.size
            x1, y1, x2, y2 = map(float, plate["box"])
            x1, x2 = max(0.0, x1), min(float(width), x2)
            y1, y2 = max(0.0, y1), min(float(height), y2)
            if x2 <= x1 or y2 <= y1:
                continue
            stem = frame.parent.name
            image_target = output / "images" / split / f"{stem}.jpg"
            label_target = output / "labels" / split / f"{stem}.txt"
            image_target.parent.mkdir(parents=True, exist_ok=True)
            label_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(frame, image_target)
            xc = (x1 + x2) / (2 * width)
            yc = (y1 + y2) / (2 * height)
            bw = (x2 - x1) / width
            bh = (y2 - y1) / height
            label_target.write_text(
                f"0 {xc:.8f} {yc:.8f} {bw:.8f} {bh:.8f}\n", encoding="utf-8")
            counts[split] += 1

    (output / "webcam.yaml").write_text(
        f"path: {output}\ntrain: images/train\nval: images/val\nnames:\n  0: plate\n",
        encoding="utf-8")
    balanced_train = [line for line in
                      (args.balanced_root / "balanced_train.txt").read_text().splitlines()
                      if line]
    balanced_val = [line for line in
                    (args.balanced_root / "balanced_val.txt").read_text().splitlines()
                    if line]
    webcam_train = sorted(str(path.resolve()) for path in (output / "images/train").glob("*.jpg"))
    webcam_val = sorted(str(path.resolve()) for path in (output / "images/val").glob("*.jpg"))
    adapt_train = balanced_train + webcam_train * args.webcam_repeat
    adapt_val = balanced_val + webcam_val
    (output / "adapt_train.txt").write_text("\n".join(adapt_train) + "\n", encoding="utf-8")
    (output / "adapt_val.txt").write_text("\n".join(adapt_val) + "\n", encoding="utf-8")
    (output / "adapt.yaml").write_text(
        f"path: {output}\ntrain: adapt_train.txt\nval: adapt_val.txt\nnames:\n  0: plate\n",
        encoding="utf-8")
    report = {
        "source_captures": str(args.captures.resolve()),
        "minimum_confidence": args.min_confidence,
        "split_method": "chronological latest-per-expected-plate validation",
        "webcam_images": dict(counts),
        "per_plate": plate_counts,
        "webcam_repeat": args.webcam_repeat,
        "adapt_train_entries": len(adapt_train),
        "adapt_val_entries": len(adapt_val),
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
