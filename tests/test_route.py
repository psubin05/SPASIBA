import copy
import json
from pathlib import Path
import unittest

import networkx as nx

from server.route import route, shortest_path, validate_map
from server.map_store import validate_demo_layout

DATA = json.loads((Path(__file__).resolve().parents[1] / 'map/b2.json').read_text(encoding='utf-8'))


class RouteTests(unittest.TestCase):
    def test_every_pair_matches_networkx(self):
        _, graph = validate_map(DATA)
        reference = nx.Graph()
        for a, neighbors in graph.items():
            for b, weight in neighbors:
                reference.add_edge(a, b, weight=weight)
        for a in graph:
            for b in graph:
                self.assertEqual(shortest_path(graph, a, b)[0], nx.shortest_path_length(reference, a, b, weight='weight'))

    def test_sample_route_and_turn(self):
        result = route(DATA, 'QR-B2-ENT1', 'B2-A-03')
        self.assertEqual(result['distance_m'], 16)
        self.assertEqual(result['steps'], ['15m 직진 후 좌회전', '1m 직진', 'A-03 도착'])

    def test_invalid_maps(self):
        for mutation in ('distance', 'reference', 'disconnected'):
            data = copy.deepcopy(DATA)
            if mutation == 'distance':
                data['edges'][0]['length_m'] = -1
            elif mutation == 'reference':
                data['slots'][0]['node_id'] = 'missing'
            else:
                data['nodes'].append({'node_id': 'isolated', 'floor': 'B2', 'x': 99, 'y': 99})
            with self.assertRaises(ValueError):
                validate_map(data)

    def test_unknown_and_unreachable(self):
        with self.assertRaises(KeyError):
            route(DATA, 'unknown', 'B2-A-03')
        with self.assertRaises(ValueError):
            shortest_path({'a': [], 'b': []}, 'a', 'b')

    def test_right_turn_and_geometry_validation(self):
        self.assertEqual(route(DATA, 'QR-B2-ENT1', 'B2-B-03')['steps'][0], '15m 직진 후 우회전')
        for kind in ('slot', 'camera', 'board', 'duplicate_edge'):
            data = copy.deepcopy(DATA)
            if kind == 'slot':
                data['slots'][0]['polygon'][0] = [999, 999]
            elif kind == 'camera':
                data['demo_layout']['camera_mounts'][0]['camera_id'] = 'missing'
            elif kind == 'board':
                data['demo_layout']['board']['width'] = 0
            else:
                data['edges'].append(dict(data['edges'][0]))
            with self.assertRaises(ValueError):
                validate_map(data)
                validate_demo_layout(data)


if __name__ == '__main__':
    unittest.main()
