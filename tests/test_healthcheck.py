import argparse
import unittest
from unittest.mock import patch
import healthcheck

class HealthCheckTest(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(memory_critical=90, disk_critical=90, load_critical=2, gpu_temp_critical=85, require_gpu=False)
    def test_good(self):
        self.assertEqual(healthcheck.check(20, 30, 0.5, {'state':'not_installed','devices':[]}, self.args), [])
    def test_alerts(self):
        self.assertEqual(len(healthcheck.check(95, 95, 3, {'state':'ok','devices':[{'index':'0','temp_c':90}]}, self.args)), 4)
    def test_gpu_required(self):
        self.args.require_gpu = True
        self.assertEqual(len(healthcheck.check(20, 30, 0.5, {'state':'not_installed','devices':[]}, self.args)), 1)
    @patch('healthcheck.subprocess.run')
    def test_gpu_parser(self, mock):
        mock.return_value.returncode = 0
        mock.return_value.stdout = '0, NVIDIA H200, 48, 20, 1024, 141312\n'
        self.assertEqual(healthcheck.gpu_metrics()['devices'][0]['temp_c'], 48)

if __name__ == '__main__': unittest.main()
