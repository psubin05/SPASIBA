"""Server-side v0.4 MQTT camera and parking-slot identifiers."""
import re

CAMERA_ID_RE = re.compile(r"CAM-[A-Za-z0-9]+-[0-9]{2}")
SLOT_ID_RE = re.compile(r"[A-Za-z0-9]+-[A-Za-z0-9]+-[0-9]{2}")
