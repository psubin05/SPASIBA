from __future__ import annotations

import time

from detector import PlateDetector
from paddle_ocr import SubinPaddleOCR


class HybridPlateReader:
    def __init__(self, detector: PlateDetector, ocr: SubinPaddleOCR):
        self.detector, self.ocr = detector, ocr

    def __call__(self, image):
        results = []
        for detection in self.detector(image):
            started = time.perf_counter()
            reading = self.ocr.recognize(detection.crop)
            results.append({
                **reading,
                "bbox": list(detection.bbox),
                "detection_confidence": detection.confidence,
                "processing_time_ms": (time.perf_counter() - started) * 1000,
                "crop": detection.crop,
                "crop_width": int(detection.crop.shape[1]),
                "crop_height": int(detection.crop.shape[0]),
            })
        return results
