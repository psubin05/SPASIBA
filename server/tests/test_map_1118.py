"""MAP_FILE=map/b2_layout_1118.json 으로 11/18 회의 배치(18칸)를 쓰는 앱 전체 흐름."""
import json
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MAP_1118 = 'map/b2_layout_1118.json'


@pytest.fixture
def app1118(settings):
    cfg = replace(settings, seed_sample_map=True, simulator_enabled=True, map_file=MAP_1118)
    with TestClient(create_app(cfg)) as client:
        yield client


def test_map_file_setting_from_env(monkeypatch):
    monkeypatch.setenv('MAP_FILE', MAP_1118)
    assert Settings.from_env().map_file == MAP_1118
    monkeypatch.delenv('MAP_FILE')
    assert Settings.from_env().map_file == 'map/b2.json'


def test_map_and_simulator_layout_use_selected_file(app1118):
    data = app1118.get('/map', params={'floor': 'B2'}).json()
    assert len(data['slots']) == 18
    layout = app1118.get('/simulator/layout').json()
    assert layout['layout']['title'].startswith('B2 · 18면')
    assert {q['location_id'] for q in layout['qr_locations']} == {'QR-B2-ENT1', 'QR-B2-ENT2'}
    assert len(layout['layout']['aisles']) == 3 and len(layout['layout']['crosswalks']) == 6


def test_c_slot_event_matches_and_routes(app1118):
    assert app1118.post('/entries', json={'plate_number': '12가3456'}).status_code == 201
    event = {'event_id': str(uuid4()), 'plate_number': '12가3456', 'camera_id': 'CAM-B2-03', 'slot_id': 'B2-C-01',
             'recognized_at': datetime.now(timezone.utc).isoformat(), 'votes': 7, 'frames': 9}
    result = app1118.app.state.mqtt.handler.handle('spasiba/CAM-B2-03/event',
                                                   json.dumps(event, ensure_ascii=False).encode(),
                                                   datetime.now(timezone.utc))
    assert result == 'assigned'
    loc = app1118.get('/vehicles/12가3456/last-location').json()
    assert (loc['status'], loc['slot_id'], loc['zone_id'], loc['slot_name']) == ('CONFIRMED', 'B2-C-01', 'B2-C', 'C-01 장애인')
    path = app1118.get('/route', params={'from': 'QR-B2-ENT2', 'to': 'B2-C-01'}).json()
    assert path['distance_m'] == 29.3 and path['steps'][-1] == 'C-01 장애인 도착'


def test_default_map_unchanged(integrated_default):
    assert len(integrated_default.get('/map', params={'floor': 'B2'}).json()['slots']) == 8


@pytest.fixture
def integrated_default(settings):
    with TestClient(create_app(replace(settings, seed_sample_map=True, simulator_enabled=True))) as client:
        yield client
