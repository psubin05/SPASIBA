#!/usr/bin/env python3
"""Select unique Korean plates for manual OBB labeling and make four mixed bundles."""

from __future__ import annotations

import argparse
import colorsys
import csv
import json
import random
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageStat
from tqdm import tqdm


TARGETS = {"white_long": 1000, "yellow_long": 400, "yellow_two_line": 300, "green_other": 300}


def plate_number(stem: str) -> str:
    return re.sub(r"-\d+$", "", stem)


def dominant_bucket(path: Path) -> tuple[str, float, tuple[float, float, float]]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        ratio = rgb.width / max(rgb.height, 1)
        # Center-heavy crop avoids most bumper/background pixels.
        x1, y1, x2, y2 = int(rgb.width*.12), int(rgb.height*.12), int(rgb.width*.88), int(rgb.height*.88)
        thumb = rgb.crop((x1, y1, x2, y2)).resize((32, 16))
        hsv = [colorsys.rgb_to_hsv(r/255, g/255, b/255) for r, g, b in thumb.getdata()]
        yellow = sum(0.10 <= h <= 0.19 and s >= 0.30 and v >= 0.25 for h, s, v in hsv) / len(hsv)
        green = sum(0.20 <= h <= 0.48 and s >= 0.22 and v >= 0.18 for h, s, v in hsv) / len(hsv)
        mean = tuple(round(v, 1) for v in ImageStat.Stat(thumb).mean)
    two_line = ratio < 1.75
    if yellow >= 0.18:
        return ("yellow_two_line" if two_line else "yellow_long"), ratio, mean
    if green >= 0.12 or two_line:
        return "green_other", ratio, mean
    return "white_long", ratio, mean


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--labels-zip", type=Path, help="OCR label ZIP; value is used for exact deduplication")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=103)
    parser.add_argument("--bundle-count", type=int, default=4)
    parser.add_argument("--copy", action="store_true", help="Copy instead of space-saving hard links")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    value_by_name: dict[str, str] = {}
    if args.labels_zip:
        with zipfile.ZipFile(args.labels_zip) as zf:
            for name in tqdm([n for n in zf.namelist() if n.endswith(".json")], desc="reading OCR labels"):
                record = json.loads(zf.read(name))
                value_by_name[PurePosixPath(record["imagePath"]).name] = record.get("value", "")

    by_number: dict[str, list[Path]] = {}
    for path in args.images.iterdir():
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        number = value_by_name.get(path.name) or plate_number(path.stem)
        by_number.setdefault(number, []).append(path)
    representatives = [rng.choice(paths) for _, paths in sorted(by_number.items())]

    buckets = {key: [] for key in TARGETS}
    metadata = {}
    for path in tqdm(representatives, desc="classifying"):
        bucket, ratio, mean = dominant_bucket(path)
        buckets[bucket].append(path)
        metadata[path.name] = {"plate_id": value_by_name.get(path.name) or plate_number(path.stem),
                               "bucket": bucket, "ratio": round(ratio, 3), "mean_rgb": mean}
    for values in buckets.values():
        rng.shuffle(values)

    selected: list[Path] = []
    shortages = 0
    for bucket, target in TARGETS.items():
        take = min(target, len(buckets[bucket]))
        selected.extend(buckets[bucket][:take])
        shortages += target - take
    used = set(selected)
    if shortages:
        fallback = [p for p in buckets["white_long"] if p not in used]
        selected.extend(fallback[:shortages])
    if len(selected) != sum(TARGETS.values()):
        raise RuntimeError(f"Could select only {len(selected)} unique plates")

    rng.shuffle(selected)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, source in enumerate(selected):
        bundle = index % args.bundle_count + 1
        destination = args.output / f"bundle_{bundle}" / "images" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination) if args.copy else destination.hardlink_to(source.resolve())
        row = {"bundle": bundle, "source": str(source.resolve()), **metadata[source.name]}
        rows.append(row)
    with (args.output / "selection.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(rows)
    summary = {key: sum(metadata[p.name]["bucket"] == key for p in selected) for key in TARGETS}
    (args.output / "summary.json").write_text(json.dumps({"selected": len(selected), "buckets": summary},
                                                          ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": len(selected), "buckets": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()

