"""Compare plate detectors on public close-ups and held-out synthetic vehicles."""

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True, type=Path)
    parser.add_argument("--roboflow-data", type=Path,
                        default=Path("data/plate_mixed_rf_v1/roboflow_eval.yaml"))
    parser.add_argument("--synthetic-data", type=Path,
                        default=Path("data/plate_synth_1200/dataset.yaml"))
    parser.add_argument("--blur-data", type=Path,
                        help="optional original blurred-vehicle validation set")
    parser.add_argument("--output", type=Path,
                        default=Path("data/plate_mixed_rf_v1/evaluation.json"))
    parser.add_argument("--test", action="store_true",
                        help="evaluate the public test split after model selection")
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()
    domains = [("roboflow_val", args.roboflow_data, "val"),
               ("synthetic_val", args.synthetic_data, "val")]
    if args.blur_data:
        domains.append(("blurred_vehicle_val", args.blur_data, "val"))
    if args.test:
        domains.append(("roboflow_test", args.roboflow_data, "test"))
    results = {}
    for model_path in args.model:
        model = YOLO(str(model_path))
        model_results = {}
        for domain, data, split in domains:
            metrics = model.val(data=str(data), split=split, device=args.device,
                                imgsz=args.imgsz, batch=64, plots=False,
                                project=str(Path("detector/runs/evaluation").resolve()),
                                name=f"{model_path.parent.parent.name}_{domain}",
                                exist_ok=True)
            model_results[domain] = {
                "precision": float(metrics.box.mp),
                "recall": float(metrics.box.mr),
                "map50": float(metrics.box.map50),
                "map50_95": float(metrics.box.map),
            }
        results[str(model_path)] = model_results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
