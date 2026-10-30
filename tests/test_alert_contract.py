import unittest
from pathlib import Path
class AlertContract(unittest.TestCase):
    def test_rule_has_unavailable_detector(self):
        path=Path(__file__).resolve().parents[1]/'monitoring'/'alerts/gpu-node.yml'
        rule=path.read_text()
        self.assertIn('GPUNodeExporterUnavailable',rule)
        self.assertIn('up{job="gpu-node-healthcheck"} == 0',rule)
        self.assertIn('for: 2m',rule)
