"""Synthetic regressions for threshold, evidence, exposition and log safety."""
import contextlib
import io
import json
import logging
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import exporter
import healthcheck
import network
from prometheus import escape_label, format_metrics


@contextlib.contextmanager
def healthy_linux():
    with contextlib.ExitStack() as stack:
        values = {
            'mem_pct': 25.0,
            'shutil.disk_usage': SimpleNamespace(total=1000, used=200),
            'os.getloadavg': (0.5, 0.4, 0.3),
            'os.cpu_count': 4,
            'os.uname': SimpleNamespace(nodename='synthetic-review-node'),
            'network_metrics': [],
        }
        for key, value in values.items():
            stack.enter_context(patch('healthcheck.' + key, return_value=value))
        yield


def gpu_output(text):
    return patch('healthcheck.subprocess.run', return_value=
                 subprocess.CompletedProcess(['nvidia-smi'], 0, text, ''))


class ThresholdRegression(unittest.TestCase):
    """Thresholds must be finite; percentages must be in the declared domain."""
    pass


def threshold_case(option, value):
    def test(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                healthcheck.argument_parser().parse_args([f'{option}={value}'])
        self.assertNotEqual(error.exception.code, 0)
    return test


for option in ('--memory-critical', '--disk-critical', '--load-critical', '--gpu-temp-critical'):
    for name, value in [('nan', 'nan'), ('positive_infinity', 'inf'), ('negative_infinity', '-inf')]:
        setattr(ThresholdRegression, 'test_' + option[2:].replace('-', '_') + '_' + name,
                threshold_case(option, value))
for name, option, value in [
    ('negative_memory', '--memory-critical', '-1'),
    ('memory_over_100', '--memory-critical', '101'),
    ('negative_disk', '--disk-critical', '-1'),
    ('disk_over_100', '--disk-critical', '101'),
    ('negative_load', '--load-critical', '-1'),
]:
    setattr(ThresholdRegression, 'test_' + name, threshold_case(option, value))


class MixedGpuRegression(unittest.TestCase):
    hot = '0, GPU A, 95, 20, 1024, 8192\n'
    malformed = '1, GPU B, broken, 20, 1024, 8192\n'

    def assert_hot_not_lost(self, text):
        with healthy_linux(), gpu_output(text):
            result = healthcheck.collect_metrics()
        self.assertEqual(result['status'], 'CRITICAL',
                         'A distinct valid hot GPU must not disappear because another row is malformed')
        self.assertTrue(any('GPU 0' in a and 'temperature' in a for a in result['alerts']))
        self.assertNotEqual(result['gpu']['state'], 'ok',
                            'Collection must still disclose incomplete/invalid telemetry')

    def test_hot_gpu_before_bad_row(self):
        self.assert_hot_not_lost(self.hot + self.malformed)

    def test_hot_gpu_after_bad_row(self):
        self.assert_hot_not_lost(self.malformed + self.hot)

    def test_invalid_gpu_telemetry_not_overall_ok(self):
        with healthy_linux(), gpu_output('0, GPU A, 95, 999, 1024, 8192\n'):
            result = healthcheck.collect_metrics()
        self.assertNotEqual(result['status'], 'OK',
                            'Invalid attempted telemetry is not the same as legitimately absent optional hardware')

    def test_invalid_gpu_cli_status_and_exit_are_consistent(self):
        with healthy_linux(), gpu_output('0, GPU A, 95, 999, 1024, 8192\n'):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                code = healthcheck.main([])
        result = json.loads(output.getvalue())
        self.assertNotEqual(result['status'], 'OK')
        self.assertEqual(code, {'CRITICAL': 2, 'UNKNOWN': 3}[result['status']])

    def test_optional_tool_absence_still_allows_healthy_linux(self):
        with healthy_linux(), patch('healthcheck.gpu_metrics', return_value={'state': 'not_installed', 'devices': []}):
            self.assertEqual(healthcheck.collect_metrics()['status'], 'OK')

    def test_hot_gpu_and_unsupported_other_sensor_remains_critical(self):
        with healthy_linux(), gpu_output(self.hot + '1, GPU B, N/A, 20, 1024, 8192\n'):
            result = healthcheck.collect_metrics()
        self.assertEqual(result['status'], 'CRITICAL')
        self.assertEqual(result['gpu']['state'], 'partial')


class MissingNetworkRegression(unittest.TestCase):
    # Narrow proposed contract: propagate missing sysfs like existing PermissionError.
    # A deliberately redesigned explicit unavailable status is also acceptable, but
    # must retain equivalent end-to-end coverage assertions rather than return [].
    def test_missing_sysfs_is_not_empty_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                network.network_metrics(Path(directory) / 'missing')

    def test_missing_sysfs_does_not_yield_healthy_cli(self):
        with healthy_linux(), patch('healthcheck.gpu_metrics', return_value={'state': 'not_installed', 'devices': []}), \
                patch('healthcheck.network_metrics', side_effect=lambda: network.network_metrics(Path('/sys-review-not-present'))):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                code = healthcheck.main([])
        self.assertEqual(code, 3)
        self.assertNotIn('"status": "OK"', output.getvalue())

    def test_real_empty_interface_set_remains_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'lo').mkdir()
            self.assertEqual(network.network_metrics(Path(directory)), [])


class UnknownCpuCountRegression(unittest.TestCase):
    def test_unknown_cpu_count_is_not_invented_as_one(self):
        with healthy_linux(), patch('healthcheck.os.cpu_count', return_value=None), \
                patch('healthcheck.os.getloadavg', return_value=(4.0, 3.0, 2.0)), \
                patch('healthcheck.gpu_metrics', return_value={'state': 'not_installed', 'devices': []}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                code = healthcheck.main([])
        self.assertEqual(code, 3, 'Unknown CPU capacity must not manufacture a per-CPU health finding')
        self.assertNotIn('"logical_cpus": 1', output.getvalue())


class MetricLabelRegression(unittest.TestCase):
    """Never rewrite a valid UTF-8 label separator into an unescaped line feed."""
    def check_separator(self, separator):
        name = 'Synthetic' + separator + 'GPU'
        result = {
            'status': 'OK', 'memory_used_pct': 20, 'disk_used_pct': 30,
            'load_1m': 0.5, 'logical_cpus': 4, 'network': [],
            'gpu': {'state': 'ok', 'devices': [
                {'index': '0', 'name': name, 'temp_c': 40, 'util_pct': 20,
                 'memory_used_mib': 100, 'memory_total_mib': 1000}]},
        }
        text = format_metrics(result)
        expected = 'gpu_node_gpu_temperature_celsius{gpu="0",name="' + escape_label(name) + '"} 40'
        self.assertIn(expected, text.split('\n'),
                      'Sample was split at a character other than the exposition line separator')

    def test_samples_for_each_metric_family_are_contiguous(self):
        device = {'index': '0', 'name': 'Synthetic', 'temp_c': 40,
                  'util_pct': 20, 'memory_used_mib': 100, 'memory_total_mib': 1000}
        result = {'status': 'OK', 'memory_used_pct': 20, 'disk_used_pct': 30,
                  'load_1m': 0.5, 'logical_cpus': 4, 'network': [],
                  'gpu': {'state': 'ok', 'devices': [device, {**device, 'index': '1'}]}}
        closed, last = set(), None
        for line in format_metrics(result).split('\n'):
            if not line or line.startswith('#'):
                continue
            name = line.split('{', 1)[0].split(' ', 1)[0]
            if name != last:
                if last is not None:
                    closed.add(last)
                self.assertNotIn(name, closed, 'Metric family is split into multiple groups')
                last = name

    def test_unicode_line_separator(self): self.check_separator('\u2028')
    def test_unicode_paragraph_separator(self): self.check_separator('\u2029')
    def test_next_line_character(self): self.check_separator('\u0085')


class LogSafetyRegression(unittest.TestCase):
    def test_raw_request_controls_not_written_to_logs(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = exporter.LOGGER
        old_level, old_propagate = logger.level, logger.propagate
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        server = exporter.MetricsServer(('127.0.0.1', 0))
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as connection:
                connection.sendall(b'GET /\x1b[31mREVIEW HTTP/1.0\r\nHost: localhost\r\n\r\n')
                while connection.recv(4096):
                    pass
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            logger.removeHandler(handler)
            logger.setLevel(old_level)
            logger.propagate = old_propagate
        self.assertNotIn('\x1b', stream.getvalue(), 'Raw terminal escape from request path leaked to logs')


if __name__ == '__main__':
    unittest.main()
