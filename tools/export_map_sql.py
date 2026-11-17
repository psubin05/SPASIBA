"""Generate a reviewable PostgreSQL schema + seed transaction. Does not connect to DB."""

import argparse
import json
from pathlib import Path

from server.route import validate_map

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    ('zone', 'zones', ('zone_id', 'floor', 'name'), ('zone_id',)),
    ('camera', 'cameras', ('camera_id', 'zone_id', 'description'), ('camera_id',)),
    ('map_node', 'nodes', ('node_id', 'floor', 'x', 'y', 'type'), ('node_id',)),
    ('parking_slot', 'slots', ('slot_id', 'zone_id', 'camera_id', 'name', 'roi', 'node_id', 'polygon'), ('slot_id',)),
    ('map_edge', 'edges', ('from_node', 'to_node', 'length_m'), ('from_node', 'to_node')),
    ('qr_location', 'qr_locations', ('location_id', 'node_id', 'floor', 'name'), ('location_id',)),
)


def literal(value, *, jsonb=False):
    if value is None:
        return 'NULL'
    if jsonb:
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def export_sql(data):
    validate_map(data)
    lines = ['-- Generated from validated map JSON; existing rows are updated, never deleted.',
             'BEGIN;', 'SET LOCAL standard_conforming_strings = on;',
             (ROOT / 'db/map_schema.sql').read_text(encoding='utf-8')]
    for table, key, columns, primary in TABLES:
        for original in data[key]:
            row = dict(original)
            if table == 'map_edge':
                row['from_node'], row['to_node'] = sorted((row['from_node'], row['to_node']))
            values = ', '.join(literal(row.get(c), jsonb=c in ('roi', 'polygon')) for c in columns)
            updates = ', '.join(f'{c} = EXCLUDED.{c}' for c in columns if c not in primary)
            lines.append(f'INSERT INTO {table} ({", ".join(columns)}) VALUES ({values}) '
                         f'ON CONFLICT ({", ".join(primary)}) DO UPDATE SET {updates};')
    lines.append('COMMIT;')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default=str(ROOT / 'map/b2.json'))
    parser.add_argument('--output', default=str(ROOT / 'db/map_seed.sql'))
    args = parser.parse_args()
    data = json.loads(Path(args.path).read_text(encoding='utf-8'))
    Path(args.output).write_text(export_sql(data), encoding='utf-8')
    print(f'Validated PostgreSQL script written: {args.output}')


if __name__ == '__main__':
    main()
