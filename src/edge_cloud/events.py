from __future__ import annotations
from collections import Counter
from datetime import datetime
import re
import unicodedata
import uuid
from postprocessing import FULLWIDTH_DIGITS, REGIONS, USE_CHARS

PATTERN = re.compile(rf"(?:{'|'.join(REGIONS)})?[0-9]{{2,3}}[{USE_CHARS}][0-9]{{4}}")


def now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def normalize_plate(text):
    text = unicodedata.normalize("NFC", text or "")
    text = text.translate(FULLWIDTH_DIGITS)
    return re.sub(r"[\s\-·]", "", text)


def consensus(readings, minimum=5):
    """Use exactly the track's retained valid readings, at most ten."""
    valid = [normalize_plate(row[0]) for row in list(readings)[-10:]]
    valid = [text for text in valid if PATTERN.fullmatch(text)]
    if not valid:
        return None
    counts = Counter(valid)
    text, votes = counts.most_common(1)[0]
    if votes < minimum or sum(v == votes for v in counts.values()) != 1:
        return None
    return text, votes, len(valid)


def make_event(config, slot, reading):
    plate, votes, frames = reading
    if not PATTERN.fullmatch(plate) or not 1 <= votes <= frames <= 10:
        raise ValueError("invalid plate or votes")
    return dict(event_id=str(uuid.uuid4()), plate_number=plate,
                camera_id=config.camera_id, slot_id=slot,
                recognized_at=now(), votes=votes, frames=frames, kind="confirm")
