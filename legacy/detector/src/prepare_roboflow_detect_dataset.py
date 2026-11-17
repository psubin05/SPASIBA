#!/usr/bin/env python3
"""Merge Roboflow Korean plate exports into a leak-free YOLO detect dataset.

The source exports mix segmentation polygons and ordinary bounding boxes.  This
script collapses every source class to ``plate``, converts polygons to their
axis-aligned bounds, groups augmented copies by the pre-``.rf.`` source name,
and deterministically assigns the whole group to one split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def group_split(source_name: str, train_ratio: float, val_ratio: float) -> str:
    value = int(hashlib.sha1(source_name.encode("utf-8")).hexdigest(), 16) / 2**160
    if value < train_ratio:
        return "train"
    if value < train_ratio + val_ratio:
        return "val"
    return "test"


def convert_label(source: Path) -> tuple[list[str], int]:
    converted, polygon_count = [], 0
    for line in source.read_text(encoding="utf-8").splitlines():
        values = [float(value) for value in line.split()]
        if len(values) < 5 or len(values) % 2 == 0:
            raise ValueError(f"invalid YOLO row in {source}: {line}")
        coordinates = values[1:]
        if len(values) == 5:
            x, y, width, height = coordinates
        else:
            polygon_count += 1
            xs, ys = coordinates[0::2], coordinates[1::2]
            left, right = min(xs), max(xs)
            top, bottom = min(ys), max(ys)
            x, y = (left + right) / 2, (top + bottom) / 2
            width, height = right - left, bottom - top
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1):
            raise ValueError(f"out-of-range YOLO row in {source}: {line}")
        converted.append(f"0 {x:.8f} {y:.8f} {width:.8f} {height:.8f}")
    return converted, polygon_count


def materialize(source: Path, target: Path) -> None:
    """Copy an image so Ultralytics pairs it with the converted local label.

    Ultralytics resolves symlinks before deriving label paths, which would make
    it silently read the original multi-class/polygon label instead.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    if not target.exists():
        shutil.copy2(source, target)


def image_paths(directory: Path) -> list[Path]:
    return sorted(path.resolve() for path in directory.iterdir()
                  if path.suffix.lower() in IMAGE_SUFFIXES)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", type=Path,
                        help="existing YOLO detect dataset with images/train and images/val")
    parser.add_argument("--external-repeat", type=int, default=1)
    parser.add_argument("--balanced-base-ratio", type=float, default=1.0,
                        help="base/external entry ratio for balanced train and val lists")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.80)
    parser.add_argument("--val-ratio", type=float, default=0.10)
    args = parser.parse_args()
    if args.external_repeat < 1:
        raise ValueError("--external-repeat must be at least one")
    if args.balanced_base_ratio <= 0:
        raise ValueError("--balanced-base-ratio must be positive")
    if args.train_ratio + args.val_ratio >= 1:
        raise ValueError("train + val ratios must be below one")

    output = args.output.resolve()
    counts, groups, polygons = Counter(), defaultdict(set), 0
    skipped_empty = []
    for source_root in args.sources:
        source_root = source_root.resolve()
        dataset_name = source_root.name
        license_source = source_root / "README.roboflow.txt"
        if license_source.exists():
            license_target = output / "licenses" / f"{dataset_name}.README.roboflow.txt"
            license_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(license_source, license_target)
        for original_split in ("train", "valid", "test"):
            for image in image_paths(source_root / original_split / "images"):
                label = source_root / original_split / "labels" / f"{image.stem}.txt"
                if not label.exists():
                    raise FileNotFoundError(label)
                rows, polygon_count = convert_label(label)
                if not rows:
                    skipped_empty.append(str(image))
                    continue
                source_name = image.name.split(".rf.")[0]
                split = group_split(source_name, args.train_ratio, args.val_ratio)
                unique_stem = f"{dataset_name}__{original_split}__{image.stem}"
                target_image = output / "images" / split / f"{unique_stem}{image.suffix.lower()}"
                target_label = output / "labels" / split / f"{unique_stem}.txt"
                materialize(image, target_image)
                target_label.parent.mkdir(parents=True, exist_ok=True)
                target_label.write_text("\n".join(rows) + "\n", encoding="utf-8")
                counts[split] += 1
                groups[split].add(source_name)
                polygons += polygon_count

    overlap = {f"{a}_{b}": len(groups[a] & groups[b])
               for a, b in (("train", "val"), ("train", "test"), ("val", "test"))}
    report = {
        "images": dict(counts),
        "source_groups": {split: len(names) for split, names in groups.items()},
        "group_overlap": overlap,
        "polygon_rows_converted": polygons,
        "empty_positive_labels_excluded": skipped_empty,
        "class": "plate",
    }
    (output / "preparation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "external.yaml").write_text(
        f"path: {output}\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n  0: plate\n", encoding="utf-8")

    if args.base:
        base = args.base.resolve()
        train = image_paths(base / "images" / "train")
        external_train = image_paths(output / "images" / "train")
        base_val = image_paths(base / "images" / "val")
        external_val = image_paths(output / "images" / "val")
        val = base_val + external_val
        (output / "combined_train.txt").write_text(
            "\n".join(map(str, train + external_train * args.external_repeat)) + "\n",
            encoding="utf-8")
        (output / "combined_val.txt").write_text(
            "\n".join(map(str, val)) + "\n", encoding="utf-8")
        (output / "combined.yaml").write_text(
            f"path: {output}\ntrain: combined_train.txt\nval: combined_val.txt\n"
            "names:\n  0: plate\n", encoding="utf-8")
        report["combined_train_entries"] = len(train) + len(external_train) * args.external_repeat
        report["combined_val_entries"] = len(val)

        # A very large base dataset can hide a complete external-domain failure
        # in aggregate metrics.  These deterministic lists give both domains
        # equal influence while retaining separate domain-specific evaluations.
        rng = random.Random(args.seed)
        balanced_train_base_count = min(
            len(train), round(len(external_train) * args.balanced_base_ratio))
        balanced_val_base_count = min(
            len(base_val), round(len(external_val) * args.balanced_base_ratio))
        balanced_train = external_train + rng.sample(train, balanced_train_base_count)
        balanced_val = external_val + rng.sample(base_val, balanced_val_base_count)
        rng.shuffle(balanced_train)
        rng.shuffle(balanced_val)
        (output / "balanced_train.txt").write_text(
            "\n".join(map(str, balanced_train)) + "\n", encoding="utf-8")
        (output / "balanced_val.txt").write_text(
            "\n".join(map(str, balanced_val)) + "\n", encoding="utf-8")
        (output / "balanced.yaml").write_text(
            f"path: {output}\ntrain: balanced_train.txt\nval: balanced_val.txt\n"
            "names:\n  0: plate\n", encoding="utf-8")
        report["balanced_seed"] = args.seed
        report["balanced_base_ratio"] = args.balanced_base_ratio
        report["balanced_train_entries"] = len(balanced_train)
        report["balanced_val_entries"] = len(balanced_val)
        (output / "preparation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
