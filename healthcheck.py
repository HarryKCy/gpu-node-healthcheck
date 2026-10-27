#!/usr/bin/env python3
"""Read-only Linux and optional NVIDIA GPU health check. Python stdlib only."""
import argparse
import csv
import io
import json
import logging
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from network import network_metrics

LOGGER = logging.getLogger(__name__)
GPU_TIMEOUT_SECONDS = 5
UNSUPPORTED = {'n/a', '[n/a]', '[not supported]', 'not supported'}


def mem_pct() -> float:
    values = {}
    with open('/proc/meminfo', encoding='utf8') as stream:
        for line in stream:
            key, _, value = line.partition(':')
            if key in ('MemAvailable', 'MemTotal'):
                fields = value.split()
                if not fields:
                    raise ValueError(f'Missing value for {key} in /proc/meminfo')
                values[key] = int(fields[0])
    total, available = values['MemTotal'], values['MemAvailable']
    if total <= 0 or not 0 <= available <= total:
        raise ValueError('Invalid MemTotal or MemAvailable in /proc/meminfo')
    return round(100 * (1 - available / total), 1)


def _gpu_number(value: str, maximum: float | None = None) -> float | None:
    if value.lower() in UNSUPPORTED:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or (maximum is not None and number > maximum):
        raise ValueError(f'Invalid NVIDIA numeric telemetry: {value!r}')
    return number


def gpu_metrics() -> dict:
    cmd = [
        'nvidia-smi',
        '--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total',
        '--format=csv,noheader,nounits',
    ]
    try:
        out = subprocess.run(cmd, text=True, capture_output=True,
                             timeout=GPU_TIMEOUT_SECONDS, check=False)
    except FileNotFoundError:
        LOGGER.debug('nvidia-smi is not installed; optional GPU telemetry unavailable')
        return {'state': 'not_installed', 'devices': []}
    except subprocess.TimeoutExpired:
        LOGGER.warning('nvidia-smi exceeded the %s second timeout', GPU_TIMEOUT_SECONDS)
        return {'state': 'timeout', 'devices': []}
    except (OSError, UnicodeError) as exc:
        LOGGER.warning('Unable to execute or decode nvidia-smi: %s', exc)
        return {'state': 'error', 'devices': []}
    # NVIDIA uses a nonzero exit status for several errors. Only explicit
    # no-device output is classified as absent hardware; driver errors are unknown.
    message = out.stdout.strip()
    if out.returncode:
        message = (message + '\n' + out.stderr).strip()
    if message.lower() == 'no devices were found':
        return {'state': 'no_devices', 'devices': []}
    if out.returncode:
        LOGGER.warning('nvidia-smi failed (exit %s): %s', out.returncode, message[:500])
        return {'state': 'error', 'devices': []}
    if not out.stdout.strip():
        LOGGER.warning('nvidia-smi returned empty telemetry')
        return {'state': 'empty', 'devices': []}
    devices = []
    seen = set()
    try:
        for row in csv.reader(io.StringIO(out.stdout), skipinitialspace=True, strict=True):
            if not row:
                continue
            if len(row) != 6:
                raise ValueError('Expected six NVIDIA telemetry fields')
            index, name, temp, util, used, total = [value.strip() for value in row]
            if not index.isdecimal() or index in seen or not name:
                raise ValueError('Missing or duplicate GPU identity')
            seen.add(index)
            device = {
                'index': index, 'name': name,
                'temp_c': _gpu_number(temp), 'util_pct': _gpu_number(util, 100),
                'memory_used_mib': _gpu_number(used),
                'memory_total_mib': _gpu_number(total),
            }
            used_mem, total_mem = device['memory_used_mib'], device['memory_total_mib']
            if total_mem == 0 or (used_mem is not None and total_mem is not None and used_mem > total_mem):
                raise ValueError('Inconsistent NVIDIA memory telemetry')
            devices.append(device)
    except (ValueError, csv.Error) as exc:
        LOGGER.warning('Invalid nvidia-smi telemetry: %s', exc)
        return {'state': 'parse_error', 'devices': []}
    if not devices:
        return {'state': 'empty', 'devices': []}
    # Unsupported sensors are not device failures. Keep the supported fields,
    # but disclose incomplete coverage instead of presenting it as complete.
    partial = any(dev[field] is None for dev in devices
                  for field in ('temp_c', 'util_pct', 'memory_used_mib', 'memory_total_mib'))
    return {'state': 'partial' if partial else 'ok', 'devices': devices}


def check(mem, disk, load_ratio, gpu, args):
    alerts = []
    if mem >= args.memory_critical:
        alerts.append('memory usage high')
    if disk >= args.disk_critical:
        alerts.append('disk usage high')
    if load_ratio >= args.load_critical:
        alerts.append('load per logical CPU high')
    for dev in gpu['devices']:
        if dev['temp_c'] is not None and dev['temp_c'] >= args.gpu_temp_critical:
            alerts.append('GPU ' + dev['index'] + ' temperature high')
    if args.require_gpu and (gpu['state'] != 'ok' or not gpu['devices']):
        alerts.append('required GPU telemetry missing')
    return alerts


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk-path', default='/')
    parser.add_argument('--memory-critical', type=float, default=90)
    parser.add_argument('--disk-critical', type=float, default=90)
    parser.add_argument('--load-critical', type=float, default=2,
                        help='Load average divided by logical CPU count')
    parser.add_argument('--gpu-temp-critical', type=float, default=85)
    parser.add_argument('--require-gpu', action='store_true')
    return parser


def collect_metrics(args=None) -> dict:
    """Collect a snapshot without writing to process-wide stdout or stderr."""
    if args is None:
        args = argument_parser().parse_args([])
    mem = mem_pct()
    usage = shutil.disk_usage(args.disk_path)
    if usage.total <= 0 or not 0 <= usage.used <= usage.total:
        raise ValueError(f'Invalid filesystem capacity for {args.disk_path}')
    disk = round(100 * usage.used / usage.total, 1)
    load = os.getloadavg()
    if not all(math.isfinite(value) and value >= 0 for value in load):
        raise ValueError('Invalid CPU load average')
    cpus = os.cpu_count() or 1
    gpu = gpu_metrics()
    alerts = check(mem, disk, load[0] / cpus, gpu, args)
    return {
        'utc': datetime.now(timezone.utc).isoformat(),
        'hostname': os.uname().nodename, 'status': 'CRITICAL' if alerts else 'OK',
        'memory_used_pct': mem, 'disk_used_pct': disk, 'disk_path': args.disk_path,
        'load_1m': round(load[0], 2), 'logical_cpus': cpus, 'gpu': gpu,
        'network': network_metrics(), 'alerts': alerts,
    }


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = collect_metrics(args)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 2 if result['alerts'] else 0
    except (OSError, KeyError, ValueError, ZeroDivisionError) as exc:
        print(json.dumps({'status': 'UNKNOWN', 'error': str(exc)}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    sys.exit(main())
