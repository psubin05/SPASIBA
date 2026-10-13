"""Measure whether a plate detector finds any box in held-out sharp OCR crops.

These crops have plate text labels but no box labels, so the reported any-box
rate is a diagnostic, not detection recall. Inspect the saved preview for false
positives. No validation crop is used for training by this script.
"""

import argparse
import io
import json
import random
import re
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw
from ultralytics import YOLO, YOLOWorld


def zip_name(info):
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except UnicodeError:
        return info.filename


def load_labels(path):
    rows = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if zip_name(info).endswith(".json"):
                item = json.loads(archive.read(info))
                rows[Path(item["imagePath"]).name] = item["value"]
    return rows


def selected_names(labels, limit, seed):
    by_plate = {}
    for name, plate in labels.items():
        by_plate.setdefault(plate, []).append(name)
    rng = random.Random(seed)
    plates = list(by_plate)
    rng.shuffle(plates)
    if limit:
        plates = plates[:limit]
    return [rng.choice(by_plate[plate]) for plate in plates]


def make_preview(examples, path):
    if not examples:
        return
    columns, cell_w, cell_h = 4, 320, 240
    sheet = Image.new("RGB", (columns * cell_w,
                              ((len(examples) + columns - 1) // columns) * cell_h), "white")
    drawer = ImageDraw.Draw(sheet)
    for index, (image, detections, found) in enumerate(examples):
        sample = image.copy()
        draw = ImageDraw.Draw(sample)
        for x1, y1, x2, y2, _ in detections:
            draw.rectangle((x1, y1, x2, y2), outline="red", width=3)
        sample.thumbnail((cell_w - 8, cell_h - 32))
        x, y = index % columns * cell_w, index // columns * cell_h
        sheet.paste(sample, (x + 4, y + 28))
        drawer.text((x + 4, y + 4), "box" if found else "no box", fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def evaluate(args):
    labels = load_labels(args.labels)
    excluded = set()
    if args.exclude_proposals:
        with args.exclude_proposals.open(encoding="utf-8") as handle:
            excluded = {json.loads(line)["truth"] for line in handle if line.strip()}
        labels = {name: value for name, value in labels.items()
                  if re.sub(r"[^0-9가-힣]", "", value) not in excluded}
    names = selected_names(labels, args.limit, args.seed)
    model = YOLOWorld(str(args.model)) if args.world else YOLO(str(args.model))
    if args.world:
        model.set_classes(["license plate"])
    rows = []
    previews = []
    with zipfile.ZipFile(args.images) as archive:
        indexed = {Path(zip_name(info)).name: info for info in archive.infolist()}
        for index, name in enumerate(names, 1):
            info = indexed.get(name)
            if info is None:
                raise FileNotFoundError(f"No OCR validation image for {name}")
            with Image.open(io.BytesIO(archive.read(info))) as opened:
                image = opened.convert("RGB")
            result = model.predict(image, imgsz=args.imgsz, conf=args.conf,
                                   device=args.device, verbose=False)[0]
            detections = [[float(v) for v in (*box.xyxy[0].tolist(), box.conf.item())]
                          for box in result.boxes]
            found = bool(detections)
            rows.append({"image": name, "truth": labels[name], "any_box": found,
                         "detections": detections})
            if len(previews) < args.preview:
                previews.append((image, detections, found))
            if index % 50 == 0:
                print(f"{index}/{len(names)}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "predictions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    summary = {"model": str(args.model), "world": args.world, "images": len(rows), "excluded_plate_values": len(excluded),
               "any_box": sum(r["any_box"] for r in rows),
               "any_box_rate": sum(r["any_box"] for r in rows) / len(rows) if rows else None,
               "note": "Any-box rate can include false detections; no box ground truth is available."}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    make_preview(previews, args.output / "preview.jpg")
    print(json.dumps(summary, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--world", action="store_true", help="use YOLO-World with the license plate prompt")
    parser.add_argument("--exclude-proposals", type=Path,
                        help="skip plate values present in training proposals JSONL")
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=300, help="distinct plate values; 0 means all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=.25)
    parser.add_argument("--device", default="0")
    parser.add_argument("--preview", type=int, default=24)
    args = parser.parse_args()
    if args.limit < 0 or args.preview < 0 or not 0 < args.conf < 1:
        parser.error("limit/preview must be nonnegative and conf must be between 0 and 1")
    evaluate(args)


if __name__ == "__main__":
    main()
