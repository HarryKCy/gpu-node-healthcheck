"""Additional direct-call, identity and bounded production-server checks."""
import socket
import threading
import unittest
from unittest.mock import patch

import exporter
import healthcheck
from prometheus import format_metrics, metric
from test_exporter import SNAPSHOT
from test_review_regressions import healthy_linux, gpu_output


class EvidenceBoundaries(unittest.TestCase):
    def test_direct_thresholds_rejected_before_collection(self):
        for field in ('memory_critical', 'disk_critical', 'load_critical', 'gpu_temp_critical'):
            for value in (float('nan'), float('inf'), -1):
                args = healthcheck.argument_parser().parse_args([])
                setattr(args, field, value)
                with patch('healthcheck.mem_pct') as mem, patch('healthcheck.subprocess.run') as run:
                    with self.assertRaises(ValueError):
                        healthcheck.collect_metrics(args)
                    mem.assert_not_called()
                    run.assert_not_called()

    def test_threshold_boundaries(self):
        for value in ('0', '100'):
            self.assertEqual(healthcheck.percentage_threshold(value), float(value))
        self.assertEqual(healthcheck.threshold('1000'), 1000)

    def test_failed_states_status_exit_and_metric(self):
        for state in ('timeout', 'error', 'empty', 'parse_error'):
            for critical in (False, True):
                with healthy_linux(), patch('healthcheck.gpu_metrics', return_value={'state': state, 'devices': []}), patch('healthcheck.mem_pct', return_value=95 if critical else 25):
                    result = healthcheck.collect_metrics()
                self.assertEqual(result['status'], 'CRITICAL' if critical else 'UNKNOWN')
                self.assertIn(f"gpu_node_health_status {2 if critical else 3}\n", format_metrics(result))

    def test_duplicate_invalid_row_revokes_identity(self):
        for duplicate in ('0, bad', '00, GPU, 40, 20, 1, 8', '"0", GPU, 40, 20, 1, 8', '0, "unterminated'):
            with gpu_output('0, GPU, 95, 20, 1, 8\n' + duplicate):
                result = healthcheck.gpu_metrics()
            self.assertEqual(result, {'state': 'parse_error', 'devices': []})

    def test_partial_enumeration_has_no_count(self):
        with healthy_linux(), gpu_output('0, GPU, 95, 20, 1, 8\n1, bad'):
            result = healthcheck.collect_metrics()
        text = format_metrics(result)
        self.assertNotIn('gpu_node_gpu_devices', text)
        self.assertIn('gpu_node_gpu_temperature_celsius{gpu="0",name="GPU"} 95', text)

    def test_boolean_and_nonfinite_samples(self):
        self.assertTrue(metric('test', True, 'test').endswith('test 1\n'))
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ValueError):
                metric('test', value, 'test')


class ResourceBoundaries(unittest.TestCase):
    def test_idle_incomplete_overload_and_cleanup(self):
        entered = threading.Event()
        class Observe(exporter.MetricsHandler):
            def setup(self):
                super().setup()
                entered.set()
        server = exporter.MetricsServer(('127.0.0.1', 0), Observe, max_handlers=1, io_timeout=0.2)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
        thread.start()
        try:
            for request in (b'', b'GET /metrics HTTP/1.0\r\nHost:'):
                entered.clear()
                with socket.create_connection(server.server_address, timeout=2) as first:
                    if request:
                        first.sendall(request)
                    self.assertTrue(entered.wait(2))
                    with socket.create_connection(server.server_address, timeout=2) as excess:
                        self.assertEqual(excess.recv(1), b'')
                    self.assertEqual(first.recv(1), b'')
                # Acquiring the slot waits for handler cleanup, not an arbitrary sleep.
                self.assertTrue(server.handler_slots.acquire(timeout=2))
                server.handler_slots.release()
            with patch('exporter.collect_metrics', return_value=SNAPSHOT):
                with socket.create_connection(server.server_address, timeout=2) as client:
                    client.sendall(b'GET /metrics HTTP/1.0\r\n\r\n')
                    self.assertIn(b'200 OK', client.recv(4096))
            self.assertTrue(server.handler_slots.acquire(timeout=2))
            server.handler_slots.release()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_disconnect_releases_collection_and_handler(self):
        started, release = threading.Event(), threading.Event()
        def collect():
            started.set()
            if not release.wait(2):
                raise RuntimeError('synchronization timeout')
            return SNAPSHOT
        server = exporter.MetricsServer(('127.0.0.1', 0), max_handlers=1)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
        thread.start()
        try:
            with patch('exporter.collect_metrics', side_effect=collect):
                with socket.create_connection(server.server_address, timeout=2) as client:
                    client.sendall(b'GET /metrics HTTP/1.0\r\n\r\n')
                    self.assertTrue(started.wait(2))
                release.set()
                self.assertTrue(server.handler_slots.acquire(timeout=2))
                server.handler_slots.release()
                self.assertTrue(exporter.COLLECTION_SLOT.acquire(timeout=2))
                exporter.COLLECTION_SLOT.release()
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)

class PromqlGeneration(unittest.TestCase):
    def test_cases_use_actual_queries_and_all_controls(self):
        import json
        from pathlib import Path
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'cases.json'
            subprocess.run([sys.executable, 'tools/make_promql_cases.py',
                            'dashboards/gpu-node-overview.json', str(output)],
                           check=True, capture_output=True)
            cases = json.loads(output.read_text())['tests']
        self.assertEqual(len(cases), 7)
        self.assertEqual(sum(len(case['promql_expr_test']) for case in cases), 42)
        for case in cases:
            for assertion in case['promql_expr_test']:
                self.assertIn('and on (job, instance, interface)', assertion['expr'])
                self.assertIn('and on (job, instance)', assertion['expr'])
                self.assertNotIn('$', assertion['expr'])
