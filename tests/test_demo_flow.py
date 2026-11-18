from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
import sqlite3
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from server.legacy_app import create_app
from server.demo_parking import edit_distance, EntryInput, DemoError


class DemoFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'demo.sqlite3'
        self.client = TestClient(create_app(demo_db=self.path))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def event(self, plate='12가3456', slot='B2-A-03', **changes):
        registered = self.client.app.state.maps.slots[slot]
        payload = {'event_id': str(uuid4()), 'plate_number': plate, 'slot_id': slot,
                   'zone_id': registered['zone_id'], 'camera_id': registered['camera_id'],
                   'recognized_at': datetime.now(timezone.utc).isoformat(), 'votes': 5, 'frames': 7}
        payload.update(changes)
        return payload

    def location(self, plate='12가3456'):
        return self.client.get(f'/vehicles/{plate}/last-location')

    def test_entry_pending_parking_qr_route_exit_and_reentry(self):
        entry = self.client.post('/entries', json={'plate_number': '１２ 가-3456'})
        self.assertEqual(entry.status_code, 201)
        self.assertEqual(self.location().json()['status'], 'PENDING')
        self.assertEqual(self.client.post('/entries', json={'plate_number': '12가3456'}).status_code, 409)
        payload = self.event()
        self.assertEqual(self.client.post('/simulator/events', json=payload).json()['method'], 'EXACT')
        self.assertEqual(self.client.post('/simulator/events', json=payload).json()['status'], 'DUPLICATE')
        location = self.location().json()
        self.assertEqual(location['status'], 'CONFIRMED')
        qr = self.client.get('/qr/QR-B2-ENT1').json()
        result = self.client.get('/route', params={'from': qr['location_id'], 'to': location['slot_id']})
        self.assertEqual(result.json()['distance_m'], 16)
        self.assertEqual(self.client.post('/exits', json={'session_id': entry.json()['session_id']}).status_code, 200)
        self.assertEqual(self.location().status_code, 404)
        self.client.post('/simulator/events', json=self.event())
        self.assertEqual(self.location().status_code, 404)
        later = self.client.post('/entries', json={'plate_number': '12가3456'})
        self.assertNotEqual(later.json()['session_id'], entry.json()['session_id'])
        self.assertEqual(self.location().json()['status'], 'PENDING')

    def test_records_survive_app_restart(self):
        self.client.post('/entries', json={'plate_number': '12가3456'})
        self.client.post('/simulator/events', json=self.event())
        with TestClient(create_app(demo_db=self.path)) as client:
            self.assertEqual(client.get('/vehicles/12가3456/last-location').json()['slot_id'], 'B2-A-03')

    def test_invalid_event_is_recorded_but_not_matched(self):
        self.client.post('/entries', json={'plate_number': '12가3456'})
        payload = self.event(camera_id='wrong')
        self.assertEqual(self.client.post('/simulator/events', json=payload).json()['status'], 'INVALID')
        self.assertEqual(self.location().json()['status'], 'PENDING')

    def test_unique_edit1_and_ambiguous_candidates(self):
        self.client.post('/entries', json={'plate_number': '12가3456'})
        self.assertEqual(self.client.post('/simulator/events', json=self.event('12가3458')).json()['method'], 'EDIT1')
        self.client.post('/entries', json={'plate_number': '12가3459'})
        self.assertEqual(self.client.post('/simulator/events', json=self.event('12가3458')).json()['status'], 'PENDING')
        self.assertEqual(edit_distance('서울12가3456', '부산12가3456'), 1)

    def test_slot_replacement_and_move(self):
        self.client.post('/entries', json={'plate_number': '12가3456'})
        self.client.post('/entries', json={'plate_number': '34나5678'})
        self.client.post('/simulator/events', json=self.event())
        self.client.post('/simulator/events', json=self.event('34나5678'))
        self.assertEqual(self.location().json()['status'], 'PENDING')
        self.client.post('/simulator/events', json=self.event('34나5678', 'B2-B-03'))
        self.assertEqual(self.location('34나5678').json()['slot_id'], 'B2-B-03')

    def test_demo_routes_are_disabled_in_map_only_app(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.post('/entries', json={'plate_number': '12가3456'}).status_code, 404)

    def test_bad_inputs(self):
        for payload in ({'plate_number': 'bad'}, {'plate_number': '12가3456', 'entered_at': '2026-11-17T00:00:00'}):
            self.assertEqual(self.client.post('/entries', json=payload).status_code, 422)
        self.assertEqual(self.client.post('/exits', json={}).status_code, 422)
        self.assertEqual(self.client.post('/simulator/events', json=self.event(votes=8, frames=5)).status_code, 422)

    def test_old_and_equal_time_observations_cannot_move_vehicle_back(self):
        base = datetime.now(timezone.utc) - timedelta(seconds=10)
        self.client.post('/entries', json={'plate_number': '12가3456', 'entered_at': (base - timedelta(seconds=10)).isoformat()})
        self.client.post('/simulator/events', json=self.event(recognized_at=base.isoformat()))
        self.client.post('/simulator/events', json=self.event(slot='B2-B-03', recognized_at=(base + timedelta(seconds=1)).isoformat()))
        stale = self.client.post('/simulator/events', json=self.event(recognized_at=base.isoformat())).json()
        self.assertEqual(stale['status'], 'STALE')
        tied = self.client.post('/simulator/events', json=self.event(recognized_at=(base + timedelta(seconds=1)).isoformat())).json()
        self.assertEqual(tied['status'], 'STALE')
        self.assertEqual(self.location().json()['slot_id'], 'B2-B-03')

    def test_same_second_timestamp_with_different_precision(self):
        base = (datetime.now(timezone.utc) - timedelta(seconds=5)).replace(microsecond=0)
        self.client.post('/entries', json={'plate_number': '12가3456', 'entered_at': base.isoformat()})
        event = self.event(recognized_at=base.isoformat(timespec='microseconds'))
        self.assertEqual(self.client.post('/simulator/events', json=event).json()['status'], 'CONFIRMED')

    def test_future_observation_and_missing_votes_do_not_confirm(self):
        self.client.post('/entries', json={'plate_number': '12가3456'})
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.assertEqual(self.client.post('/simulator/events', json=self.event(recognized_at=future)).json()['status'], 'INVALID')
        no_votes = self.event('12가3458')
        no_votes.pop('votes')
        self.assertEqual(self.client.post('/simulator/events', json=no_votes).json()['status'], 'PENDING')
        self.assertEqual(self.location().json()['status'], 'PENDING')

    def test_parallel_duplicate_entries_create_only_one_session(self):
        store = self.client.app.state.parking
        def enter(_):
            try:
                store.enter(EntryInput(plate_number='12가3456'))
                return 201
            except DemoError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(enter, range(8)))
        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(statuses.count(409), 7)
        self.assertEqual(len(store.entries('ACTIVE')), 1)

    def test_removed_slot_returns_pending_not_server_error(self):
        self.client.post('/entries', json={'plate_number': '12가3456'})
        self.client.post('/simulator/events', json=self.event())
        del self.client.app.state.maps.slots['B2-A-03']
        self.assertEqual(self.location().json()['status'], 'PENDING')

    def test_responses_are_not_cached(self):
        self.assertEqual(self.client.get('/entries').headers['cache-control'], 'no-store')

    def test_storage_failure_returns_recoverable_error(self):
        with patch.object(self.client.app.state.parking, 'entries', side_effect=sqlite3.OperationalError('database is locked')):
            response = self.client.get('/entries')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'STORAGE_UNAVAILABLE')
        self.assertNotIn('database is locked', response.text)
