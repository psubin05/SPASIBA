"""Validated in-memory map cache, loaded once at application startup."""

import json
import math
from pathlib import Path

from server.route import validate_map


def validate_demo_layout(data):
    layout = data.get('demo_layout')
    if layout is None:
        return
    board = layout['board']
    for key in ('x', 'y', 'width', 'depth'):
        if not math.isfinite(board[key]):
            raise ValueError('Invalid board dimension')
    if board['width'] <= 0 or board['depth'] <= 0:
        raise ValueError('Board dimensions must be positive')

    def inside(x, y):
        return board['x'] <= x <= board['x'] + board['width'] and board['y'] <= y <= board['y'] + board['depth']

    for slot in data['slots']:
        if not slot.get('polygon') or any(not inside(x, y) for x, y in slot['polygon']):
            raise ValueError('Simulator slots must have polygons inside the board')
    for node in data['nodes']:
        if not inside(node['x'], node['y']):
            raise ValueError('Walking node is outside the board')
    cameras = {c['camera_id'] for c in data['cameras']}
    mounts = layout['camera_mounts']
    if len({m['camera_id'] for m in mounts}) != len(mounts):
        raise ValueError('Duplicate camera mount')
    for mount in mounts:
        if mount['camera_id'] not in cameras or not inside(mount['x'], mount['y']) or not math.isfinite(mount['height']) or mount['height'] <= 0:
            raise ValueError('Invalid camera mount')
    for shape in [layout['aisle'], *layout['walls'], *layout.get('aisles', []), *layout.get('sidewalks', []),
                  *layout.get('crosswalks', [])]:
        if any(not math.isfinite(shape[k]) for k in ('x', 'y', 'width', 'depth')) or shape['width'] <= 0 or shape['depth'] <= 0:
            raise ValueError('Invalid board geometry')
        if not inside(shape['x'], shape['y']) or not inside(shape['x'] + shape['width'], shape['y'] + shape['depth']):
            raise ValueError('Geometry is outside the board')
        if 'height' in shape and (not math.isfinite(shape['height']) or shape['height'] < 0):
            raise ValueError('Invalid wall height')
    for point in [*layout.get('gates', []), *([layout['entry_camera']] if layout.get('entry_camera') else [])]:
        if not inside(point['x'], point['y']):
            raise ValueError('Marker is outside the board')


class MapStore:
    def __init__(self, path):
        self.data = json.loads(Path(path).read_text(encoding='utf-8'))
        self.nodes, self.graph = validate_map(self.data)
        validate_demo_layout(self.data)
        self.qrs = {q['location_id']: q for q in self.data['qr_locations']}
        self.slots = {s['slot_id']: s for s in self.data['slots']}

    def public_map(self):
        return {key: self.data[key] for key in ('floor', 'nodes', 'edges', 'slots')}
