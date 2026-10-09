#!/usr/bin/env python3
"""Verify bundled model files and optionally load the YOLOv5 detector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="also load YOLOv5 detector weights")
    args = parser.parse_args()

    paths = {
        "detector": ROOT / "models/detector/lp_det.pt",
        "ocr_pt": ROOT / "models/ocr/plate_ctc_v3_strong.pt",
        "ocr_onnx": ROOT / "models/ocr/plate_ctc_fp32.onnx",
        "metadata": ROOT / "models/ocr/model_metadata.json",
        "yolov5": ROOT / "third_party/yolov5/hubconf.py",
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
        import torch
        model = torch.hub.load(str((ROOT / "third_party/yolov5").resolve()), "custom",
                               path=str(paths["detector"].resolve()), source="local", device="cpu")
        print(f"YOLOv5 detector OK: {type(model).__name__}")
    print("Bundle verification passed.")


if __name__ == "__main__":
    main()
