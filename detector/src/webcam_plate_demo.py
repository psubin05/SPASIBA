#!/usr/bin/env python3
"""Live webcam demo: plate detection -> line split -> CTC OCR -> stable text.

Keys:
  q / ESC  quit
  s        save the current annotated frame
  r        clear temporal voting history
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, deque
from pathlib import Path

os.environ.setdefault("QT_QPA_FONTDIR", "/usr/share/fonts/opentype/noto")

import cv2
import numpy as np
import onnxruntime as ort
import torch
from PIL import Image, ImageDraw, ImageFont

from build_ocr_dataset import craft_line_cut
from ocr_common import decode_regions


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PORTABLE_MODELS = PROJECT_ROOT / "models"
if PORTABLE_MODELS.exists():
    DEFAULT_DETECTOR = PORTABLE_MODELS / "detector" / "lp_det.pt"
    DEFAULT_YOLOV5 = PROJECT_ROOT / "third_party" / "yolov5"
    DEFAULT_OCR_DIR = PORTABLE_MODELS / "ocr"
    DEFAULT_SAVE_DIR = PROJECT_ROOT / "webcam_captures"
else:
    DEFAULT_DETECTOR = PROJECT_ROOT / "EasyKoreanLpDetector" / "lp_det.pt"
    DEFAULT_YOLOV5 = PROJECT_ROOT / "EasyKoreanLpDetector" / "yolov5"
    DEFAULT_OCR_DIR = PROJECT_ROOT / "plate_detector" / "runs" / "plate_ctc_v3_strong" / "export"
    DEFAULT_SAVE_DIR = PROJECT_ROOT / "plate_detector" / "webcam_captures"
DEFAULT_FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--detector", type=Path, default=DEFAULT_DETECTOR)
    parser.add_argument("--yolov5-repo", type=Path, default=DEFAULT_YOLOV5)
    parser.add_argument("--ocr", type=Path, default=DEFAULT_OCR_DIR / "plate_ctc_fp32.onnx")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_OCR_DIR / "model_metadata.json")
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--det-conf", type=float, default=0.20)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--line-mode", choices=("auto", "ratio", "single"), default="auto",
                        help="auto uses CRAFT only for low-ratio plates; ratio is faster")
    parser.add_argument("--history", type=int, default=12)
    parser.add_argument("--max-plates", type=int, default=4)
    parser.add_argument("--save-dir", type=Path,
                        default=DEFAULT_SAVE_DIR)
    parser.add_argument("--device", default="0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--headless", action="store_true",
                        help="do not open a window; useful for camera smoke tests")
    parser.add_argument("--max-frames", type=int, default=0,
                        help="stop after this many frames (0 means unlimited)")
    return parser.parse_args()


class CTCRecognizer:
    def __init__(self, model_path: Path, metadata_path: Path):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.characters = metadata["characters"]
        self.width = int(metadata["width"])
        self.height = int(metadata["height"])
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])

    def prepare(self, image: Image.Image) -> np.ndarray:
        image = image.convert("RGB")
        scale = min(self.width / image.width, self.height / image.height)
        image = image.resize((max(1, round(image.width * scale)),
                              max(1, round(image.height * scale))))
        canvas = Image.new("RGB", (self.width, self.height), (127, 127, 127))
        canvas.paste(image, ((self.width - image.width) // 2,
                             (self.height - image.height) // 2))
        array = np.asarray(canvas, dtype=np.float32) / 127.5 - 1.0
        return array.transpose(2, 0, 1)

    def recognize(self, lines: list[Image.Image]) -> tuple[str, float]:
        batch = np.stack([self.prepare(line) for line in lines])
        log_probs = self.session.run(None, {"images": batch})[0]
        decoded, confidences = [], []
        for sequence in log_probs:
            probabilities = np.exp(sequence)
            indices = sequence.argmax(axis=-1)
            result, kept_confidence, previous = [], [], -1
            for timestep, index in enumerate(indices.tolist()):
                if index != 0 and index != previous:
                    result.append(self.characters[index - 1])
                    kept_confidence.append(float(probabilities[timestep, index]))
                previous = index
            decoded.append(decode_regions("".join(result)))
            confidences.append(float(np.mean(kept_confidence)) if kept_confidence else 0.0)
        return "".join(decoded), float(np.mean(confidences))


def split_lines(plate: Image.Image, mode: str, craft_reader) -> tuple[list[Image.Image], str]:
    ratio = plate.width / max(1, plate.height)
    if mode == "single":
        return [plate], "1-line"
    cut = plate.height // 2
    is_tall = ratio < 2.6
    if mode == "auto" and ratio < 3.8:
        line_count, detected_cut = craft_line_cut(craft_reader, plate, 0.65)
        is_tall = line_count == 2 and ratio <= 2.6
        if is_tall:
            cut = detected_cut
    if not is_tall:
        return [plate], "1-line"
    overlap = max(1, round(plate.height * 0.025))
    top = plate.crop((0, 0, plate.width, min(plate.height, cut + overlap)))
    bottom = plate.crop((0, max(0, cut - overlap), plate.width, plate.height))
    return [top, bottom], "2-line"


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def draw_text(frame: np.ndarray, items: list[tuple[tuple[int, int], str, tuple[int, int, int]]],
              font: ImageFont.ImageFont) -> np.ndarray:
    canvas = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(canvas)
    for position, text, color in items:
        x, y = position
        box = draw.textbbox((x, y), text, font=font, stroke_width=2)
        draw.rectangle((box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2), fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=color, stroke_width=1, stroke_fill=(0, 0, 0))
    return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)


def main() -> None:
    args = parse_args()
    if args.headless and args.max_frames <= 0:
        raise ValueError("--headless requires --max-frames greater than zero")
    for required in (args.detector, args.yolov5_repo, args.ocr, args.metadata):
        if not required.exists():
            raise FileNotFoundError(required)

    detector = torch.hub.load(str(args.yolov5_repo.resolve()), "custom",
                              path=str(args.detector.resolve()), source="local",
                              device=args.device)
    detector.conf = args.det_conf
    recognizer = CTCRecognizer(args.ocr, args.metadata)
    craft_reader = None
    if args.line_mode == "auto":
        import easyocr
        craft_reader = easyocr.Reader(["en"], gpu=args.device != "cpu",
                                      recognizer=False, verbose=False)

    camera = cv2.VideoCapture(args.camera)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not camera.isOpened():
        raise RuntimeError(f"Cannot open camera index {args.camera}")
    font = load_font(args.font, 26)
    history: deque[str] = deque(maxlen=max(1, args.history))
    args.save_dir.mkdir(parents=True, exist_ok=True)
    previous_time = time.perf_counter()
    frame_count = 0

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError("Webcam frame read failed")
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = detector(rgb, size=args.imgsz)
            predictions = result.xyxy[0].detach().cpu().numpy()
            predictions = sorted(predictions, key=lambda row: float(row[4]), reverse=True)
            text_items = []
            current_primary = ""
            for index, prediction in enumerate(predictions[:args.max_plates]):
                x1, y1, x2, y2, detection_confidence = prediction[:5]
                pad = 0.02 * max(x2 - x1, y2 - y1)
                left = max(0, int(round(x1 - pad)))
                top = max(0, int(round(y1 - pad)))
                right = min(frame.shape[1], int(round(x2 + pad)))
                bottom = min(frame.shape[0], int(round(y2 + pad)))
                if right - left < 8 or bottom - top < 8:
                    continue
                plate = Image.fromarray(rgb[top:bottom, left:right])
                lines, line_type = split_lines(plate, args.line_mode, craft_reader)
                text, ocr_confidence = recognizer.recognize(lines)
                if index == 0 and text:
                    current_primary = text
                    history.append(text)
                color = (40, 220, 40) if ocr_confidence >= 0.75 else (255, 190, 40)
                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                label = f"{text or '?'}  det:{detection_confidence:.2f} ocr:{ocr_confidence:.2f} {line_type}"
                text_items.append(((left, max(0, top - 34)), label, color))

            stable = Counter(history).most_common(1)[0][0] if history else "-"
            now = time.perf_counter()
            fps = 1.0 / max(now - previous_time, 1e-6)
            previous_time = now
            text_items.append(((12, 10), f"현재: {current_primary or '-'}", (255, 255, 255)))
            text_items.append(((12, 44), f"안정화: {stable}   FPS: {fps:.1f}", (80, 255, 255)))
            text_items.append(((12, frame.shape[0] - 30), "q: 종료  s: 저장  r: 기록 초기화", (220, 220, 220)))
            frame = draw_text(frame, text_items, font)
            frame_count += 1
            if args.headless:
                print(f"frame={frame_count} current={current_primary or '-'} stable={stable} fps={fps:.1f}")
                if args.max_frames and frame_count >= args.max_frames:
                    break
                continue
            cv2.imshow("SPASIBA Plate OCR", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                history.clear()
            if key == ord("s"):
                stamp = time.strftime("%Y%m%d_%H%M%S")
                output = args.save_dir / f"plate_demo_{stamp}.jpg"
                cv2.imwrite(str(output), frame)
                print(f"saved: {output}")
            if args.max_frames and frame_count >= args.max_frames:
                break
    finally:
        camera.release()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
