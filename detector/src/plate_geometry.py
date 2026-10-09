"""Conservative experimental plate perspective rectification helpers."""

from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image


def _order(points: np.ndarray) -> np.ndarray:
    points = points.astype(np.float32)
    ordered = np.zeros((4, 2), dtype=np.float32)
    total = points.sum(axis=1)
    diff = np.diff(points, axis=1).ravel()
    ordered[0], ordered[2] = points[np.argmin(total)], points[np.argmax(total)]
    ordered[1], ordered[3] = points[np.argmin(diff)], points[np.argmax(diff)]
    return ordered


def _warp(array: np.ndarray, points: np.ndarray) -> tuple[np.ndarray, float]:
    top_left, top_right, bottom_right, bottom_left = _order(points)
    width = max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left))
    height = max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right))
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                      dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(
        np.array([top_left, top_right, bottom_right, bottom_left]), target)
    warped = cv2.warpPerspective(array, matrix, (max(2, round(width)), max(2, round(height))),
                                 flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    angle = math.degrees(math.atan2(top_right[1] - top_left[1], top_right[0] - top_left[0]))
    return warped, angle


def rectify_plate(image: Image.Image, max_angle: float = 32.0) -> tuple[Image.Image, dict]:
    """Rectify only when a large plausible quadrilateral is found.

    This remains an opt-in experiment because the 500-image regression benchmark
    did not improve accuracy. A trained OBB detector should replace it.
    """
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 45, 150)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    image_area = width * height
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        area = abs(cv2.contourArea(polygon))
        if area < image_area * 0.28:
            continue
        points = polygon.reshape(4, 2).astype(np.float32)
        ordered = _order(points)
        candidate_width = max(np.linalg.norm(ordered[1] - ordered[0]),
                              np.linalg.norm(ordered[2] - ordered[3]))
        candidate_height = max(np.linalg.norm(ordered[3] - ordered[0]),
                               np.linalg.norm(ordered[2] - ordered[1]))
        ratio = candidate_width / max(candidate_height, 1.0)
        rectangularity = area / max(candidate_width * candidate_height, 1.0)
        if not 1.25 <= ratio <= 6.5 or rectangularity < 0.70:
            continue
        warped, angle = _warp(rgb, points)
        if abs(angle) <= max_angle and warped.shape[0] >= 10 and warped.shape[1] >= 20:
            candidates.append((area / image_area * rectangularity, warped, angle, ratio))
    if not candidates:
        return image.convert("RGB"), {"applied": False, "method": "none", "angle": 0.0}
    score, warped, angle, ratio = max(candidates, key=lambda item: item[0])
    if abs(angle) < 2.0:
        return image.convert("RGB"), {"applied": False, "method": "quad", "angle": angle,
                                      "score": float(score), "ratio": float(ratio)}
    return Image.fromarray(warped), {"applied": True, "method": "quad", "angle": angle,
                                    "score": float(score), "ratio": float(ratio)}
