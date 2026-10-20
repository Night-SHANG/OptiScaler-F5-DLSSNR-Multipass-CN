"""Reproduce fresh-clone report order differences without weakening sync gates."""
from pathlib import Path
import itertools
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from localize_f5 import write_boundary_report
from loclib import save_json
from f5_sync import write_json


class BoundaryReportTests(unittest.TestCase):
    def test_all_traversal_orders_produce_identical_utf8_lf_bytes(self):
        records = [
            {'file': 'OptiScaler/z.cpp', 'display_calls': 3},
            {'file': 'OptiScaler/a.hpp', 'display_calls': 7},
            {'file': 'OptiScaler/中.inl', 'display_calls': 2},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            outputs = []
            for order in itertools.permutations(records):
                write_boundary_report(path, list(order))
                outputs.append(path.read_bytes())
            self.assertTrue(all(data == outputs[0] for data in outputs))
            self.assertNotIn(b'\r', outputs[0])
            report = json.loads(outputs[0])
            self.assertEqual(report['calls'], 12)
            self.assertEqual(report['files'], sorted(records, key=lambda record: record['file']))

    def test_count_and_path_changes_remain_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            write_boundary_report(path, [{'file': 'a.cpp', 'display_calls': 1}])
            original = path.read_bytes()
            for record in ({'file': 'a.cpp', 'display_calls': 2},
                           {'file': 'b.cpp', 'display_calls': 1}):
                write_boundary_report(path, [record])
                self.assertNotEqual(path.read_bytes(), original)

    def test_checked_in_report_is_canonical(self):
        committed = ROOT / 'reports/display-boundaries.json'
        report = json.loads(committed.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            write_boundary_report(path, report['files'])
            self.assertEqual(path.read_bytes(), committed.read_bytes())

    def test_sync_and_catalog_json_writers_share_exact_utf8_lf_bytes(self):
        value = {'z': ['中文', 'line\nbreak'], 'a': 1}
        expected = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        with tempfile.TemporaryDirectory() as directory:
            for writer in (save_json, write_json):
                path = Path(directory) / writer.__name__ / 'result.json'
                writer(path, value)
                self.assertEqual(path.read_bytes(), expected)


if __name__ == '__main__':
    unittest.main()
