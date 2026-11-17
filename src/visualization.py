from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


FONTS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
)


def draw_results(image, results):
    canvas = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(canvas)
    font_path = next((path for path in FONTS if Path(path).is_file()), None)
    font = ImageFont.truetype(font_path, max(18, image.shape[1] // 50)) if font_path else ImageFont.load_default()
    for index, result in enumerate(results, 1):
        x1, y1, x2, y2 = result["bbox"]
        draw.rectangle((x1, y1, x2, y2), outline=(0, 255, 0), width=3)
        text = result.get("display_text", result["plate_text"]) or "미인식"
        label = f"{text} D:{result['detection_confidence']:.2f} O:{result['ocr_confidence']:.2f}"
        if not font_path:
            label = f"plate {index} D:{result['detection_confidence']:.2f} O:{result['ocr_confidence']:.2f}"
        position = (x1, max(0, y1 - 30))
        bounds = draw.textbbox(position, label, font=font)
        draw.rectangle(bounds, fill=(0, 0, 0))
        draw.text(position, label, font=font, fill=(80, 255, 80))
    return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)
