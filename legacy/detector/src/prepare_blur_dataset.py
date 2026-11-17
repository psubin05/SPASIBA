#!/usr/bin/env python3
"""Build a YOLO detection dataset by cropping AI Hub frames to vehicle boxes."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image
from tqdm import tqdm


def norm_name(value: str) -> str:
    return unicodedata.normalize("NFC", PurePosixPath(value).name)


def split_for(group: str, val_ratio: float) -> str:
    score = int(hashlib.sha1(group.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if score < val_ratio else "train"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images-zip", type=Path, required=True)
    parser.add_argument("--labels-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--val-ratio", type=float, default=0.087)
    parser.add_argument("--padding", type=float, default=0.05,
                        help="Padding around the car bbox as a fraction of its larger side")
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--limit", type=int, default=0, help="For a smoke test; 0 means all")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for split in ("train", "val"):
        (args.output / "images" / split).mkdir(parents=True, exist_ok=True)
        (args.output / "labels" / split).mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(args.images_zip) as image_zip, zipfile.ZipFile(args.labels_zip) as label_zip:
        image_members = {
            norm_name(name): name for name in image_zip.namelist()
            if name.lower().endswith((".jpg", ".jpeg", ".png"))
        }
        annotations: dict[str, dict] = {}
        json_members = [n for n in label_zip.namelist() if n.lower().endswith(".json")]
        for member in tqdm(json_members, desc="matching labels"):
            try:
                record = json.loads(label_zip.read(member))
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
                continue
            key = norm_name(record.get("imagePath", ""))
            if key in image_members and record.get("car", {}).get("bbox") and record.get("plate", {}).get("bbox"):
                annotations.setdefault(key, record)
                if args.limit and len(annotations) >= args.limit:
                    break

        stats = {"train": 0, "val": 0, "skipped": 0}
        manifest = []
        for key, record in tqdm(sorted(annotations.items()), desc="writing crops"):
            try:
                with Image.open(io.BytesIO(image_zip.read(image_members[key]))) as source:
                    image = source.convert("RGB")
                (cx1, cy1), (cx2, cy2) = record["car"]["bbox"]
                (px1, py1), (px2, py2) = record["plate"]["bbox"]
                pad = max(cx2 - cx1, cy2 - cy1) * args.padding
                x1, y1 = clamp(cx1 - pad, 0, image.width), clamp(cy1 - pad, 0, image.height)
                x2, y2 = clamp(cx2 + pad, 0, image.width), clamp(cy2 + pad, 0, image.height)
                if x2 - x1 < 2 or y2 - y1 < 2:
                    raise ValueError("empty car crop")
                bx1, by1 = clamp(px1, x1, x2), clamp(py1, y1, y2)
                bx2, by2 = clamp(px2, x1, x2), clamp(py2, y1, y2)
                if bx2 - bx1 < 1 or by2 - by1 < 1:
                    raise ValueError("empty plate box")
                crop = image.crop((round(x1), round(y1), round(x2), round(y2)))
                cw, ch = crop.size
                xc = ((bx1 + bx2) / 2 - x1) / cw
                yc = ((by1 + by2) / 2 - y1) / ch
                bw = (bx2 - bx1) / cw
                bh = (by2 - by1) / ch
                group = record.get("videoName") or key
                split = split_for(group, args.val_ratio)
                stem = Path(key).stem
                out_image = args.output / "images" / split / f"{stem}.jpg"
                out_label = args.output / "labels" / split / f"{stem}.txt"
                crop.save(out_image, quality=args.jpeg_quality, optimize=True)
                out_label.write_text(f"0 {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n", encoding="utf-8")
                stats[split] += 1
                manifest.append({"image": key, "split": split, "video": group})
            except (OSError, ValueError, KeyError, TypeError) as exc:
                stats["skipped"] += 1
                manifest.append({"image": key, "error": str(exc)})

    (args.output / "data.yaml").write_text(
        "path: " + str(args.output.resolve()) + "\n"
        "train: images/train\nval: images/val\n"
        "names:\n  0: plate\n",
        encoding="utf-8",
    )
    (args.output / "manifest.json").write_text(
        json.dumps({"stats": stats, "items": manifest}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()

