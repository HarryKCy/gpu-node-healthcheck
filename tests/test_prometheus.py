"""Automated tests for Prometheus metrics formatting."""

import unittest

from prometheus import escape_label, format_metrics, metric


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

    def test_label_escaping(self):
        self.assertEqual(escape_label('GPU"\\\n'), 'GPU\\"\\\\\\n')

    def test_optional_gpu_fields_are_omitted(self):
        self.result['gpu']['devices'][0]['temp_c'] = None
        self.result['gpu']['state'] = 'partial'
        output = format_metrics(self.result)
        self.assertNotIn('gpu_node_gpu_temperature_celsius', output)
        self.assertIn('gpu_node_gpu_memory_used_mib{gpu="0",name="NVIDIA Test GPU"} 1024.0', output)
        self.assertIn('gpu_node_gpu_collection_info{state="partial"} 1', output)
        self.assertIn('gpu_node_gpu_collection_success 0', output)
        self.assertIn('gpu_node_gpu_devices 1', output)

    def test_absent_gpu_and_unknown_presence_are_distinct(self):
        for state in ('not_installed', 'timeout', 'error', 'parse_error', 'empty', 'no_devices'):
            with self.subTest(state=state):
                self.result['gpu'] = {'state': state, 'devices': []}
                output = format_metrics(self.result)
                self.assertNotIn('gpu_node_gpu_temperature_celsius', output)
                if state == 'no_devices':
                    self.assertIn('gpu_node_gpu_devices 0', output)
                else:
                    self.assertNotIn('gpu_node_gpu_devices', output)

    def test_invalid_network_counters_are_not_exported_as_zero(self):
        self.result['network'][0]['collection_success'] = False
        output = format_metrics(self.result)
        self.assertIn('gpu_node_network_collection_success{interface="eth0"} 0', output)
        self.assertNotIn('gpu_node_network_rx_bytes_total{interface="eth0"}', output)
        self.assertIn('gpu_node_network_rx_bytes_total{interface="eth1"} 3000', output)

    def test_unknown_health_status(self):
        self.result['status'] = 'UNKNOWN'
        self.assertIn('gpu_node_health_status 3', format_metrics(self.result))

    def test_invalid_metric_value(self):
        for value in (float('nan'), float('inf'), 'not numeric'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metric('test', value, 'Test gauge')

    def test_multi_gpu_metadata_once(self):
        self.result['gpu']['devices'].append({**self.result['gpu']['devices'][0], 'index': '1'})
        output = format_metrics(self.result)
        self.assertEqual(output.count('# TYPE gpu_node_gpu_temperature_celsius gauge'), 1)
        self.assertIn('gpu_node_gpu_temperature_celsius{gpu="1",name="NVIDIA Test GPU"} 50.0', output)


if __name__ == "__main__":
    unittest.main()
