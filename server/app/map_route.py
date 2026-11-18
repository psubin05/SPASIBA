"""Single-floor, bidirectional pedestrian routing. Coordinates use metres, y down."""

import heapq
import math


def validate_map(data):
    nodes = {n['node_id']: n for n in data['nodes']}
    if not nodes or len(nodes) != len(data['nodes']):
        raise ValueError('Nodes must be nonempty and unique')
    graph = {key: [] for key in nodes}
    for node in nodes.values():
        if node['floor'] != data['floor'] or not all(
            math.isfinite(node[c]) for c in ('x', 'y')
        ):
            raise ValueError('Invalid node floor or coordinates')
    for edge in data['edges']:
        a, b, weight = edge['from_node'], edge['to_node'], edge['length_m']
        if a not in nodes or b not in nodes or a == b or not math.isfinite(weight) or weight <= 0:
            raise ValueError('Invalid edge endpoint or distance')
        if nodes[a]['x'] == nodes[b]['x'] and nodes[a]['y'] == nodes[b]['y']:
            raise ValueError('Walking edge has identical endpoint coordinates')
        if any(neighbor == b for neighbor, _ in graph[a]):
            raise ValueError('Duplicate bidirectional edge')
        graph[a].append((b, weight))
        graph[b].append((a, weight))
    for collection, key in [('slots', 'slot_id'), ('qr_locations', 'location_id')]:
        items = data[collection]
        if len({item[key] for item in items}) != len(items):
            raise ValueError('Duplicate identifiers')
        for item in items:
            if item['node_id'] not in nodes:
                raise ValueError('Unknown referenced node')
    zones = {z['zone_id']: z for z in data['zones']}
    cameras = {c['camera_id']: c for c in data['cameras']}
    if len(zones) != len(data['zones']) or len(cameras) != len(data['cameras']):
        raise ValueError('Duplicate zones or cameras')
    for zone in zones.values():
        if zone['floor'] != data['floor']:
            raise ValueError('Invalid zone floor')
    for camera in cameras.values():
        if camera['zone_id'] not in zones:
            raise ValueError('Unknown camera zone')
    for slot in data['slots']:
        camera = cameras.get(slot['camera_id'])
        if slot['zone_id'] not in zones or camera is None:
            raise ValueError('Invalid slot camera/zone relationship')
        polygon = slot.get('polygon')
        if polygon is not None:
            if len(polygon) < 3 or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in polygon):
                raise ValueError('Invalid slot polygon')
            area = sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1]
                       - polygon[(i + 1) % len(polygon)][0] * polygon[i][1] for i in range(len(polygon)))
            if abs(area) < 1e-9:
                raise ValueError('Slot polygon has zero area')
    for qr in data['qr_locations']:
        if qr['floor'] != data['floor']:
            raise ValueError('Invalid QR floor')
    seen, todo = set(), [next(iter(nodes))]
    while todo:
        current = todo.pop()
        if current not in seen:
            seen.add(current)
            todo.extend(n for n, _ in graph[current])
    if len(seen) != len(nodes):
        raise ValueError('Disconnected map')
    return nodes, graph


def shortest_path(graph, start, end):
    if start not in graph or end not in graph:
        raise KeyError('Unknown node')
    distances, previous = {start: 0.0}, {}
    queue = [(0.0, start)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances[node]:
            continue
        if node == end:
            path = [end]
            while path[-1] != start:
                path.append(previous[path[-1]])
            return distance, list(reversed(path))
        for neighbor, weight in graph[node]:
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor], previous[neighbor] = candidate, node
                heapq.heappush(queue, (candidate, neighbor))
    raise ValueError('No walking route')


def route(data, location_id, slot_id, *, cache=None):
    nodes, graph = cache if cache is not None else validate_map(data)
    origin = next((q for q in data['qr_locations'] if q['location_id'] == location_id), None)
    slot = next((s for s in data['slots'] if s['slot_id'] == slot_id), None)
    if origin is None or slot is None:
        raise KeyError('Unknown QR location or parking slot')
    distance, path = shortest_path(graph, origin['node_id'], slot['node_id'])
    steps, straight = [], 0.0
    for i in range(1, len(path)):
        a, b = path[i - 1], path[i]
        straight += min(w for n, w in graph[a] if n == b)
        if i < len(path) - 1:
            p, q, r = nodes[a], nodes[b], nodes[path[i + 1]]
            ux, uy = q['x'] - p['x'], q['y'] - p['y']
            vx, vy = r['x'] - q['x'], r['y'] - q['y']
            cross, dot = ux * vy - uy * vx, ux * vx + uy * vy
            if abs(cross) > 1e-9 or dot < 0:
                turn = '뒤로 돌아 이동' if abs(cross) <= 1e-9 else ('우회전' if cross > 0 else '좌회전')
                steps.append(f'{straight:g}m 직진 후 {turn}')
                straight = 0.0
    if straight:
        steps.append(f'{straight:g}m 직진')
    steps.append(f'{slot["name"]} 도착')
    return {'from': location_id, 'to_slot': slot_id, 'floor': data['floor'],
            'distance_m': distance,
            'path': [{'node': n, 'x': nodes[n]['x'], 'y': nodes[n]['y']} for n in path],
            'steps': steps}
