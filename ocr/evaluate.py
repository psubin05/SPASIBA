"""Evaluate Korean license-plate OCR directly from the AI Hub validation ZIPs."""

import argparse
import io
import json
import random
import re
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

from PIL import Image


REGIONS = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)
PLATE_PATTERN = re.compile(
    rf"(?:(?:{'|'.join(REGIONS)}))?\d{{2,3}}[가-힣]\d{{4}}"
)


def normalize(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value or ""))


def zip_name(info):
    # AI Hub ZIP entries use CP949 bytes without setting the UTF-8 flag.
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except (UnicodeError, UnicodeEncodeError):
        return info.filename


def find_validation_zips(data_dir):
    images = labels = None
    for path in data_dir.rglob("*.zip"):
        name = path.name
        if name == "자동차번호판OCR_validation.zip":
            labels = path
        elif name == "자동차번호판OCR데이터.zip" and "2.Validation" in path.parts:
            images = path
    if not images or not labels:
        raise FileNotFoundError("AI Hub OCR validation image/label ZIPs were not found")
    return images, labels


def load_labels(archive):
    rows = {}
    for info in archive.infolist():
        if not zip_name(info).lower().endswith(".json"):
            continue
        item = json.loads(archive.read(info))
        image_name = Path(item["imagePath"]).name
        rows[image_name] = item["value"]
    return rows


def plate_group(value):
    value = normalize(value)
    if value.startswith(REGIONS):
        return "region"
    if re.fullmatch(r"\d{2,3}[가-힣]\d{4}", value):
        return "standard"
    return "other"


def extract_plate(value):
    """Remove surrounding OCR noise while preserving only observed plate text."""
    cleaned = re.sub(r"[^0-9가-힣]", "", normalize(value))
    matches = list(PLATE_PATTERN.finditer(cleaned))
    if not matches:
        return cleaned
    # A complete regional plate is more informative than a substring of it.
    matches.sort(key=lambda match: (-bool(match.group().startswith(REGIONS)),
                                    -len(match.group()), match.start()))
    return matches[0].group()


def edit_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def select_rows(labels, limit, seed):
    groups = defaultdict(list)
    for name, truth in labels.items():
        groups[plate_group(truth)].append(name)
    rng = random.Random(seed)
    for items in groups.values():
        rng.shuffle(items)
    if not limit or limit >= len(labels):
        return [name for items in groups.values() for name in items]
    # Keep rare formats represented in a small diagnostic sample.
    quotas = {group: round(limit * len(items) / len(labels))
              for group, items in groups.items()}
    for group in groups:
        if groups[group] and limit >= len(groups):
            quotas[group] = max(1, quotas[group])
    chosen = [name for group, items in groups.items() for name in items[:quotas[group]]]
    if len(chosen) < limit:
        remaining = [name for group, items in groups.items()
                     for name in items[quotas[group]:]]
        rng.shuffle(remaining)
        chosen.extend(remaining[:limit - len(chosen)])
    return chosen[:limit]


def make_model(method, device):
    if method == "recognition":
        from paddleocr import TextRecognition
        return TextRecognition(model_name="korean_PP-OCRv5_mobile_rec",
                               device=device, enable_mkldnn=False)
    from paddleocr import PaddleOCR
    return PaddleOCR(
        device=device,
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, enable_mkldnn=False,
    )


def predict(model, image, method):
    import numpy as np
    # PaddleOCR accepts OpenCV-style BGR arrays.
    bgr = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    output = model.predict(input=bgr)
    if not output:
        return "", 0.0
    result = output[0].json["res"]
    if method == "recognition":
        return result.get("rec_text", ""), float(result.get("rec_score", 0))
    words = list(zip(result.get("rec_texts", []), result.get("rec_scores", []),
                     result.get("rec_boxes", [])))
    # Reading order: top to bottom, then left to right. This also joins two rows.
    words.sort(key=lambda row: (int((row[2][1] + row[2][3]) / 15), row[2][0]))
    return "".join(row[0] for row in words), min((float(row[1]) for row in words), default=0)


def summarize(rows):
    summary = {}
    for group in ("all", "standard", "region", "other"):
        subset = rows if group == "all" else [r for r in rows if r["group"] == group]
        if not subset:
            continue
        chars = sum(len(r["truth_normalized"]) for r in subset)
        summary[group] = {
            "count": len(subset),
            "exact_accuracy": sum(r["exact"] for r in subset) / len(subset),
            "character_error_rate": sum(r["edit_distance"] for r in subset) / chars,
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--method", choices=("recognition", "pipeline"), default="recognition")
    parser.add_argument("--limit", type=int, default=300, help="0 evaluates all 10,000")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--postprocess", action="store_true",
                        help="extract a syntactically valid plate from noisy OCR text")
    parser.add_argument("--output", type=Path, default=Path("reports/ocr_baseline.jsonl"))
    args = parser.parse_args()
    image_path, label_path = find_validation_zips(args.data_dir)
    with zipfile.ZipFile(label_path) as label_zip:
        labels = load_labels(label_zip)
    selected = select_rows(labels, args.limit, args.seed)
    model = make_model(args.method, args.device)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with zipfile.ZipFile(image_path) as image_zip, args.output.open("w", encoding="utf-8") as out:
        images = {Path(zip_name(info)).name: info for info in image_zip.infolist()}
        for index, name in enumerate(selected, 1):
            if name not in images:
                raise KeyError(f"Missing image for label: {name}")
            with Image.open(io.BytesIO(image_zip.read(images[name]))) as image:
                raw_prediction, score = predict(model, image, args.method)
            prediction = extract_plate(raw_prediction) if args.postprocess else raw_prediction
            truth = labels[name]
            normalized_truth, normalized_prediction = normalize(truth), normalize(prediction)
            row = {"image": name, "group": plate_group(truth), "truth": truth,
                   "raw_prediction": raw_prediction,
                   "prediction": prediction, "score": score,
                   "truth_normalized": normalized_truth,
                   "prediction_normalized": normalized_prediction,
                   "exact": normalized_truth == normalized_prediction,
                   "edit_distance": edit_distance(normalized_truth, normalized_prediction)}
            rows.append(row)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            if index % 25 == 0:
                print(f"{index}/{len(selected)} evaluated", flush=True)
    report = {"method": args.method, "postprocess": args.postprocess,
              "model": "korean_PP-OCRv5_mobile_rec",
              "seed": args.seed, "count": len(rows), "metrics": summarize(rows)}
    report_path = args.output.with_suffix(".summary.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
