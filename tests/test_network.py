"""Tests for Linux network interface monitoring."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from network import network_metrics


class NetworkMetricsTest(unittest.TestCase):

    def test_interface_counters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            iface = root / "eth0"
            stats = iface / "statistics"
            stats.mkdir(parents=True)

            (iface / "operstate").write_text("up")

            counters = {
                "rx_bytes": 1000,
                "tx_bytes": 2000,
                "rx_errors": 0,
                "tx_errors": 0,
                "rx_dropped": 5,
                "tx_dropped": 2,
            }

            for name, value in counters.items():
                (stats / name).write_text(str(value))

            result = network_metrics(root)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["name"], "eth0")
            self.assertEqual(result[0]["state"], "up")
            self.assertEqual(result[0]["rx_bytes"], 1000)
            self.assertEqual(result[0]["rx_dropped"], 5)
            self.assertEqual(result[0]["tx_dropped"], 2)

    def test_loopback_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lo").mkdir()
            result = network_metrics(root)

            self.assertEqual(result, [])

    def test_missing_network_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "nonexistent"
            result = network_metrics(root)

            self.assertEqual(result, [])

    def test_invalid_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            iface = root / "eth0"
            stats = iface / "statistics"
            stats.mkdir(parents=True)

            (iface / "operstate").write_text("down")
            (stats / "rx_errors").write_text("invalid")

            result = network_metrics(root)

            self.assertEqual(result[0]["state"], "down")
            self.assertEqual(result[0]["rx_errors"], 0)

    def test_directory_permission_failure(self):
        with patch.object(Path, 'iterdir', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                network_metrics(Path('/mock/sys/net'))

    def test_missing_and_negative_counters_report_failure(self):
        for value in (None, '-1', 'invalid'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                stats = root / 'eth0' / 'statistics'
                stats.mkdir(parents=True)
                if value is not None:
                    (stats / 'rx_bytes').write_text(value)
                with self.assertLogs('network', level='WARNING'):
                    result = network_metrics(root)
                self.assertFalse(result[0]['collection_success'])
                self.assertEqual(result[0]['state'], 'unknown')

    def test_interfaces_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'eth2').mkdir()
            (root / 'eth1').mkdir()
            with self.assertLogs('network', level='WARNING'):
                result = network_metrics(root)
            self.assertEqual([iface['name'] for iface in result], ['eth1', 'eth2'])


if __name__ == "__main__":
    unittest.main()
