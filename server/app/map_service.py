"""Shared DB map data for QR/routing and the simulator (Subin)."""
from pathlib import Path
import json

from sqlalchemy import select

from .models_map import Zone, Camera, MapNode, MapEdge, ParkingSlot, QrLocation
from .map_route import validate_map
from .parking import ParkingError

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / 'map/b2.json'


def sample_data():
    return json.loads(SAMPLE.read_text(encoding='utf-8'))


def seed_sample(database):
    """Explicit opt-in, empty DB only. Never overwrite a team's existing map."""
    data = sample_data()
    validate_map(data)
    with database.SessionLocal() as db:
        models = (Zone, Camera, MapNode, MapEdge, ParkingSlot, QrLocation)
        if any(db.scalars(select(model).limit(1)).first() is not None for model in models):
            return False
        for model, key in ((Zone,'zones'),(Camera,'cameras'),(MapNode,'nodes'),
                           (ParkingSlot,'slots'),(MapEdge,'edges'),(QrLocation,'qr_locations')):
            columns = set(model.__table__.columns.keys())
            for row in data[key]:
                db.add(model(**{k:v for k,v in row.items() if k in columns}))
            db.flush()
        db.commit()
    return True


def read_map(db, floor):
    nodes = db.scalars(select(MapNode).where(MapNode.floor == floor)).all()
    if not nodes:
        raise ParkingError(404, 'NOT_FOUND', '해당 층의 지도가 없습니다.')
    node_ids = {n.node_id for n in nodes}
    zones = db.scalars(select(Zone).where(Zone.floor == floor)).all()
    zone_ids = {z.zone_id for z in zones}
    slots = db.scalars(select(ParkingSlot).where(ParkingSlot.zone_id.in_(zone_ids))).all()
    cameras = db.scalars(select(Camera).where(Camera.camera_id.in_({s.camera_id for s in slots}))).all()
    edges = db.scalars(select(MapEdge).where(MapEdge.from_node.in_(node_ids), MapEdge.to_node.in_(node_ids))).all()
    qrs = db.scalars(select(QrLocation).where(QrLocation.floor == floor)).all()
    def records(rows):
        return [{column.name:getattr(row,column.name) for column in row.__table__.columns} for row in rows]
    data = {'floor':floor,'nodes':records(nodes),'edges':records(edges),'slots':records(slots),
            'zones':records(zones),'cameras':records(cameras),'qr_locations':records(qrs)}
    try:
        validate_map(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ParkingError(503, 'MAP_INVALID', '지도 연결 정보를 확인해주세요.') from exc
    return data
