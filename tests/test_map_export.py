import copy
import json
from pathlib import Path
import unittest

from tools.export_map_sql import export_sql

DATA = json.loads((Path(__file__).resolve().parents[1] / 'map/b2.json').read_text(encoding='utf-8'))


class ExportTests(unittest.TestCase):
    def test_all_map_entities_exported_without_delete(self):
        sql = export_sql(DATA)
        self.assertEqual(sql.count('INSERT INTO '), 40)
        self.assertIn('BEGIN;', sql)
        self.assertTrue(sql.endswith('COMMIT;\n'))
        self.assertNotIn('DELETE FROM', sql)
        self.assertNotIn('DROP TABLE', sql)

    def test_quotes_and_json_geometry_are_safe(self):
        data = copy.deepcopy(DATA)
        data['slots'][0]['name'] = "A's slot"
        sql = export_sql(data)
        self.assertIn("'A''s slot'", sql)
        self.assertIn('::jsonb', sql)
        self.assertIn('ON CONFLICT (slot_id) DO UPDATE', sql)

    def test_invalid_reference_rejected_before_export(self):
        data = copy.deepcopy(DATA)
        data['slots'][0]['camera_id'] = 'missing'
        with self.assertRaises(ValueError):
            export_sql(data)
