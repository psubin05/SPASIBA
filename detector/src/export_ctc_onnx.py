#!/usr/bin/env python3
"""Export PlateCTC to ONNX, create dynamic-int8 weights and verify outputs."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic

from train_ctc_ocr import PlateCTC


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=100)
    return parser.parse_args()


def benchmark(session: ort.InferenceSession, sample: np.ndarray, runs: int) -> float:
    for _ in range(10):
        session.run(None, {"images": sample})
    started = time.perf_counter()
    for _ in range(runs):
        session.run(None, {"images": sample})
    return (time.perf_counter() - started) * 1000 / runs


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = torch.load(args.weights, map_location="cpu", weights_only=False)
    model = PlateCTC(len(checkpoint["characters"]) + 1)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    sample = torch.randn(1, 3, checkpoint["height"], checkpoint["width"])
    fp_path = args.output / "plate_ctc_fp32.onnx"
    int8_path = args.output / "plate_ctc_int8.onnx"
    torch.onnx.export(
        model, sample, fp_path, input_names=["images"], output_names=["log_probs"],
        dynamic_axes={"images": {0: "batch"}, "log_probs": {0: "batch"}},
        opset_version=17, dynamo=False,
    )
    onnx.checker.check_model(onnx.load(fp_path))
    quantize_dynamic(fp_path, int8_path, weight_type=QuantType.QInt8)
    onnx.checker.check_model(onnx.load(int8_path))

    array = sample.numpy()
    providers = ["CPUExecutionProvider"]
    fp_session = ort.InferenceSession(str(fp_path), providers=providers)
    int8_session = ort.InferenceSession(str(int8_path), providers=providers)
    with torch.no_grad():
        torch_output = model(sample).numpy()
    fp_output = fp_session.run(None, {"images": array})[0]
    int8_output = int8_session.run(None, {"images": array})[0]
    report = {
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "input": list(sample.shape),
        "fp32_bytes": fp_path.stat().st_size,
        "int8_bytes": int8_path.stat().st_size,
        "pytorch_vs_onnx_max_abs": float(np.max(np.abs(torch_output - fp_output))),
        "fp32_vs_int8_max_abs": float(np.max(np.abs(fp_output - int8_output))),
        "onnx_fp32_cpu_ms": benchmark(fp_session, array, args.runs),
        "onnx_int8_cpu_ms": benchmark(int8_session, array, args.runs),
        "runs": args.runs,
        "note": "CPU time is for this development machine, not Raspberry Pi 4.",
    }
    (args.output / "export_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    (args.output / "model_metadata.json").write_text(json.dumps({
        "characters": checkpoint["characters"],
        "width": checkpoint["width"],
        "height": checkpoint["height"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
