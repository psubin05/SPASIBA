import base64
import json
import threading
import time


def jpeg_bytes(crop):
    import cv2
    if crop is None or crop.size == 0:
        raise ValueError("empty crop")
    h, w = crop.shape[:2]
    scale = min(1.0, 640 / max(h, w))
    image = cv2.resize(crop, (max(1, int(w * scale)), max(1, int(h * scale))))
    for quality in (85, 70, 55, 40, 25):
        ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok and len(encoded) <= 100_000:
            return bytes(encoded)
    raise ValueError("crop exceeds 100KB")


class CropCache:
    """One bounded JPEG per slot. Never return a newer event's image for an old ID."""
    def __init__(self, ttl):
        self.ttl, self.entries, self.lock = ttl, {}, threading.Lock()

    def put(self, event, crop):
        from .events import now
        value = (event['event_id'], now(), time.monotonic(), jpeg_bytes(crop))
        with self.lock:
            self.entries[event['slot_id']] = value

    def response(self, payload):
        if len(payload) > 4096:
            raise ValueError("crop request too large")
        request = json.loads(payload)
        for key in ('request_id', 'event_id', 'slot_id'):
            if not isinstance(request.get(key), str) or not 1 <= len(request[key]) <= 128:
                raise ValueError("invalid crop request")
        with self.lock:
            value = self.entries.get(request['slot_id'])
            if not value:
                return None
            event_id, captured, timestamp, image = value
            if time.monotonic() - timestamp > self.ttl:
                del self.entries[request['slot_id']]
                return None
            if event_id != request['event_id']:
                return None
        return {**{k: request[k] for k in ('request_id','event_id','slot_id')},
                'captured_at': captured, 'image_jpeg_base64': base64.b64encode(image).decode('ascii')}
