#!/usr/bin/env python3
"""Read-only Linux and optional NVIDIA GPU health check. Python stdlib only."""
import argparse
import csv
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
    seen, ambiguous = set(), set()
    rejected = False
    # NVIDIA emits one device per line. Reject malformed rows independently;
    # even an invalid duplicate row makes that index ambiguous.
    for line in out.stdout.split('\n'):
        if not line.strip():
            continue
        try:
            row = next(csv.reader([line], skipinitialspace=True, strict=True))
        except csv.Error:
            row = []
        raw_index = row[0].strip() if row else line.split(',', 1)[0].strip()
        index = str(int(raw_index)) if raw_index.isascii() and raw_index.isdecimal() else None
        if index is not None:
            if index in seen:
                ambiguous.add(index)
            seen.add(index)
        try:
            if len(row) != 6:
                raise ValueError('Expected six NVIDIA telemetry fields')
            _, name, temp, util, used, total = [value.strip() for value in row]
            if index is None or index in ambiguous or not name:
                raise ValueError('Missing or duplicate GPU identity')
            used_mem, total_mem = _gpu_number(used), _gpu_number(total)
            device = {
                'index': index, 'name': name,
                'temp_c': _gpu_number(temp), 'util_pct': _gpu_number(util, 100),
                'memory_used_mib': used_mem,
                'memory_total_mib': total_mem,
            }
            if total_mem == 0 or (used_mem is not None and total_mem is not None and used_mem > total_mem):
                raise ValueError('Inconsistent NVIDIA memory telemetry')
            devices.append(device)
        except (ValueError, csv.Error) as exc:
            rejected = True
            LOGGER.warning('Invalid nvidia-smi telemetry: %s', exc)
    devices = [device for device in devices if device['index'] not in ambiguous]
    if rejected:
        # parse_error may retain valid rows, but never represents a full count.
        return {'state': 'parse_error', 'devices': devices}
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


def threshold(value, maximum=None):
    """Finite, nonnegative policy threshold; percentages additionally cap at 100.

    Temperature policy starts at 0 C, matching the supported sensor domain;
    there is no universal hardware maximum.
    """
    number = float(value)
    if not math.isfinite(number) or number < 0 or (maximum is not None and number > maximum):
        domain = '0 to 100 inclusive' if maximum is not None else 'nonnegative'
        raise ValueError(f'threshold must be finite and {domain}')
    return number


def percentage_threshold(value):
    return threshold(value, 100)


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk-path', default='/')
    parser.add_argument('--memory-critical', type=percentage_threshold, default=90)
    parser.add_argument('--disk-critical', type=percentage_threshold, default=90)
    parser.add_argument('--load-critical', type=threshold, default=2,
                        help='Load average divided by logical CPU count')
    parser.add_argument('--gpu-temp-critical', type=threshold, default=85,
                        help='Finite temperature threshold in Celsius, at least 0')
    parser.add_argument('--require-gpu', action='store_true')
    return parser


def collect_metrics(args=None) -> dict:
    """Collect a snapshot without writing to process-wide stdout or stderr."""
    if args is None:
        args = argument_parser().parse_args([])
    for field in ('memory_critical', 'disk_critical', 'load_critical', 'gpu_temp_critical'):
        maximum = 100 if field in ('memory_critical', 'disk_critical') else None
        try:
            value = getattr(args, field)
            if type(value) not in (int, float):
                raise ValueError('threshold must be numeric')
            threshold(value, maximum)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Invalid {field}: {exc}') from exc
    mem = mem_pct()
    usage = shutil.disk_usage(args.disk_path)
    if usage.total <= 0 or not 0 <= usage.used <= usage.total:
        raise ValueError(f'Invalid filesystem capacity for {args.disk_path}')
    disk = round(100 * usage.used / usage.total, 1)
    load = os.getloadavg()
    if not all(math.isfinite(value) and value >= 0 for value in load):
        raise ValueError('Invalid CPU load average')
    cpus = os.cpu_count()
    if type(cpus) is not int or cpus <= 0:
        raise ValueError('Logical CPU count unavailable or invalid')
    gpu = gpu_metrics()
    alerts = check(mem, disk, load[0] / cpus, gpu, args)
    # Optional absence and unsupported sensors are allowed; query failures are not.
    status = 'OK' if gpu['state'] in ('ok', 'partial', 'not_installed', 'no_devices') else 'UNKNOWN'
    if alerts:
        status = 'CRITICAL'
    return {
        'utc': datetime.now(timezone.utc).isoformat(),
        'hostname': os.uname().nodename, 'status': status,
        'memory_used_pct': mem, 'disk_used_pct': disk, 'disk_path': args.disk_path,
        'load_1m': round(load[0], 2), 'logical_cpus': cpus, 'gpu': gpu,
        'network': network_metrics(), 'alerts': alerts,
    }


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        result = collect_metrics(args)
        print(json.dumps(result, indent=2, allow_nan=False))
        return {'OK': 0, 'CRITICAL': 2, 'UNKNOWN': 3}[result['status']]
    except (OSError, KeyError, ValueError, ZeroDivisionError) as exc:
        print(json.dumps({'status': 'UNKNOWN', 'error': str(exc)}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    sys.exit(main())
