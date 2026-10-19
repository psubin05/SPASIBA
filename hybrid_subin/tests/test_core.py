import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postprocessing import extract_plate
from tracking import Tracker
from preprocessing import resize_for_ocr
from detector import PlateDetector
import numpy as np


class CoreTests(unittest.TestCase):
    def test_extracts_plate_from_noise(self):
        self.assertEqual(extract_plate("logo 서울80 바1234 xyz"), ("서울80바1234", True))

    def test_invalid_hangul_is_not_valid(self):
        self.assertEqual(extract_plate("154런7070"), ("154런7070", False))

    def test_tracks_do_not_mix_cars(self):
        tracker = Tracker()
        a = {"bbox": [0, 0, 100, 30], "plate_text": "154러7070", "format_valid": True, "ocr_confidence": 0.8}
        b = {**a, "bbox": [300, 0, 400, 30], "plate_text": "50가1234"}
        track_a = tracker.update([a], 0)[0][1]
        track_b = tracker.update([b], 1)[0][1]
        self.assertNotEqual(track_a.track_id, track_b.track_id)

    def test_moving_plate_keeps_track(self):
        tracker = Tracker()
        item = {"bbox": [0, 0, 100, 40], "plate_text": "123가4567", "format_valid": True, "ocr_confidence": 0.9}
        first = tracker.update([item], 0)[0][1]
        moved = {**item, "bbox": [80, 10, 180, 50]}
        second = tracker.update([moved], 1)[0][1]
        self.assertEqual(first.track_id, second.track_id)
        self.assertEqual(second.best(2)[0], "123가4567")

    def test_new_plate_clears_stale_votes_after_two_mismatches(self):
        tracker = Tracker()
        old = {"bbox": [0, 0, 100, 40], "plate_text": "167모3942", "raw_text": "167모3942", "format_valid": True, "ocr_confidence": 0.9}
        track = tracker.update([old], 0)[0][1]
        tracker.update([old], 1)
        tracker.update([{**old, "plate_text": "8974321", "raw_text": "897 4321", "format_valid": False}], 2)
        tracker.update([{**old, "plate_text": "89714321", "raw_text": "8971 4321", "format_valid": False}], 3)
        self.assertIsNone(track.best(2))
        new = {**old, "plate_text": "89가4321", "raw_text": "89가4321"}
        tracker.update([new], 4)
        self.assertEqual(track.readings[-1][0], "89가4321")

    def test_tiny_crop_is_scaled_by_height(self):
        image = np.zeros((20, 120, 3), dtype=np.uint8)
        resized = resize_for_ocr(image)
        self.assertGreaterEqual(resized.shape[0], 128)
        self.assertGreaterEqual(resized.shape[1], 640)

    def test_nms_removes_duplicate_detection(self):
        detector = PlateDetector.__new__(PlateDetector)
        detector.nms_iou = 0.45
        boxes = [([0, 0, 100, 40], 0.9), ([2, 1, 102, 41], 0.8), ([200, 0, 300, 40], 0.7)]
        self.assertEqual(len(detector._nms(boxes)), 2)


if __name__ == "__main__":
    unittest.main()
