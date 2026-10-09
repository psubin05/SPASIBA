#!/usr/bin/env python3
"""Validate X-AnyLabeling LabelMe polygons, group-split, and convert OBB to YOLO AABB."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--labels", type=Path, nargs="+", required=True,
                        help="Directories containing X-AnyLabeling LabelMe JSON files")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--eval-count", type=int, default=300)
    parser.add_argument("--label-name", default="plate")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.selection.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    labels = {p.stem: p for root in args.labels for p in root.rglob("*.json")}
    missing = [Path(row["source"]).stem for row in rows if Path(row["source"]).stem not in labels]
    if missing:
        raise RuntimeError(f"Missing {len(missing)} labels, e.g. {missing[:5]}")

    # Stable, plate-ID-level holdout. One selected image already exists per ID.
    ordered = sorted(rows, key=lambda row: hashlib.sha1(row["plate_id"].encode()).hexdigest())
    eval_ids = {row["plate_id"] for row in ordered[:args.eval_count]}
    report = {"train": 0, "eval": 0, "empty": 0, "boxes": 0}
    for row in rows:
        source = Path(row["source"])
        split = "eval" if row["plate_id"] in eval_ids else "train"
        out_image = args.output / "images" / split / source.name
        out_label = args.output / "labels" / split / f"{source.stem}.txt"
        out_image.parent.mkdir(parents=True, exist_ok=True)
        out_label.parent.mkdir(parents=True, exist_ok=True)
        if not out_image.exists():
            out_image.hardlink_to(source.resolve())
        annotation = json.loads(labels[source.stem].read_text(encoding="utf-8"))
        with Image.open(source) as image:
            width, height = image.size
        yolo = []
        for shape in annotation.get("shapes", []):
            if shape.get("label") != args.label_name:
                continue
            points = shape.get("points", [])
            if len(points) < 4:
                raise ValueError(f"{labels[source.stem]}: plate needs four polygon/rotation points")
            xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]
            x1, x2 = max(0.0, min(xs)), min(float(width), max(xs))
            y1, y2 = max(0.0, min(ys)), min(float(height), max(ys))
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"{labels[source.stem]}: invalid plate polygon")
            yolo.append(f"0 {(x1+x2)/2/width:.6f} {(y1+y2)/2/height:.6f} "
                        f"{(x2-x1)/width:.6f} {(y2-y1)/height:.6f}")
        out_label.write_text("\n".join(yolo) + ("\n" if yolo else ""), encoding="utf-8")
        report[split] += 1
        report["boxes"] += len(yolo)
        report["empty"] += not yolo
    (args.output / "data.yaml").write_text(
        f"path: {args.output.resolve()}\ntrain: images/train\nval: images/eval\nnames:\n  0: plate\n",
        encoding="utf-8",
    )
    (args.output / "split_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

