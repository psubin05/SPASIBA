#!/usr/bin/env python3
"""Create Ultralytics train-list YAML with sharp samples repeated N times."""

from __future__ import annotations

import argparse
from pathlib import Path


def images(root: Path) -> list[Path]:
    return sorted(p.resolve() for p in root.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blur", type=Path, required=True)
    parser.add_argument("--sharp", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sharp-repeat", type=int, default=5)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    train = images(args.blur / "images/train") + images(args.sharp / "images/train") * args.sharp_repeat
    val = images(args.sharp / "images/eval")
    (args.output / "train.txt").write_text("\n".join(map(str, train)) + "\n", encoding="utf-8")
    (args.output / "eval.txt").write_text("\n".join(map(str, val)) + "\n", encoding="utf-8")
    (args.output / "data.yaml").write_text(
        f"path: {args.output.resolve()}\ntrain: train.txt\nval: eval.txt\nnames:\n  0: plate\n",
        encoding="utf-8",
    )
    print(f"train entries={len(train)}, eval entries={len(val)}")


if __name__ == "__main__":
    main()

