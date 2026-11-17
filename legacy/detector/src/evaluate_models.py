#!/usr/bin/env python3
"""Compare two YOLO detectors on the same sharp holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def evaluate(weights: Path, data: Path, imgsz: int, device: str) -> dict:
    metrics = YOLO(str(weights)).val(data=str(data), imgsz=imgsz, device=device, plots=False, verbose=False)
    return {"precision": float(metrics.box.mp), "recall": float(metrics.box.mr),
            "map50": float(metrics.box.map50), "map50_95": float(metrics.box.map)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--finetuned", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("comparison.json"))
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    report = {"baseline": evaluate(args.baseline, args.data, args.imgsz, args.device),
              "finetuned": evaluate(args.finetuned, args.data, args.imgsz, args.device)}
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

