#!/usr/bin/env python3
"""Detect, crop and index AI Hub OCR images for lightweight CTC training."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image, ImageOps
from tqdm import tqdm
from ultralytics import YOLO
import torch

from ocr_common import encode_regions, is_supported, normalize_plate, split_two_line


def group_split(plate_id: str) -> str:
    value = int(hashlib.sha1(plate_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "train" if value < 80 else ("val" if value < 90 else "test")


def find_line_cut(image: Image.Image) -> int:
    gray = np.asarray(ImageOps.grayscale(image).resize((160, 96)), dtype=np.float32)
    low, high = int(gray.shape[0] * 0.38), int(gray.shape[0] * 0.62)
    scores = []
    for y in range(low, high):
        band = gray[max(0, y - 1):min(gray.shape[0], y + 2)]
        # The gap between lines is usually bright and locally smooth.
        scores.append((float(band.mean() - 0.65 * band.std()), y))
    best = max(scores)[1]
    return max(1, min(image.height - 1, round(best / gray.shape[0] * image.height)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--labels-zip", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--detector-backend", choices=("yolo11", "yolov5"), default="yolo11")
    parser.add_argument("--yolov5-repo", type=Path,
                        default=Path("EasyKoreanLpDetector/yolov5"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-per-plate", type=int, default=5)
    parser.add_argument("--seed", type=int, default=103)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--device", default="0")
    parser.add_argument("--tall-max-ratio", type=float, default=2.6)
    parser.add_argument("--long-min-ratio", type=float, default=3.8)
    parser.add_argument("--line-detector", choices=("none", "craft"), default="craft",
                        help="CRAFT verifies low-ratio plates so tilted one-line plates are not split")
    parser.add_argument("--min-line-overlap", type=float, default=0.65,
                        help="minimum horizontal overlap ratio for accepting two text rows")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def craft_line_cut(reader, crop: Image.Image, min_line_overlap: float = 0.65) -> tuple[int, int]:
    """Return (line_count, cut_y). cut_y is meaningful only for two lines."""
    horizontal, free = reader.detect(np.asarray(crop), text_threshold=.5, low_text=.25,
                                     link_threshold=.3, canvas_size=640, mag_ratio=1.5)
    boxes = []
    for x1, x2, y1, y2 in horizontal[0]:
        boxes.append((float(x1), float(x2), float(y1), float(y2)))
    for polygon in free[0]:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        boxes.append((min(xs), max(xs), min(ys), max(ys)))
    if not boxes:
        return 0, crop.height // 2
    boxes.sort(key=lambda box: (box[2] + box[3]) / 2)
    groups = [[boxes[0]]]
    for box in boxes[1:]:
        previous_center = sum((b[2] + b[3]) / 2 for b in groups[-1]) / len(groups[-1])
        center = (box[2] + box[3]) / 2
        if center - previous_center > crop.height * 0.18:
            groups.append([box])
        else:
            groups[-1].append(box)
    if len(groups) < 2:
        return 1, crop.height // 2
    top, bottom = groups[0], groups[-1]
    top_x1, top_x2 = min(b[0] for b in top), max(b[1] for b in top)
    bottom_x1, bottom_x2 = min(b[0] for b in bottom), max(b[1] for b in bottom)
    overlap = max(0.0, min(top_x2, bottom_x2) - max(top_x1, bottom_x1))
    # A tilted one-line plate is often split into left/right CRAFT boxes whose
    # vertical centers differ. Real two-line plates overlap strongly in x.
    if overlap / max(1.0, min(top_x2 - top_x1, bottom_x2 - bottom_x1)) < min_line_overlap:
        return 1, crop.height // 2
    cut = round((max(b[3] for b in top) + min(b[2] for b in bottom)) / 2)
    return 2, max(1, min(crop.height - 1, cut))


def prediction_stream(args: argparse.Namespace, selected: list[tuple[Path, str]]):
    if args.detector_backend == "yolo11":
        model = YOLO(str(args.detector))
        sources = [str(path) for path, _ in selected]
        results = model.predict(sources, stream=True, imgsz=args.imgsz, batch=args.batch,
                                conf=args.conf, device=args.device, verbose=False)
        for result in results:
            if result.boxes is None:
                yield torch.empty((0, 5))
            else:
                yield torch.cat((result.boxes.xyxy, result.boxes.conf[:, None]), dim=1).cpu()
        return
    model = torch.hub.load(str(args.yolov5_repo.resolve()), "custom", path=str(args.detector.resolve()),
                           source="local", device=args.device)
    model.conf = args.conf
    for start in range(0, len(selected), args.batch):
        batch = selected[start:start + args.batch]
        output = model([str(path) for path, _ in batch], size=args.imgsz)
        yield from (prediction[:, :5].cpu() for prediction in output.xyxy)


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    craft_reader = None
    if args.line_detector == "craft":
        import easyocr
        craft_reader = easyocr.Reader(["en"], gpu=args.device != "cpu", recognizer=False, verbose=False)
    available = {path.name: path for path in args.images.iterdir()
                 if path.suffix.lower() in {".jpg", ".jpeg", ".png"}}
    grouped: dict[str, list[Path]] = defaultdict(list)
    with zipfile.ZipFile(args.labels_zip) as zf:
        members = [name for name in zf.namelist() if name.lower().endswith(".json")]
        for member in tqdm(members, desc="reading labels"):
            record = json.loads(zf.read(member))
            filename = PurePosixPath(record.get("imagePath", "")).name
            value = normalize_plate(record.get("value", ""))
            if filename in available and is_supported(value):
                grouped[value].append(available[filename])

    selected: list[tuple[Path, str]] = []
    for plate_id, paths in sorted(grouped.items()):
        rng.shuffle(paths)
        selected.extend((path, plate_id) for path in paths[:args.max_per_plate])
    rng.shuffle(selected)
    if args.limit:
        selected = selected[:args.limit]

    writers = {}
    handles = []
    for split in ("train", "val", "test"):
        (args.output / "images" / split).mkdir(parents=True, exist_ok=True)
        handle = (args.output / f"{split}.tsv").open("w", newline="", encoding="utf-8")
        handles.append(handle)
        writers[split] = csv.writer(handle, delimiter="\t")

    stats = Counter(selected=len(selected))
    metadata = []
    try:
        predictions = prediction_stream(args, selected)
        for prediction, (source, plate_id) in tqdm(zip(predictions, selected), total=len(selected), desc="detecting plates"):
            if len(prediction) == 0:
                stats["no_detection"] += 1
                continue
            best = int(prediction[:, 4].argmax().item())
            x1, y1, x2, y2, confidence = prediction[best].tolist()
            with Image.open(source) as opened:
                image = opened.convert("RGB")
            pad = 0.02 * max(x2 - x1, y2 - y1)
            x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
            x2, y2 = min(image.width, x2 + pad), min(image.height, y2 + pad)
            if x2 - x1 < 8 or y2 - y1 < 8:
                stats["tiny_detection"] += 1
                continue
            crop = image.crop((round(x1), round(y1), round(x2), round(y2)))
            ratio = crop.width / crop.height
            line_cut = None
            if ratio >= args.long_min_ratio:
                plate_type = "long_vregion" if not plate_id[0].isdigit() else "long"
            elif craft_reader is not None:
                line_count, line_cut = craft_line_cut(craft_reader, crop, args.min_line_overlap)
                if line_count == 2 and ratio <= args.tall_max_ratio:
                    plate_type = "tall"
                elif line_count == 2:
                    stats["ambiguous_ratio"] += 1
                    continue
                elif line_count == 1:
                    plate_type = "long_vregion" if not plate_id[0].isdigit() else "long"
                    stats["craft_recovered_tilted_long"] += 1
                else:
                    stats["craft_no_text"] += 1
                    continue
            else:
                stats["ambiguous_ratio"] += 1
                continue
            split = group_split(plate_id)
            stem = source.stem
            if plate_type == "tall":
                top_text, bottom_text = split_two_line(plate_id)
                cut = line_cut if line_cut is not None else find_line_cut(crop)
                overlap = max(1, round(crop.height * 0.025))
                line_data = ((crop.crop((0, 0, crop.width, min(crop.height, cut + overlap))), top_text, 0),
                             (crop.crop((0, max(0, cut - overlap), crop.width, crop.height)), bottom_text, 1))
            else:
                line_data = ((crop, encode_regions(plate_id), 0),)
            for line_image, encoded, line_index in line_data:
                name = f"{stem}__L{line_index}.jpg"
                relative = Path("images") / split / name
                line_image.save(args.output / relative, quality=95, optimize=True)
                writers[split].writerow((relative.as_posix(), encoded, plate_id, plate_type))
                stats[f"{split}_lines"] += 1
            stats[plate_type] += 1
            metadata.append({"source": source.name, "plate_id": plate_id, "split": split,
                             "type": plate_type, "ratio": round(ratio, 4),
                             "confidence": round(confidence, 6)})
    finally:
        for handle in handles:
            handle.close()
    (args.output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
