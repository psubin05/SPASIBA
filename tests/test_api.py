import unittest

from fastapi.testclient import TestClient

from server.app import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_qr_to_route_contract(self):
        qr = self.client.get('/qr/QR-B2-ENT1').json()
        self.assertEqual(set(qr), {'location_id', 'name', 'floor', 'node_id'})
        data = self.client.get('/route', params={'from': qr['location_id'], 'to': 'B2-A-03'}).json()
        self.assertEqual(set(data), {'from', 'to_slot', 'floor', 'distance_m', 'path', 'steps'})
        self.assertEqual(data['distance_m'], 16)
        self.assertEqual(data['path'][0]['node'], qr['node_id'])
        self.assertEqual(set(data['path'][0]), {'node', 'x', 'y'})

    def test_every_qr_slot_route(self):
        store = self.client.app.state.maps
        for qr in store.qrs:
            for slot in store.slots:
                response = self.client.get('/route', params={'from': qr, 'to': slot})
                self.assertEqual(response.status_code, 200)

    def test_errors_use_shared_envelope(self):
        for url, status in [('/qr/missing', 404), ('/map?floor=B9', 404),
                            ('/route?from=QR-B2-ENT1&to=missing', 404), ('/route', 422), ('/missing', 404)]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status)
            self.assertEqual(set(response.json()['error']), {'code', 'message'})

    def test_map_health_and_simulator(self):
        data = self.client.get('/map?floor=B2').json()
        self.assertEqual(set(data), {'floor', 'nodes', 'edges', 'slots'})
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertIn('모형 주차장 시뮬레이터', self.client.get('/simulator').text)

    def test_simulator_assets_and_shared_geometry(self):
        meta = self.client.get('/simulator/layout').json()
        self.assertTrue(meta['sample'])
        self.assertEqual(meta['layout']['status'], 'prototype_unmeasured')
        data = self.client.get('/map?floor=B2').json()
        for slot in data['slots']:
            self.assertEqual(len(slot['polygon']), 4)
            self.assertIn(slot['node_id'], self.client.app.state.maps.nodes)
        self.assertEqual(self.client.get('/simulator/assets/app.js').status_code, 200)
        self.assertEqual(self.client.get('/simulator/assets/style.css').status_code, 200)


if __name__ == '__main__':
    unittest.main()
