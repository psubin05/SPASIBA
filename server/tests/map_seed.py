"""테스트용 지도 데이터: 수빈의 샘플 지도 map/b2.json(subin_server d36f941)과 같은 ID."""
from __future__ import annotations

from app.models_map import Camera, MapNode, ParkingSlot, Zone

ZONES = [("B2-A", "B2", "A"), ("B2-B", "B2", "B")]
CAMERAS = [("CAM-B2-01", "B2-A"), ("CAM-B2-02", "B2-B")]
SLOTS = [f"B2-A-0{i}" for i in range(1, 5)] + [f"B2-B-0{i}" for i in range(1, 5)]


def seed_map(session) -> None:
    # relationship()을 두지 않아 한 번의 flush에서는 FK 순서가 보장되지 않음 → 표마다 flush
    session.add_all([Zone(zone_id=z, floor=f, name=n) for z, f, n in ZONES])
    session.flush()
    session.add_all([Camera(camera_id=c, zone_id=z, description="test") for c, z in CAMERAS])
    session.flush()
    for i, slot_id in enumerate(SLOTS):
        zone_id = slot_id[:4]
        node_id = f"N-{slot_id[3]}{slot_id[-2:]}"
        session.add(MapNode(node_id=node_id, floor="B2", x=float(i), y=0.0, type="slot_front"))
        session.flush()
        session.add(ParkingSlot(slot_id=slot_id, zone_id=zone_id, camera_id='CAM-B2-01' if zone_id == 'B2-A' else 'CAM-B2-02',
                                name=slot_id[3:], node_id=node_id))
    session.commit()
