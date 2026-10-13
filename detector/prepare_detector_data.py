"""Build YOLO plate-detection data from AI Hub original-frame and label ZIPs.

Only the labelled vehicle and its plate are used. Train/validation are split by
video, so adjacent frames from the same recording cannot enter both sets.
"""

import argparse
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image


def label_rows(label_zip):
    """Index plate-labelled frames by basename without extracting 500k JSON files."""
    rows = defaultdict(list)
    with zipfile.ZipFile(label_zip) as archive:
        for info in archive.infolist():
            if not info.filename.lower().endswith(".json"):
                continue
            item = json.loads(archive.read(info))
            if item.get("plate", {}).get("bbox") and item.get("car", {}).get("bbox"):
                rows[Path(item["imagePath"]).name].append(item)
    return rows


def box_xyxy(points, width, height):
    if len(points) != 2 or any(len(point) != 2 for point in points):
        return None
    values = [coordinate for point in points for coordinate in point]
    if not all(isinstance(value, (float, int)) and math.isfinite(value) for value in values):
        return None
    x1, x2 = sorted((points[0][0], points[1][0]))
    y1, y2 = sorted((points[0][1], points[1][1]))
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def crop_and_label(image, row, min_plate_width, context):
    width, height = image.size
    car = box_xyxy(row["car"]["bbox"], width, height)
    plate = box_xyxy(row["plate"]["bbox"], width, height)
    if car is None or plate is None or plate[2] - plate[0] < min_plate_width:
        return None
    # Keep the entire plate even if its annotation extends slightly past the car.
    x1 = max(0, math.floor(min(car[0], plate[0]) - (car[2] - car[0]) * context))
    y1 = max(0, math.floor(min(car[1], plate[1]) - (car[3] - car[1]) * context))
    x2 = min(width, math.ceil(max(car[2], plate[2]) + (car[2] - car[0]) * context))
    y2 = min(height, math.ceil(max(car[3], plate[3]) + (car[3] - car[1]) * context))
    crop_width, crop_height = x2 - x1, y2 - y1
    if crop_width <= 0 or crop_height <= 0:
        return None
    cx = ((plate[0] + plate[2]) / 2 - x1) / crop_width
    cy = ((plate[1] + plate[3]) / 2 - y1) / crop_height
    bw = (plate[2] - plate[0]) / crop_width
    bh = (plate[3] - plate[1]) / crop_height
    if not all(0 <= value <= 1 for value in (cx, cy, bw, bh)):
        return None
    # Quantize consistently so rounding never makes a boundary box exceed 1.
    unit = 100_000_000
    qcx, qcy = round(cx * unit), round(cy * unit)
    qbw = min(round(bw * unit), 2 * min(qcx, unit - qcx) - 1)
    qbh = min(round(bh * unit), 2 * min(qcy, unit - qcy) - 1)
    if qbw <= 0 or qbh <= 0:
        return None
    return image.crop((x1, y1, x2, y2)), f"0 {qcx / unit:.8f} {qcy / unit:.8f} {qbw / unit:.8f} {qbh / unit:.8f}\n"


def split_for_video(video_name, validation_fraction):
    digest = hashlib.sha256(video_name.encode("utf-8")).digest()
    number = int.from_bytes(digest[:8], "big") / (1 << 64)
    return "val" if number < validation_fraction else "train"


def zip_name(info):
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except (UnicodeError, UnicodeEncodeError):
        return info.filename


def build(args):
    # Require a complete directory and valid CRCs before writing any samples.
    with zipfile.ZipFile(args.images) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise zipfile.BadZipFile(f"Corrupt ZIP member: {bad_member}")
        image_infos = [(info, Path(zip_name(info)).name) for info in archive.infolist()]
        image_infos = [(info, name) for info, name in image_infos if name.lower().endswith((".jpg", ".jpeg", ".png"))]
        rows = label_rows(args.labels)
        output = args.output.resolve()
        counts = Counter()
        for info, image_name in image_infos:
            counts["source_entries"] += 1
            if image_name not in rows:
                continue
            try:
                with Image.open(io.BytesIO(archive.read(info))) as opened:
                    image = opened.convert("RGB")
            except (OSError, ValueError, zipfile.BadZipFile):
                counts["bad_image"] += 1
                continue
            for row in rows[image_name]:
                sample = crop_and_label(image, row, args.min_plate_width, args.context)
                if sample is None:
                    counts["filtered"] += 1
                    continue
                crop, yolo_label = sample
                split = split_for_video(row.get("videoName") or row["imagePath"], args.validation_fraction)
                stem = hashlib.sha256((image_name + row["id"]).encode("utf-8")).hexdigest()[:20]
                image_path = output / "images" / split / f"{stem}.jpg"
                label_path = output / "labels" / split / f"{stem}.txt"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                label_path.parent.mkdir(parents=True, exist_ok=True)
                crop.save(image_path, quality=90)
                label_path.write_text(yolo_label, encoding="utf-8")
                counts[split] += 1
                if args.limit and counts["train"] + counts["val"] >= args.limit:
                    break
            if args.limit and counts["train"] + counts["val"] >= args.limit:
                break
    (output / "dataset.yaml").write_text(
        f"path: {output}\ntrain: images/train\nval: images/val\nnames:\n  0: plate\n",
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps({"counts": counts, "source_images": str(args.images), "source_labels": str(args.labels),
                    "validation_fraction": args.validation_fraction},
                   ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(counts, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True, help="AI Hub original-image label ZIP")
    parser.add_argument("--images", type=Path, required=True, help="complete original-image ZIP")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-plate-width", type=float, default=20)
    parser.add_argument("--context", type=float, default=0.05, help="fraction of vehicle box added as margin")
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--limit", type=int, default=0, help="successful crops; 0 means all")
    args = parser.parse_args()
    if not 0 <= args.context <= 0.5 or not 0 < args.validation_fraction < 1:
        parser.error("context must be 0..0.5 and validation-fraction must be 0..1")
    build(args)


if __name__ == "__main__":
    main()
