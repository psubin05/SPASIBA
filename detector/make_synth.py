"""Replace blurred vehicle plate regions with sharp OCR training plate crops.

Source and destination splits remain separate. Generated labels retain the
original vehicle annotation; synthetic validation is only a diagnostic.
"""

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np


def read_box(path, width, height):
    line = path.read_text(encoding="utf-8").splitlines()[0].split()
    if len(line) != 5 or line[0] != "0":
        raise ValueError(f"Expected one plate label in {path}")
    cx, cy, bw, bh = map(float, line[1:])
    return (max(0, round((cx - bw / 2) * width)), max(0, round((cy - bh / 2) * height)),
            min(width, round((cx + bw / 2) * width)), min(height, round((cy + bh / 2) * height)))


def composite(vehicle, source, destination, source_box):
    x1, y1, x2, y2 = destination
    sx1, sy1, sx2, sy2 = source_box
    if x2 - x1 < 20 or y2 - y1 < 8 or sx2 <= sx1 or sy2 <= sy1:
        return None
    plate = source[sy1:sy2, sx1:sx2]
    if plate.size == 0:
        return None
    target = vehicle[y1:y2, x1:x2]
    plate = cv2.resize(plate, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
    # Preserve source colors; match only luminance to the vehicle plate area.
    src_lab = cv2.cvtColor(plate, cv2.COLOR_BGR2LAB).astype(np.float32)
    dst_lab = cv2.cvtColor(target, cv2.COLOR_BGR2LAB).astype(np.float32)
    src_mean = float(src_lab[:, :, 0].mean())
    dst_mean = float(dst_lab[:, :, 0].mean())
    src_lab[:, :, 0] = np.clip(src_lab[:, :, 0] + np.clip(dst_mean - src_mean, -35, 35), 0, 255)
    plate = cv2.cvtColor(src_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    feather = max(1, min(x2 - x1, y2 - y1) // 12)
    mask = np.ones((y2 - y1, x2 - x1), dtype=np.float32)
    mask[:feather, :] *= np.linspace(0, 1, feather)[:, None]
    mask[-feather:, :] *= np.linspace(1, 0, feather)[:, None]
    mask[:, :feather] *= np.linspace(0, 1, feather)[None, :]
    mask[:, -feather:] *= np.linspace(1, 0, feather)[None, :]
    result = vehicle.copy()
    result[y1:y2, x1:x2] = (plate * mask[:, :, None] + target * (1 - mask[:, :, None])).astype(np.uint8)
    return result


def create(args):
    rng = random.Random(args.seed)
    output = args.output.resolve()
    counts = {}
    for split, limit in (("train", args.train_limit), ("val", args.val_limit)):
        sources = sorted((args.sharp / "images" / split).glob("*.jpg"))
        vehicles = sorted((args.vehicle / "images" / split).glob("*.jpg"))
        if not sources or not vehicles:
            raise FileNotFoundError(f"Missing {split} images in source or vehicle dataset")
        rng.shuffle(vehicles)
        made = skipped = 0
        for vehicle_path in vehicles[:limit or None]:
            vehicle = cv2.imread(str(vehicle_path))
            if vehicle is None:
                skipped += 1
                continue
            vehicle_label = args.vehicle / "labels" / split / (vehicle_path.stem + ".txt")
            if not vehicle_label.exists():
                skipped += 1
                continue
            try:
                destination = read_box(vehicle_label, vehicle.shape[1], vehicle.shape[0])
            except (ValueError, IndexError):
                skipped += 1
                continue
            source_path = rng.choice(sources)
            source = cv2.imread(str(source_path))
            if source is None:
                skipped += 1
                continue
            source_label = args.sharp / "labels" / split / (source_path.stem + ".txt")
            try:
                source_box = read_box(source_label, source.shape[1], source.shape[0])
            except (ValueError, IndexError, FileNotFoundError):
                skipped += 1
                continue
            result = composite(vehicle, source, destination, source_box)
            if result is None:
                skipped += 1
                continue
            image_dir = output / "images" / split
            label_dir = output / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            stem = f"synth_{vehicle_path.stem}"
            cv2.imwrite(str(image_dir / f"{stem}.jpg"), result, [cv2.IMWRITE_JPEG_QUALITY, 93])
            (label_dir / f"{stem}.txt").write_bytes(vehicle_label.read_bytes())
            made += 1
        counts[split] = {"made": made, "skipped": skipped}
    (output / "dataset.yaml").write_text(
        f"path: {output}\ntrain: images/train\nval: images/val\nnames:\n  0: plate\n", encoding="utf-8")
    (output / "summary.json").write_text(
        json.dumps({"counts": counts, "vehicle": str(args.vehicle), "sharp": str(args.sharp),
                    "note": "Synthetic validation is not a real-camera performance estimate."}, indent=2),
        encoding="utf-8")
    print(json.dumps(counts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vehicle", type=Path, required=True)
    parser.add_argument("--sharp", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-limit", type=int, default=5000)
    parser.add_argument("--val-limit", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.train_limit < 0 or args.val_limit < 0:
        parser.error("limits must be nonnegative")
    create(args)


if __name__ == "__main__":
    main()
