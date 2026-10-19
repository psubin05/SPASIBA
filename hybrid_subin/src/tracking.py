from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import re


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def center_distance_ratio(a, b):
    ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    scale = max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1], 1)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 / scale


@dataclass
class Track:
    track_id: int
    bbox: list[int]
    last_frame: int
    readings: deque = field(default_factory=lambda: deque(maxlen=10))
    mismatch_streak: int = 0

    def _current_consensus_text(self):
        result = self.best(2)
        return result[0] if result else None

    def add(self, result, frame):
        self.bbox, self.last_frame = list(result["bbox"]), frame
        stable_text = self._current_consensus_text()
        observed = result["plate_text"] if result["format_valid"] else re.sub(r"[^0-9가-힣]", "", result.get("raw_text", ""))
        if stable_text and observed:
            if observed == stable_text:
                self.mismatch_streak = 0
            else:
                self.mismatch_streak += 1
                if self.mismatch_streak >= 2:
                    self.readings.clear()
                    self.mismatch_streak = 0
        if result["format_valid"]:
            self.readings.append((result["plate_text"], result["ocr_confidence"]))

    def best(self, minimum=2):
        scores, counts = defaultdict(float), defaultdict(int)
        for text, confidence in self.readings:
            scores[text] += confidence
            counts[text] += 1
        if not scores:
            return None
        text = max(scores, key=lambda value: (counts[value], scores[value]))
        return (text, scores[text] / counts[text], counts[text]) if counts[text] >= minimum else None


class Tracker:
    def __init__(self, threshold=0.15, max_age=30, center_threshold=1.2):
        self.threshold, self.max_age, self.center_threshold, self.next_id = threshold, max_age, center_threshold, 1
        self.tracks = {}

    def update(self, results, frame):
        self.tracks = {key: value for key, value in self.tracks.items() if frame - value.last_frame <= self.max_age}
        available, output = set(self.tracks), []
        for result in results:
            matches = [
                (iou(result["bbox"], self.tracks[key].bbox), -center_distance_ratio(result["bbox"], self.tracks[key].bbox), key)
                for key in available
            ]
            score, negative_distance, key = max(matches, default=(0, float("-inf"), -1))
            distance = -negative_distance
            if score < self.threshold and distance > self.center_threshold:
                key, self.next_id = self.next_id, self.next_id + 1
                self.tracks[key] = Track(key, list(result["bbox"]), frame)
            else:
                available.remove(key)
            self.tracks[key].add(result, frame)
            output.append((result, self.tracks[key]))
        return output
