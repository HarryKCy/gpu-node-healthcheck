"""Guard dashboard layout, metric references and missing-data semantics."""
import json
from pathlib import Path
import re
import unittest

from prometheus import format_metrics
from test_exporter import SNAPSHOT

ROOT = Path(__file__).resolve().parents[1]


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.dashboard = json.loads((ROOT / 'dashboards/gpu-node-overview.json').read_text())
        self.panels = self.dashboard['panels']

    def test_stable_identity_and_datasource(self):
        self.assertEqual(self.dashboard['uid'], 'adk8tqs')
        self.assertNotIn('__inputs', self.dashboard)
        for panel in self.panels:
            if panel['type'] != 'row':
                self.assertEqual(panel['datasource']['uid'], 'gpu-node-prometheus')
                self.assertEqual(panel['pluginVersion'], '12.2.0')

    def test_layout_has_no_overlap_or_duplicate_ids(self):
        self.assertEqual(len(self.panels), len({panel['id'] for panel in self.panels}))
        occupied = set()
        for panel in self.panels:
            grid = panel['gridPos']
            self.assertLessEqual(grid['x'] + grid['w'], 24)
            for x in range(grid['x'], grid['x'] + grid['w']):
                for y in range(grid['y'], grid['y'] + grid['h']):
                    self.assertNotIn((x, y), occupied)
                    occupied.add((x, y))

    def test_queries_use_exported_metric_names(self):
        snapshot = {**SNAPSHOT, 'network': [{'name': 'eth0', **dict.fromkeys(
            ('rx_bytes', 'tx_bytes', 'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped'), 0)}],
            'gpu': {'state': 'ok', 'devices': [{'index': '0', 'name': 'test', 'temp_c': 40,
                    'util_pct': 10, 'memory_used_mib': 100, 'memory_total_mib': 1000}]}}
        metrics = set(re.findall(r'^# TYPE (\w+)', format_metrics(snapshot), re.MULTILINE))
        for panel in self.panels:
            for target in panel.get('targets', []):
                for name in re.findall(r'\bgpu_node_\w+', target['expr']):
                    self.assertIn(name, metrics)
                self.assertNotIn('or vector(0)', target['expr'])

    def test_status_is_current_and_gaps_are_visible(self):
        for panel in self.panels:
            if panel['type'] == 'stat':
                expected = 'Unavailable' if panel['title'] == 'Detected GPUs' else 'No telemetry'
                self.assertEqual(panel['fieldConfig']['defaults']['noValue'], expected)
                for target in panel['targets']:
                    self.assertTrue(target['instant'])
                    self.assertFalse(target['range'])
            if panel['type'] == 'timeseries':
                self.assertFalse(panel['fieldConfig']['defaults']['custom']['spanNulls'])
