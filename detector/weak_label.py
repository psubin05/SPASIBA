"""Create reviewable plate box proposals from OCR text positions.

Only AI Hub OCR training ZIPs are accepted. Recognition must match the supplied
plate text exactly; ambiguous images are skipped. The expanded text rectangle is
still a proposal, not a verified plate outline.
"""

import argparse
import hashlib
import io
import itertools
import json
import os
import re
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def decoded_name(info):
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except UnicodeError:
        return info.filename


def normalized(value):
    return re.sub(r"[^0-9가-힣]", "", value or "")


def load_truth(path):
    result = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if decoded_name(info).lower().endswith(".json"):
                item = json.loads(archive.read(info))
                result[Path(item["imagePath"]).name] = normalized(item["value"])
    return result


def proposal(result, truth, width, height, min_conf):
    words = list(zip(result.get("rec_texts", []), result.get("rec_scores", []),
                     result.get("rec_boxes", [])))
    words = [(normalized(text), float(score), box) for text, score, box in words
             if normalized(text) and score >= min_conf]
    if not words:
        return None
    # Usually one or two text boxes; subsets exclude a bumper logo or noise.
    matches = []
    for length in range(1, min(4, len(words)) + 1):
        for subset in itertools.combinations(words, length):
            ordered = sorted(subset, key=lambda row: (round((row[2][1] + row[2][3]) / 20), row[2][0]))
            if "".join(word[0] for word in ordered) == truth:
                matches.append(ordered)
    if not matches:
        return None
    selected = max(matches, key=lambda rows: min(row[1] for row in rows))
    x1 = min(row[2][0] for row in selected)
    y1 = min(row[2][1] for row in selected)
    x2 = max(row[2][2] for row in selected)
    y2 = max(row[2][3] for row in selected)
    text_width, text_height = x2 - x1, y2 - y1
    if text_width < width * .25 or text_height < height * .12:
        return None
    # Text sits inside the plate. Leave room for its rim and mounting bolts.
    mx, my = text_width * .12, text_height * .30
    box = [max(0, round(x1 - mx)), max(0, round(y1 - my)),
           min(width, round(x2 + mx)), min(height, round(y2 + my))]
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box, min(row[1] for row in selected)


def make_sheet(examples, path):
    if not examples:
        return
    cols, cw, ch = 5, 240, 180
    sheet = Image.new("RGB", (cols * cw, ((len(examples) + cols - 1) // cols) * ch), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (image, box, confidence) in enumerate(examples):
        image = image.copy()
        ImageDraw.Draw(image).rectangle(box, outline="lime", width=3)
        image.thumbnail((cw - 8, ch - 28))
        x, y = index % cols * cw, index // cols * ch
        sheet.paste(image, (x + 4, y + 24))
        draw.text((x + 4, y + 3), f"{index}: {confidence:.2f}", fill="black")
    sheet.save(path)


def generate(args):
    if "1.Training" not in args.images.parts or "1.Training" not in args.labels.parts:
        raise ValueError("Only the AI Hub OCR 1.Training ZIPs can generate training labels")
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(args.cache.resolve()))
    os.environ.setdefault("MPLCONFIGDIR", str((args.cache / "matplotlib").resolve()))
    from paddleocr import PaddleOCR

    truth = load_truth(args.labels)
    args.output.mkdir(parents=True, exist_ok=True)
    model = PaddleOCR(device=args.device, text_detection_model_name="PP-OCRv5_mobile_det",
                      text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
                      use_doc_orientation_classify=False, use_doc_unwarping=False,
                      use_textline_orientation=False, enable_mkldnn=False)
    rows, examples = [], []
    with zipfile.ZipFile(args.images) as archive:
        infos = [info for info in archive.infolist()
                 if decoded_name(info).lower().endswith((".jpg", ".jpeg", ".png"))]
        if args.limit:
            stride = max(1, len(infos) // args.limit)
            infos = infos[::stride][:args.limit]
        for index, info in enumerate(infos, 1):
            name = Path(decoded_name(info)).name
            if name not in truth:
                continue
            with Image.open(io.BytesIO(archive.read(info))) as opened:
                image = opened.convert("RGB")
            bgr = np.asarray(image)[:, :, ::-1].copy()
            result = model.predict(input=bgr)[0].json["res"]
            found = proposal(result, truth[name], image.width, image.height, args.min_conf)
            if found:
                box, confidence = found
                rows.append({"image": name, "truth": truth[name], "width": image.width,
                             "height": image.height, "box": box, "confidence": confidence})
                if len(examples) < args.preview:
                    examples.append((image, box, confidence))
                if args.materialize:
                    stem = f"ocr_{index:06d}"
                    split = "val" if int(hashlib.sha256(truth[name].encode()).hexdigest()[:8], 16) % 10 == 0 else "train"
                    image_dir = args.output / "images" / split
                    label_dir = args.output / "labels" / split
                    image_dir.mkdir(parents=True, exist_ok=True)
                    label_dir.mkdir(parents=True, exist_ok=True)
                    image.save(image_dir / f"{stem}.jpg", quality=95)
                    x1, y1, x2, y2 = box
                    label = f"0 {(x1+x2)/2/image.width:.6f} {(y1+y2)/2/image.height:.6f} {(x2-x1)/image.width:.6f} {(y2-y1)/image.height:.6f}\n"
                    (label_dir / f"{stem}.txt").write_text(label, encoding="utf-8")
            if index % 100 == 0:
                print(f"{index}/{len(infos)} accepted={len(rows)}", flush=True)
    with (args.output / "proposals.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"examined": len(infos), "accepted": len(rows), "acceptance_rate": len(rows) / len(infos) if infos else 0,
               "source_images": str(args.images), "source_labels": str(args.labels), "human_reviewed": False}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.materialize:
        root = args.output.resolve()
        (args.output / "dataset.yaml").write_text(
            f"path: {root}\ntrain: images/train\nval: images/val\nnames:\n  0: plate\n", encoding="utf-8")
    make_sheet(examples, args.output / "audit.jpg")
    print(json.dumps(summary, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=Path("data/.paddlex"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0, help="0 processes all images")
    parser.add_argument("--preview", type=int, default=50)
    parser.add_argument("--min-conf", type=float, default=.85)
    parser.add_argument("--materialize", action="store_true", help="also write YOLO images and labels")
    args = parser.parse_args()
    if args.limit < 0 or args.preview < 0 or not 0 <= args.min_conf <= 1:
        parser.error("invalid limit, preview, or min-conf")
    generate(args)


if __name__ == "__main__":
    main()
