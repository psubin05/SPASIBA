#!/usr/bin/env python3
"""Run a trained detector over OCR crops and write one CSV row per detection."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(args.weights))
    results = model.predict(source=str(args.source), stream=True, imgsz=args.imgsz, batch=args.batch,
                            conf=args.conf, device=args.device, verbose=False)
    fields = ["image", "detection_index", "confidence", "x1", "y1", "x2", "y2"]
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                writer.writerow({"image": Path(result.path).name, "detection_index": -1})
                continue
            for index, (xyxy, conf) in enumerate(zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist())):
                writer.writerow({"image": Path(result.path).name, "detection_index": index,
                                 "confidence": round(conf, 6), "x1": round(xyxy[0], 2),
                                 "y1": round(xyxy[1], 2), "x2": round(xyxy[2], 2),
                                 "y2": round(xyxy[3], 2)})


if __name__ == "__main__":
    main()

