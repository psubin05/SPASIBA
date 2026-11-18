"""11/18 회의 정리본 지도 (map/b2_layout_1118.json, tools/make_layout_1118.py로 생성)."""
import json
import unittest
from pathlib import Path

from server.map_store import validate_demo_layout
from server.route import route, validate_map
from tools.make_layout_1118 import build

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'map/b2_layout_1118.json').read_text(encoding='utf-8'))


class Layout1118Test(unittest.TestCase):
    def test_file_matches_generator(self):
        self.assertEqual(DATA, json.loads(json.dumps(build())), '지도를 고쳤으면 python -m tools.make_layout_1118 로 다시 생성')

    def test_valid_map_and_layout(self):
        validate_map(DATA)
        validate_demo_layout(DATA)

    def test_slots_follow_drawing(self):
        ids = [s['slot_id'] for s in DATA['slots']]
        self.assertEqual(len(ids), 18)
        self.assertEqual([i for i in ids if i.startswith('B2-C-')], [f'B2-C-0{n}' for n in range(1, 7)])
        self.assertEqual([i for i in ids if i.startswith('B2-A-')], [f'B2-A-0{n}' for n in range(1, 7)])
        self.assertEqual([i for i in ids if i.startswith('B2-B-')], ['B2-B-01', 'B2-B-02', 'B2-B-03', 'B2-B-05', 'B2-B-06', 'B2-B-07'])
        names = {s['slot_id']: s['name'] for s in DATA['slots']}
        self.assertEqual([names[f'B2-C-0{n}'].split()[1] for n in range(1, 7)], ['장애인', '장애인', '임산부', '임산부', '경차', '경차'])
        cameras = {s['slot_id']: s['camera_id'] for s in DATA['slots']}
        self.assertEqual({cameras[i] for i in ids if '-A-' in i}, {'CAM-B2-01'})
        self.assertEqual({cameras[i] for i in ids if '-B-' in i}, {'CAM-B2-02'})
        self.assertEqual({cameras[i] for i in ids if '-C-' in i}, {'CAM-B2-03'})

    def test_c_slot_fronts_on_top_sidewalk(self):
        nodes = {n['node_id']: n for n in DATA['nodes']}
        walk = DATA['demo_layout']['sidewalks'][0]
        for slot in DATA['slots']:
            if slot['zone_id'] == 'B2-C':
                n = nodes[slot['node_id']]
                self.assertTrue(walk['y'] <= n['y'] <= walk['y'] + walk['depth'])

    def test_every_slot_reachable_from_every_qr_with_clean_distance(self):
        cache = validate_map(DATA)
        for qr in DATA['qr_locations']:
            for slot in DATA['slots']:
                result = route(DATA, qr['location_id'], slot['slot_id'], cache=cache)
                self.assertGreater(result['distance_m'], 0)
                self.assertEqual(result['distance_m'], round(result['distance_m'], 2), result['distance_m'])
                self.assertTrue(result['steps'][-1].endswith('도착'))


if __name__ == '__main__':
    unittest.main()
