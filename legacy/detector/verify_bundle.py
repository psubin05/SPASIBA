#!/usr/bin/env python3
"""Verify the default bundled YOLO11 detector and CTC OCR artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="also load and run the YOLO11 detector")
    args = parser.parse_args()

    paths = {
        "detector": ROOT / "models/detector/plate_yolo11n_balanced_webcam_v1.pt",
        "ocr_pt": ROOT / "models/ocr_webcam_v1/plate_ctc_webcam_v1.pt",
        "ocr_onnx": ROOT / "models/ocr_webcam_v1/plate_ctc_fp32.onnx",
        "metadata": ROOT / "models/ocr_webcam_v1/model_metadata.json",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing bundle files:\n" + "\n".join(missing))

    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    session = ort.InferenceSession(str(paths["ocr_onnx"]), providers=["CPUExecutionProvider"])
    sample = np.zeros((1, 3, metadata["height"], metadata["width"]), dtype=np.float32)
    output = session.run(None, {"images": sample})[0]
    expected_classes = len(metadata["characters"]) + 1
    if output.shape[0] != 1 or output.shape[-1] != expected_classes:
        raise RuntimeError(f"Unexpected OCR output shape: {output.shape}")
    print(f"OCR ONNX OK: input={sample.shape}, output={output.shape}")

    if args.full:
        from ultralytics import YOLO
        model = YOLO(str(paths["detector"]))
        result = model.predict(np.zeros((640, 640, 3), dtype=np.uint8), device="cpu",
                               imgsz=640, verbose=False)[0]
        print(f"YOLO11 detector OK: {type(model).__name__}, boxes={len(result.boxes)}")
    print("Bundle verification passed.")


if __name__ == "__main__":
    main()
