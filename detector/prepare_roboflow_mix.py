"""Build a reproducible YOLO training set from public plate crops and synthetic vehicles.

Only the source training splits are linked into the mixed training split. The
validation splits are kept separate for domain-specific evaluation, and the
Roboflow test split is never used for training or model selection.
"""

import argparse
import json
from pathlib import Path


def link_split(source_images, source_labels, target, split, prefix, copies=1):
    images = sorted(source_images.glob("*"))
    count = 0
    for image in images:
        if not image.is_file():
            continue
        label = source_labels / f"{image.stem}.txt"
        if not label.is_file():
            raise FileNotFoundError(label)
        for index in range(copies):
            stem = f"{prefix}_{index}_{image.stem}"
            for source, dest in (
                (image, target / "images" / split / f"{stem}{image.suffix}"),
                (label, target / "labels" / split / f"{stem}.txt"),
            ):
                if dest.is_symlink():
                    if dest.resolve() != source.resolve():
                        raise FileExistsError(dest)
                elif dest.exists():
                    raise FileExistsError(dest)
                else:
                    dest.symlink_to(source.resolve())
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roboflow", type=Path, default=Path("data/roboflow_korea_car_plat"))
    parser.add_argument("--synthetic", type=Path, default=Path("data/plate_synth_1200"))
    parser.add_argument("--output", type=Path, default=Path("data/plate_mixed_rf_v1"))
    parser.add_argument("--roboflow-copies", type=int, default=3)
    args = parser.parse_args()
    if args.roboflow_copies < 1:
        parser.error("--roboflow-copies must be positive")
    out = args.output.resolve()
    for split in ("train", "val"):
        for kind in ("images", "labels"):
            (out / kind / split).mkdir(parents=True, exist_ok=True)

    rf = args.roboflow.resolve()
    synth = args.synthetic.resolve()
    counts = {
        "roboflow_train": link_split(rf / "train/images", rf / "train/labels",
                                      out, "train", "rf", args.roboflow_copies),
        "synthetic_train": link_split(synth / "images/train", synth / "labels/train",
                                      out, "train", "synth"),
        "roboflow_val": link_split(rf / "valid/images", rf / "valid/labels",
                                    out, "val", "rf"),
        "synthetic_val": link_split(synth / "images/val", synth / "labels/val",
                                    out, "val", "synth"),
    }
    (out / "dataset.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\nnames:\n  0: plate\n",
        encoding="utf-8",
    )
    (out / "roboflow_eval.yaml").write_text(
        f"path: {rf}\ntrain: train/images\nval: valid/images\ntest: test/images\nnames:\n  0: plate\n",
        encoding="utf-8",
    )
    (out / "summary.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
