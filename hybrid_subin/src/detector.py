from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
LOCAL_MODEL = ROOT / "models/detector/plate_v3.pt"


def default_model_path():
    """Return the detector bundled with this GitHub project folder."""
    return LOCAL_MODEL


@dataclass(frozen=True)
class Detection:
    bbox: tuple[int, int, int, int]
    confidence: float
    crop: np.ndarray


class PlateDetector:
    def __init__(self, model_path=None, confidence=0.25, image_size=960, device=None, margin=0.04,
                 tiled=False, tile_overlap=0.18, nms_iou=0.45):
        from ultralytics import YOLO

        self.model_path = Path(model_path).expanduser().resolve() if model_path else default_model_path().resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(f"plate_v3 모델이 없습니다: {self.model_path}")
        self.model = YOLO(str(self.model_path))
        self.confidence = confidence
        self.image_size = image_size
        self.device = device
        self.margin = margin
        self.tiled = tiled
        self.tile_overlap = tile_overlap
        self.nms_iou = nms_iou

    @staticmethod
    def _iou(a, b):
        x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
        return intersection / union if union > 0 else 0.0

    def _predict_boxes(self, image, offset_x=0, offset_y=0):
        kwargs = {"conf": self.confidence, "imgsz": self.image_size, "verbose": False}
        if self.device:
            kwargs["device"] = self.device
        result = self.model.predict(image, **kwargs)[0]
        if result.boxes is None:
            return []
        return [
            ([x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y], float(confidence))
            for (x1, y1, x2, y2), confidence in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist())
        ]

    def _tile_regions(self, width, height):
        tile_width = int(width * (0.5 + self.tile_overlap / 2))
        tile_height = int(height * (0.5 + self.tile_overlap / 2))
        return (
            (0, 0, tile_width, tile_height), (width - tile_width, 0, width, tile_height),
            (0, height - tile_height, tile_width, height),
            (width - tile_width, height - tile_height, width, height),
        )

    def _nms(self, boxes):
        kept = []
        for candidate in sorted(boxes, key=lambda item: item[1], reverse=True):
            if all(self._iou(candidate[0], previous[0]) < self.nms_iou for previous in kept):
                kept.append(candidate)
        return kept

    def __call__(self, image: np.ndarray) -> list[Detection]:
        if image is None or not image.size:
            return []
        height, width = image.shape[:2]
        boxes = self._predict_boxes(image)
        if self.tiled:
            for tx1, ty1, tx2, ty2 in self._tile_regions(width, height):
                boxes.extend(self._predict_boxes(image[ty1:ty2, tx1:tx2], tx1, ty1))
        boxes = self._nms(boxes)
        output = []
        for coords, confidence in boxes:
            x1, y1, x2, y2 = coords
            ratio = (x2 - x1) / max(y2 - y1, 1)
            if not 1.15 <= ratio <= 7.5:
                continue
            mx, my = (x2 - x1) * self.margin, (y2 - y1) * self.margin
            bbox = (
                max(0, int(x1 - mx)), max(0, int(y1 - my)),
                min(width, int(x2 + mx)), min(height, int(y2 + my)),
            )
            crop = image[bbox[1]:bbox[3], bbox[0]:bbox[2]].copy()
            if crop.size:
                output.append(Detection(bbox, float(confidence), crop))
        return output
