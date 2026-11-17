from __future__ import annotations

import cv2
import numpy as np


def resize_for_ocr(image: np.ndarray, min_width: int = 640, min_height: int = 128) -> np.ndarray:
    height, current = image.shape[:2]
    scale = max(min_width / max(current, 1), min_height / max(height, 1), 1.0)
    # Very large interpolation only magnifies blur and wastes CPU.
    scale = min(scale, 8.0)
    if scale == 1.0:
        return image.copy()
    return cv2.resize(
        image,
        (max(1, round(current * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_CUBIC,
    )


def clahe_color(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(lightness)
    return cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2BGR)


def gamma_correct(image: np.ndarray, gamma: float) -> np.ndarray:
    table = np.array([((index / 255.0) ** gamma) * 255 for index in range(256)], dtype=np.uint8)
    return cv2.LUT(image, table)


def mild_unsharp(image: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(image, (0, 0), 0.9)
    return cv2.addWeighted(image, 1.35, blurred, -0.35, 0)


def variants(image: np.ndarray, robust: bool = False) -> dict[str, np.ndarray]:
    resized = resize_for_ocr(image)
    output = {"resized": resized}
    if robust:
        output["clahe"] = clahe_color(resized)
        output["shadow"] = gamma_correct(resized, 0.72)
        output["glare"] = gamma_correct(clahe_color(resized), 1.28)
        output["unsharp"] = mild_unsharp(resized)
    return output
