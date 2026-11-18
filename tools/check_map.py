"""python -m tools.check_map [map/b2.json] --svg map/preview.svg"""

import argparse
import html
import json
from pathlib import Path

from server.route import validate_map


def main():
    parser = argparse.ArgumentParser(description='Validate map and export a static SVG preview')
    parser.add_argument('path', nargs='?', default='map/b2.json')
    parser.add_argument('--svg')
    args = parser.parse_args()
    data = json.loads(Path(args.path).read_text(encoding='utf-8'))
    nodes, _ = validate_map(data)
    print(f"OK: {len(nodes)} nodes, {len(data['edges'])} edges, {len(data['slots'])} slots")
    if args.svg:
        xmin, xmax = min(n['x'] for n in nodes.values()), max(n['x'] for n in nodes.values())
        ymin, ymax = min(n['y'] for n in nodes.values()), max(n['y'] for n in nodes.values())
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{xmin-2} {ymin-2} {xmax-xmin+4} {ymax-ymin+4}">', '<rect x="-1000" y="-1000" width="2000" height="2000" fill="white"/>']
        for edge in data['edges']:
            a, b = nodes[edge['from_node']], nodes[edge['to_node']]
            parts.append(f'<line x1="{a["x"]}" y1="{a["y"]}" x2="{b["x"]}" y2="{b["y"]}" stroke="#a5b8c9" stroke-width="0.07"/>')
        for n in nodes.values():
            parts.append(f'<circle cx="{n["x"]}" cy="{n["y"]}" r="0.09" fill="#126b66"/><text x="{n["x"]}" y="{n["y"]-.2}" text-anchor="middle" font-size="0.22">{html.escape(n["node_id"])}</text>')
        parts.append('</svg>')
        Path(args.svg).write_text('\n'.join(parts), encoding='utf-8')
        print(f'Preview: {args.svg}')


if __name__ == '__main__':
    main()
