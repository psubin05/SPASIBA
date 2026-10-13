"""Detect plates in a camera image and save crops for the OCR stage.

The optional vehicle pass enlarges small plates by running the plate model on
car, bus, and truck crops. Detections are mapped back to image coordinates.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


def predict_boxes(model, image, conf, imgsz, device):
    result = model.predict(image, conf=conf, imgsz=imgsz, device=device, verbose=False)[0]
    return [(box.xyxy[0].cpu().numpy().tolist(), float(box.conf.item()), int(box.cls.item()))
            for box in result.boxes]


def overlap(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return intersection / max(area_a + area_b - intersection, 1)


def detect(image, plate_model, vehicle_model, args):
    height, width = image.shape[:2]
    results = []
    for box, conf, _ in predict_boxes(plate_model, image, args.conf, args.imgsz, args.device):
        results.append((box, conf, "full"))
    if vehicle_model is not None:
        for vehicle_box, _, category in predict_boxes(vehicle_model, image, args.car_conf, args.imgsz, args.device):
            if category not in (2, 5, 7):  # COCO car, bus, truck
                continue
            x1, y1, x2, y2 = vehicle_box
            margin = .08
            vw, vh = x2 - x1, y2 - y1
            x1 = max(0, int(x1 - vw * margin))
            y1 = max(0, int(y1 - vh * margin))
            x2 = min(width, int(x2 + vw * margin))
            y2 = min(height, int(y2 + vh * margin))
            if x2 - x1 < 40 or y2 - y1 < 40:
                continue
            crop = image[y1:y2, x1:x2]
            for box, conf, _ in predict_boxes(plate_model, crop, args.conf, args.imgsz, args.device):
                results.append(([box[0] + x1, box[1] + y1, box[2] + x1, box[3] + y1], conf, "vehicle"))
    kept = []
    for item in sorted(results, key=lambda row: row[1], reverse=True):
        if all(overlap(item[0], previous[0]) < args.nms_iou for previous in kept):
            kept.append(item)
    return kept


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--plate-model", required=True, type=Path)
    parser.add_argument("--vehicle-model", type=Path, help="optional COCO YOLO model, e.g. detector/yolo11n.pt")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=.15)
    parser.add_argument("--car-conf", type=float, default=.25)
    parser.add_argument("--nms-iou", type=float, default=.5)
    args = parser.parse_args()
    image = cv2.imread(str(args.image))
    if image is None:
        parser.error(f"Cannot read image: {args.image}")
    plate_model = YOLO(str(args.plate_model))
    vehicle_model = YOLO(str(args.vehicle_model)) if args.vehicle_model else None
    rows = detect(image, plate_model, vehicle_model, args)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, (box, confidence, route) in enumerate(rows):
        x1, y1, x2, y2 = [int(round(value)) for value in box]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            continue
        name = f"plate_{index:03d}.jpg"
        cv2.imwrite(str(args.output / name), image[y1:y2, x1:x2])
        manifest.append({"crop": name, "box": [x1, y1, x2, y2], "confidence": confidence, "route": route})
    (args.output / "detections.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
