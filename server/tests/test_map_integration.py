"""Suin's real DB/matching + Subin's QR/routing; no demo_parking adapter."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.main import create_app
from app.models import ParkingEvent, SlotAssignment
from app.models_map import MapNode, Camera, ParkingSlot
from app.map_service import seed_sample


@pytest.fixture
def integrated(settings):
    cfg = replace(settings, seed_sample_map=True, simulator_enabled=True)
    with TestClient(create_app(cfg)) as client:
        yield client


def observation(slot='B2-A-03', camera='CAM-B2-01', plate='12가3456'):
    return {'event_id':str(uuid4()),'plate_number':plate,'camera_id':camera,'slot_id':slot,
            'recognized_at':datetime.now(timezone.utc).isoformat(),'votes':5,'frames':7}


def test_real_entry_mqtt_match_qr_route_and_exit(integrated):
    client = integrated
    assert client.post('/entries',json={'plate_number':'12가3456'}).status_code == 201
    assert client.get('/vehicles/12가3456/last-location').json()['status'] == 'PENDING'
    event = observation()
    handler = client.app.state.mqtt.handler
    result = handler.handle('spasiba/CAM-B2-01/event',json.dumps(event,ensure_ascii=False).encode(),datetime.now(timezone.utc))
    assert result == 'assigned'
    location = client.get('/vehicles/12가3456/last-location').json()
    assert location['status'] == 'CONFIRMED' and location['source'] == 'session'
    qr = client.get('/qr/QR-B2-ENT1').json()
    path = client.get('/route',params={'from':qr['location_id'],'to':location['slot_id']}).json()
    assert path['distance_m'] == 16
    assert path['path'][0]['node'] == qr['node_id']
    assert path['path'][-1]['node'] == location['node_id']
    with client.app.state.db.SessionLocal() as db:
        assert db.get(ParkingEvent,event['event_id']).valid
        assert db.scalars(select(SlotAssignment)).one().method == 'EXACT'
    assert client.post('/exits',json={'plate_number':'12가3456'}).status_code == 200
    assert client.get('/vehicles/12가3456/last-location').status_code == 404


def test_simulator_uses_real_matching_and_is_idempotent(integrated):
    integrated.post('/entries',json={'plate_number':'12가3456'})
    event = observation()
    assert integrated.post('/simulator/events',json=event).json()['status'] == 'assigned'
    assert integrated.post('/simulator/events',json=event).json()['status'] == 'duplicate'
    assert integrated.get('/entries?state=ACTIVE').json()[0]['slot_id'] == 'B2-A-03'
    meta = integrated.get('/simulator/layout').json()
    assert meta['matching_backend'] == 'shared'
    assert meta['demo_enabled'] and meta['vehicle_api_enabled']
    assert '모형 주차장 시뮬레이터' in integrated.get('/simulator').text


def test_simulator_input_disabled_by_default(client):
    assert client.post('/simulator/events',json=observation()).status_code == 404


def test_seed_never_overwrites_existing_map(integrated):
    with integrated.app.state.db.SessionLocal() as db:
        db.get(MapNode,'J1').x = 3.25
        db.commit()
    assert seed_sample(integrated.app.state.db) is False
    nodes = integrated.get('/map?floor=B2').json()['nodes']
    assert next(n for n in nodes if n['node_id']=='J1')['x'] == 3.25
    assert integrated.get('/simulator/layout').status_code == 503


def test_v04_camera_can_observe_slots_across_zones(integrated):
    with integrated.app.state.db.SessionLocal() as db:
        db.get(ParkingSlot,'B2-B-03').camera_id = 'CAM-B2-01'
        db.commit()
    integrated.post('/entries',json={'plate_number':'12가3456'})
    result = integrated.post('/simulator/events',json=observation(slot='B2-B-03')).json()
    assert result['status'] == 'assigned'
    path = integrated.get('/route?from=QR-B2-ENT1&to=B2-B-03').json()
    assert path['distance_m'] == 16
    assert '우회전' in path['steps'][0]


def test_invalid_camera_stored_and_does_not_assign(integrated):
    integrated.post('/entries',json={'plate_number':'12가3456'})
    event = observation(camera='CAM-B2-02')
    assert integrated.post('/simulator/events',json=event).json()['status'] == 'invalid'
    with integrated.app.state.db.SessionLocal() as db:
        assert not db.get(ParkingEvent,event['event_id']).valid
    assert integrated.get('/vehicles/12가3456/last-location').json()['status'] == 'PENDING'


def test_missing_qr_floor_and_request_values(integrated):
    for path,status in [('/qr/nope',404),('/map?floor=B99',404),('/route',422),('/map',422)]:
        response = integrated.get(path)
        assert response.status_code == status
        assert set(response.json()['error']) == {'code','message'}


def test_all_sample_slots_have_routes(integrated):
    slots = integrated.get('/map?floor=B2').json()['slots']
    for slot in slots:
        response = integrated.get('/route',params={'from':'QR-B2-ENT1','to':slot['slot_id']})
        assert response.status_code == 200
        assert response.json()['path'][-1]['node'] == slot['node_id']
