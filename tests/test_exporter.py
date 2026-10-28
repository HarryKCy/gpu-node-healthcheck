"""Exercise the real HTTP handler on loopback with mocked collection."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import threading
import unittest
from unittest.mock import patch

import exporter


SNAPSHOT = {
    'status': 'OK', 'memory_used_pct': 20, 'disk_used_pct': 30,
    'load_1m': 0.5, 'logical_cpus': 4, 'network': [],
    'gpu': {'state': 'not_installed', 'devices': []},
}


class ExporterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = exporter.MetricsServer(('127.0.0.1', 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={'poll_interval': 0.01})
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path='/metrics'):
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def test_success(self):
        with patch('exporter.collect_metrics', return_value=SNAPSHOT):
            code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'text/plain; version=0.0.4; charset=utf-8')
        self.assertEqual(int(headers['Content-Length']), len(body.encode()))
        self.assertIn('gpu_node_memory_used_percent 20\n', body)

    def test_critical_is_successful_scrape(self):
        with patch('exporter.collect_metrics', return_value={**SNAPSHOT, 'status': 'CRITICAL'}):
            code, _, body = self.request()
        self.assertEqual(code, 200)
        self.assertIn('gpu_node_health_status 2\n', body)

    def test_unknown_path_does_not_collect(self):
        with patch('exporter.collect_metrics') as collect:
            self.assertEqual(self.request('/')[0], 404)
        collect.assert_not_called()

    def test_failure_returns_503_and_recovers(self):
        with patch('exporter.collect_metrics', side_effect=OSError('cannot read proc')):
            with self.assertLogs('exporter', level='ERROR'):
                self.assertEqual(self.request()[0], 503)
        with patch('exporter.collect_metrics', return_value=SNAPSHOT):
            self.assertEqual(self.request()[0], 200)

    def test_invalid_snapshot(self):
        for snapshot in ({}, {**SNAPSHOT, 'load_1m': float('nan')}):
            with patch('exporter.collect_metrics', return_value=snapshot):
                with self.assertLogs('exporter', level='ERROR'):
                    self.assertEqual(self.request()[0], 503)

    def test_overlapping_scrapes_are_bounded(self):
        started, release = threading.Event(), threading.Event()

        def collect():
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError('test synchronization timeout')
            return SNAPSHOT

        with patch('exporter.collect_metrics', side_effect=collect) as collector:
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(self.request)
                try:
                    self.assertTrue(started.wait(timeout=5))
                    self.assertEqual(self.request()[0], 503)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=5)[0], 200)
            self.assertEqual(collector.call_count, 1)
