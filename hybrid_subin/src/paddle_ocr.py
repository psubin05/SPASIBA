from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

from postprocessing import extract_plate
from preprocessing import variants


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(ROOT / "models/paddlex"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


class SubinPaddleOCR:
    """Subin's PP-OCRv5 detector+Korean recognizer, loaded once."""

    def __init__(self, device: str = "cpu", robust: bool = False, cpu_threads: int | None = None):
        from paddleocr import PaddleOCR, TextRecognition

        # PaddleOCR defaults to 10 CPU threads. On a 4-core Raspberry Pi the
        # bundled OpenBLAS segfaults (sgemm_itcopy) with more threads than cores.
        cpu_threads = cpu_threads or min(4, os.cpu_count() or 1)

        self.model = PaddleOCR(
            device=device,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
            cpu_threads=cpu_threads,
        )
        # Subin's evaluation code also supports recognition-only. It is a useful
        # fallback when the text detector misses a whole, already-cropped plate.
        self.recognizer = TextRecognition(
            model_name="korean_PP-OCRv5_mobile_rec",
            device=device,
            enable_mkldnn=False,
            cpu_threads=cpu_threads,
        )
        self.device = device
        self.robust = robust

    @staticmethod
    def _parse(output) -> tuple[str, float, list[dict]]:
        if not output:
            return "", 0.0, []
        result = output[0].json["res"]
        words = list(zip(
            result.get("rec_texts", []), result.get("rec_scores", []), result.get("rec_boxes", []),
        ))
        # Subin's reading order: top-to-bottom buckets, then left-to-right.
        words.sort(key=lambda row: (int((row[2][1] + row[2][3]) / 15), row[2][0]))
        regions = [
            {"text": str(text), "confidence": float(score), "bbox": [int(v) for v in box]}
            for text, score, box in words
        ]
        raw = "".join(item["text"] for item in regions)
        confidence = min((item["confidence"] for item in regions), default=0.0)
        return raw, confidence, regions

    def recognize(self, crop: np.ndarray) -> dict:
        candidates = []
        for name, image in variants(crop, self.robust).items():
            started = time.perf_counter()
            output = self.model.predict(input=image)
            raw, confidence, regions = self._parse(output)
            plate, valid = extract_plate(raw)
            candidates.append({
                "plate_text": plate,
                "raw_text": raw,
                "format_valid": valid,
                "ocr_confidence": confidence,
                "preprocessing": name,
                "regions": regions,
                "ocr_time_ms": (time.perf_counter() - started) * 1000,
                "method": "pipeline",
            })
            started = time.perf_counter()
            rec_output = self.recognizer.predict(input=image)
            rec_result = rec_output[0].json["res"] if rec_output else {}
            rec_raw = str(rec_result.get("rec_text", ""))
            rec_confidence = float(rec_result.get("rec_score", 0.0))
            rec_plate, rec_valid = extract_plate(rec_raw)
            candidates.append({
                "plate_text": rec_plate,
                "raw_text": rec_raw,
                "format_valid": rec_valid,
                "ocr_confidence": rec_confidence,
                "preprocessing": name,
                "regions": [],
                "ocr_time_ms": (time.perf_counter() - started) * 1000,
                "method": "recognition",
            })
        best = max(candidates, key=lambda item: (item["format_valid"], item["ocr_confidence"]))
        return {**best, "alternatives": candidates}
