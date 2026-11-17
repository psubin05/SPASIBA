from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2

from detector import PlateDetector
from paddle_ocr import SubinPaddleOCR
from pipeline import HybridPlateReader
from visualization import draw_results


def main():
    parser = argparse.ArgumentParser(description="soogguang plate_v3 + subin PaddleOCR")
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", default="outputs/image")
    parser.add_argument("--detector-model")
    parser.add_argument("--det-size", type=int, default=960, choices=(640, 960, 1280))
    parser.add_argument("--det-conf", type=float, default=0.25)
    parser.add_argument("--tile-detect", action="store_true")
    parser.add_argument("--device", default="cpu", help="YOLO device")
    parser.add_argument("--ocr-device", default="cpu", help="PaddleOCR device")
    parser.add_argument("--robust", action="store_true", help="그림자/빛번짐 전처리 후보 비교")
    args = parser.parse_args()

    image = cv2.imread(args.image)
    if image is None:
        raise SystemExit(f"이미지를 읽을 수 없습니다: {args.image}")
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    # PaddleOCR must initialize before torch (YOLO) loads; the reverse order segfaults on Raspberry Pi.
    ocr = SubinPaddleOCR(args.ocr_device, args.robust)
    reader = HybridPlateReader(
        PlateDetector(args.detector_model, args.det_conf, args.det_size, args.device, tiled=args.tile_detect),
        ocr,
    )
    results = reader(image)
    serializable = [{key: value for key, value in result.items() if key != "crop"} for result in results]
    print(json.dumps(serializable, ensure_ascii=False, indent=2))
    cv2.imwrite(str(output / "result.jpg"), draw_results(image, results))
    (output / "results.json").write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["plate_text", "raw_text", "format_valid", "ocr_confidence", "detection_confidence", "method", "preprocessing", "crop_width", "crop_height", "bbox", "processing_time_ms"]
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        writer.writerows({key: result[key] for key in fields} for result in serializable)


if __name__ == "__main__":
    main()
