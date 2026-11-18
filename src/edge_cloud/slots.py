from enum import Enum


class Occupancy(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    UNKNOWN = "UNKNOWN"


def contains(polygon, point):
    x, y = point
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y):
            crossing = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < crossing:
                inside = not inside
    return inside


class SlotResolver:
    """ROI bbox-centre candidates only; no motion/occupancy inference."""
    def __init__(self, config):
        self.config = config

    def candidates(self, bbox):
        if self.config.single_slot:
            return [self.config.single_slot]
        if not bbox or len(bbox) != 4:
            return []
        point = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        return [slot for slot, polygon in self.config.rois.items() if contains(polygon, point)]

    def resolve(self, bbox):
        matches = self.candidates(bbox)
        return matches[0] if len(matches) == 1 else None
