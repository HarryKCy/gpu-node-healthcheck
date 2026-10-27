"""Deterministic collection tests; NVIDIA and Linux measurements are mocked."""
import contextlib
import io
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import mock_open, patch

import healthcheck


class GpuReliabilityTest(unittest.TestCase):
    def run_gpu(self, stdout='', stderr='', returncode=0, error=None):
        with patch('healthcheck.subprocess.run', side_effect=error,
                   return_value=subprocess.CompletedProcess([], returncode, stdout, stderr)) as run:
            result = healthcheck.gpu_metrics()
        self.assertEqual(run.call_args.kwargs['timeout'], 5)
        self.assertFalse(run.call_args.kwargs['check'])
        self.assertNotIn('shell', run.call_args.kwargs)
        return result

    def test_multiple_devices_and_csv_names(self):
        result = self.run_gpu('0, "NVIDIA, Test", 48, 20, 1024, 8192\n1, GPU B, 51, 99, 4000, 8000\n')
        self.assertEqual(result['state'], 'ok')
        self.assertEqual(len(result['devices']), 2)
        self.assertEqual(result['devices'][0]['name'], 'NVIDIA, Test')
        self.assertEqual(result['devices'][1]['memory_used_mib'], 4000)

    def test_missing_executable(self):
        self.assertEqual(self.run_gpu(error=FileNotFoundError())['state'], 'not_installed')

    def test_timeout(self):
        self.assertEqual(self.run_gpu(error=subprocess.TimeoutExpired('nvidia-smi', 5))['state'], 'timeout')

    def test_command_failure(self):
        result = self.run_gpu(stderr='Unable to communicate with NVIDIA driver', returncode=9)
        self.assertEqual(result, {'state': 'error', 'devices': []})

    def test_permission_error(self):
        self.assertEqual(self.run_gpu(error=PermissionError('denied'))['state'], 'error')

    def test_decode_error(self):
        self.assertEqual(self.run_gpu(error=UnicodeError('invalid output'))['state'], 'error')

    def test_no_devices(self):
        for code in (0, 6):
            with self.subTest(returncode=code):
                self.assertEqual(self.run_gpu(stdout='No devices were found\n', returncode=code),
                                 {'state': 'no_devices', 'devices': []})

    def test_empty_telemetry_is_not_success(self):
        for value in ('', '\n  \n'):
            with self.subTest(output=value):
                self.assertEqual(self.run_gpu(stdout=value)['state'], 'empty')

    def test_malformed_rows(self):
        for value in ('0, GPU, 40', 'x, GPU, 40, 20, 0, 8000',
                      '0, , 40, 20, 0, 8000', '0, GPU, broken, 20, 0, 8000',
                      '0, GPU, 40, 20, 0, 8000\n0, GPU, 40, 20, 0, 8000',
                      '0, "unterminated, 40, 20, 0, 8000'):
            with self.subTest(output=value):
                self.assertEqual(self.run_gpu(stdout=value), {'state': 'parse_error', 'devices': []})

    def test_invalid_numeric_values(self):
        for fields in ('NaN, 20, 0, 8000', '40, inf, 0, 8000',
                       '40, -1, 0, 8000', '40, 101, 0, 8000',
                       '40, 20, 9000, 8000', '40, 20, 0, 0', '40, , 0, 8000'):
            with self.subTest(fields=fields):
                self.assertEqual(self.run_gpu(stdout='0, GPU, '+fields)['state'], 'parse_error')

    def test_unsupported_sensors_preserve_supported_values(self):
        result = self.run_gpu('0, GPU, [Not Supported], N/A, 1024, 8192')
        self.assertEqual(result['state'], 'partial')
        self.assertIsNone(result['devices'][0]['temp_c'])
        self.assertEqual(result['devices'][0]['memory_used_mib'], 1024)

    def test_required_gpu_rejects_partial_and_empty(self):
        args = healthcheck.argument_parser().parse_args(['--require-gpu'])
        for state in ('partial', 'empty', 'error', 'no_devices', 'not_installed'):
            with self.subTest(state=state):
                self.assertIn('required GPU telemetry missing',
                              healthcheck.check(0, 0, 0, {'state': state, 'devices': []}, args))


class LinuxReliabilityTest(unittest.TestCase):
    def setUp(self):
        patches = {
            'mem_pct': {'return_value': 25.0},
            'shutil.disk_usage': {'return_value': SimpleNamespace(total=1000, used=200)},
            'os.getloadavg': {'return_value': (4.0, 3.0, 2.0)},
            'os.cpu_count': {'return_value': 8},
            'os.uname': {'return_value': SimpleNamespace(nodename='test-node')},
            'gpu_metrics': {'return_value': {'state': 'not_installed', 'devices': []}},
            'network_metrics': {'return_value': []},
        }
        self.mocks = {}
        for name, kwargs in patches.items():
            patcher = patch('healthcheck.' + name, **kwargs)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def test_cpu_and_disk_snapshot(self):
        result = healthcheck.collect_metrics()
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['load_1m'], 4)
        self.assertEqual(result['logical_cpus'], 8)
        self.assertEqual(result['disk_used_pct'], 20)
        self.assertEqual(result['memory_used_pct'], 25)

    def test_cpu_count_unavailable(self):
        self.mocks['os.cpu_count'].return_value = None
        result = healthcheck.collect_metrics()
        self.assertEqual(result['logical_cpus'], 1)
        self.assertIn('load per logical CPU high', result['alerts'])

    def test_cpu_failure(self):
        self.mocks['os.getloadavg'].side_effect = OSError('load unavailable')
        with self.assertRaisesRegex(OSError, 'load unavailable'):
            healthcheck.collect_metrics()

    def test_cpu_invalid_load(self):
        for load in ((float('nan'), 0, 0), (-1, 0, 0)):
            self.mocks['os.getloadavg'].return_value = load
            with self.assertRaises(ValueError):
                healthcheck.collect_metrics()

    def test_disk_failure_and_invalid_capacity(self):
        self.mocks['shutil.disk_usage'].side_effect = PermissionError('denied')
        with self.assertRaises(PermissionError):
            healthcheck.collect_metrics()
        self.mocks['shutil.disk_usage'].side_effect = None
        for total, used in ((0, 0), (100, 101), (100, -1)):
            self.mocks['shutil.disk_usage'].return_value = SimpleNamespace(total=total, used=used)
            with self.assertRaises(ValueError):
                healthcheck.collect_metrics()

    def test_custom_disk_path(self):
        healthcheck.collect_metrics(healthcheck.argument_parser().parse_args(['--disk-path', '/data']))
        self.mocks['shutil.disk_usage'].assert_called_once_with('/data')

    def test_cli_success_and_critical(self):
        for mem, expected in ((25, 0), (95, 2)):
            self.mocks['mem_pct'].return_value = mem
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(healthcheck.main([]), expected)
            self.assertEqual(json.loads(output.getvalue())['memory_used_pct'], mem)

    def test_cli_unknown(self):
        self.mocks['mem_pct'].side_effect = OSError('meminfo unavailable')
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(healthcheck.main([]), 3)
        self.assertEqual(json.loads(output.getvalue())['status'], 'UNKNOWN')


class MemoryReliabilityTest(unittest.TestCase):
    def test_available_memory(self):
        with patch('builtins.open', mock_open(read_data='MemTotal: 1000 kB\nMemAvailable: 750 kB\nOther: ignored\n')):
            self.assertEqual(healthcheck.mem_pct(), 25)

    def test_invalid_memory(self):
        for content in ('MemTotal: 0\nMemAvailable: 0', 'MemTotal: 100\nMemAvailable: 101',
                        'MemTotal: 100\nMemAvailable: -1', 'MemTotal: bad\nMemAvailable: 1',
                        'MemTotal: 100\n', 'MemTotal: \nMemAvailable: 10'):
            with self.subTest(content=content), patch('builtins.open', mock_open(read_data=content)):
                with self.assertRaises((ValueError, KeyError)):
                    healthcheck.mem_pct()

    def test_unreadable_meminfo(self):
        with patch('builtins.open', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                healthcheck.mem_pct()
