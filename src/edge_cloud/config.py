from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    camera_id: str
    zone_id: str | None = None  # Legacy metadata; slot ownership is per slot.
    host: str = ""
    port: int = 8883
    tls: bool = True
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    ca: str | None = None
    cert: str | None = None
    key: str | None = field(default=None, repr=False)
    database: str = "outputs/edge-v04/events.sqlite3"
    min_votes: int = 5
    single_slot: str | None = None
    rois: dict = field(default_factory=dict)
    # Explicit rehearsal opt-in; this does NOT detect that a vehicle stopped.
    publish_on_consensus: bool = False
    crop_enabled: bool = False
    crop_ttl: float = 600.0
    max_pending: int = 10000

    def __post_init__(self):
        if self.zone_id is not None and not re.fullmatch(r"[A-Za-z0-9]+-[A-Za-z0-9]+", self.zone_id):
            raise ValueError("invalid zone_id")
        if not re.fullmatch(r"CAM-[A-Za-z0-9]+-[0-9]{2}", self.camera_id):
            raise ValueError("camera_id must have format CAM-{floor}-{number}")
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("invalid MQTT port")
        if not 1 <= self.min_votes <= 10 or self.max_pending < 1 or self.crop_ttl <= 0:
            raise ValueError("invalid votes/queue/crop limit")
        for value in (self.tls, self.publish_on_consensus, self.crop_enabled):
            if not isinstance(value, bool):
                raise ValueError("boolean settings must be JSON true/false")
        if not self.tls and self.host not in ("localhost", "127.0.0.1", "::1", ""):
            raise ValueError("plaintext MQTT is allowed only on loopback for tests")
        if bool(self.cert) != bool(self.key):
            raise ValueError("client cert and key must be configured together")
        for path in (self.ca, self.cert, self.key):
            if path and not Path(path).is_file():
                raise ValueError("TLS certificate/key path does not exist")
        if self.single_slot and self.rois:
            raise ValueError("choose single_slot or rois, not both")
        for slot in ([self.single_slot] if self.single_slot else []) + list(self.rois):
            if not re.fullmatch(r"[A-Za-z0-9]+-[A-Za-z0-9]+-[0-9]{2}", slot):
                raise ValueError("slot_id must have format {floor}-{zone}-{number}")
        for polygon in self.rois.values():
            if len(polygon) < 3 or any(len(p) != 2 or any(not isinstance(v, (int, float)) for v in p) for p in polygon):
                raise ValueError("ROI requires at least three pixel coordinate pairs")

    @classmethod
    def load(cls, path):
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        values.pop("status_topic", None)  # v0.4 fixes the status topic.
        for key in ("host", "username", "password", "ca", "cert", "key", "database", "zone_id", "camera_id"):
            env = os.getenv("SPASIBA_" + key.upper())
            if env is not None:
                values[key] = env
        if os.getenv("SPASIBA_PORT"):
            values["port"] = int(os.environ["SPASIBA_PORT"])
        return cls(**values)

    def topic(self, suffix):
        return f"spasiba/{self.camera_id}/{suffix}"
