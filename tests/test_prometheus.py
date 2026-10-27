"""Automated tests for Prometheus metrics formatting."""

import unittest
from collections import Counter

from prometheus import format_metrics


class PrometheusMetricsTest(unittest.TestCase):

    def setUp(self):
        self.result = {
            "status": "OK",
            "memory_used_pct": 32.5,
            "disk_used_pct": 11.8,
            "load_1m": 1.3,
            "logical_cpus": 14,
            "network": [
                {
                    "name": "eth0",
                    "rx_bytes": 1000,
                    "tx_bytes": 2000,
                    "rx_errors": 0,
                    "tx_errors": 0,
                    "rx_dropped": 5,
                    "tx_dropped": 2,
                },
                {
                    "name": "eth1",
                    "rx_bytes": 3000,
                    "tx_bytes": 4000,
                    "rx_errors": 0,
                    "tx_errors": 0,
                    "rx_dropped": 0,
                    "tx_dropped": 0,
                },
            ],
            "gpu": {
                "state": "ok",
                "devices": [
                    {
                        "index": "0",
                        "name": "NVIDIA Test GPU",
                        "temp_c": 50.0,
                        "util_pct": 25.0,
                        "memory_used_mib": 1024.0,
                        "memory_total_mib": 8192.0,
                    }
                ],
            },
        }

    def test_help_type_match(self):
        metrics = format_metrics(self.result)

        help_names = [
            line.split()[2]
            for line in metrics.splitlines()
            if line.startswith("# HELP ")
        ]

        type_names = [
            line.split()[2]
            for line in metrics.splitlines()
            if line.startswith("# TYPE ")
        ]

        self.assertTrue(help_names)
        self.assertEqual(
            set(help_names),
            set(type_names)
        )

    def test_no_duplicate_metadata(self):
        metrics = format_metrics(self.result)

        help_names = [
            line.split()[2]
            for line in metrics.splitlines()
            if line.startswith("# HELP ")
        ]

        type_names = [
            line.split()[2]
            for line in metrics.splitlines()
            if line.startswith("# TYPE ")
        ]

        self.assertEqual(
            len(help_names),
            len(set(help_names))
        )

        self.assertEqual(
            len(type_names),
            len(set(type_names))
        )

    def test_network_interfaces(self):
        metrics = format_metrics(self.result)

        self.assertIn(
            'gpu_node_network_rx_bytes_total{interface="eth0"} 1000',
            metrics
        )

        self.assertIn(
            'gpu_node_network_rx_bytes_total{interface="eth1"} 3000',
            metrics
        )

    def test_gpu_metrics(self):
        metrics = format_metrics(self.result)

        self.assertIn(
            'gpu_node_gpu_temperature_celsius',
            metrics
        )

        self.assertIn(
            'gpu_node_gpu_utilization_percent',
            metrics
        )


if __name__ == "__main__":
    unittest.main()
