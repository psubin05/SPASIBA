#!/usr/bin/env python3
"""Export greedy text and compact per-timestep CTC top-k probabilities as JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from PIL import Image
from torchvision.transforms import functional as TF

from ocr_common import decode_regions
from train_ctc_ocr import PlateCTC, greedy_decode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--images", type=Path, nargs="+", required=True,
                        help="one or more already-cropped plate-line images")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--device", default="cuda")
    return parser.parse_args()


def prepare(path: Path, width: int, height: int) -> torch.Tensor:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    scale = min(width / image.width, height / image.height)
    image = image.resize((max(1, round(image.width * scale)),
                          max(1, round(image.height * scale))))
    canvas = Image.new("RGB", (width, height), (127, 127, 127))
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    tensor = TF.normalize(TF.to_tensor(canvas), (0.5,) * 3, (0.5,) * 3)
    return tensor


@torch.no_grad()
def main() -> None:
    args = parse_args()
    checkpoint = torch.load(args.weights, map_location="cpu", weights_only=False)
    characters = checkpoint["characters"]
    device = torch.device(args.device)
    model = PlateCTC(len(characters) + 1).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    images = torch.stack([prepare(path, checkpoint["width"], checkpoint["height"])
                          for path in args.images]).to(device)
    log_probs = model(images)
    decoded = greedy_decode(log_probs.transpose(0, 1), characters)
    probabilities = log_probs.exp()
    values, indices = probabilities.topk(min(args.topk, probabilities.size(-1)), dim=-1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for batch_index, path in enumerate(args.images):
            timesteps = []
            for value_row, index_row in zip(values[batch_index], indices[batch_index]):
                choices = []
                for value, index in zip(value_row.tolist(), index_row.tolist()):
                    token = "<blank>" if index == 0 else decode_regions(characters[index - 1])
                    choices.append({"token": token, "p": round(value, 7)})
                timesteps.append(choices)
            handle.write(json.dumps({"image": str(path),
                                     "greedy_text": decode_regions(decoded[batch_index]),
                                     "timesteps": timesteps}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
