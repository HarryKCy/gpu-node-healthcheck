#!/usr/bin/env python3
"""Read-only Linux and optional NVIDIA GPU health check. Python stdlib only."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from network import network_metrics
from datetime import datetime, timezone


def mem_pct():
    values = {}
    with open('/proc/meminfo', encoding='utf8') as f:
        for line in f:
            key, _, value = line.partition(':')
            if value:
                values[key] = int(value.strip().split()[0])
    return round(100 * (1 - values['MemAvailable'] / values['MemTotal']), 1)


def gpu_metrics():
    cmd = ['nvidia-smi', '--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits']
    try:
        out = subprocess.run(cmd, text=True, capture_output=True, timeout=5)
    except FileNotFoundError:
        return {'state': 'not_installed', 'devices': []}
    except subprocess.TimeoutExpired:
        return {'state': 'timeout', 'devices': []}
    if out.returncode:
        return {'state': 'error', 'devices': []}
    devices = []
    for line in out.stdout.splitlines():
        parts = [v.strip() for v in line.split(',')]
        if len(parts) != 6:
            return {'state': 'parse_error', 'devices': []}
        index, name, temp, util, used, total = parts
        def num(x):
            try: return float(x)
            except ValueError: return None
        devices.append({'index': index, 'name': name, 'temp_c': num(temp), 'util_pct': num(util), 'memory_used_mib': num(used), 'memory_total_mib': num(total)})
    return {'state': 'ok', 'devices': devices}


def check(mem, disk, load_ratio, gpu, args):
    alerts = []
    if mem >= args.memory_critical: alerts.append('memory usage high')
    if disk >= args.disk_critical: alerts.append('disk usage high')
    if load_ratio >= args.load_critical: alerts.append('load per logical CPU high')
    for dev in gpu['devices']:
        if dev['temp_c'] is not None and dev['temp_c'] >= args.gpu_temp_critical:
            alerts.append('GPU ' + dev['index'] + ' temperature high')
    if args.require_gpu and (gpu['state'] != 'ok' or not gpu['devices']):
        alerts.append('required GPU telemetry missing')
    return alerts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--disk-path', default='/')
    p.add_argument('--memory-critical', type=float, default=90)
    p.add_argument('--disk-critical', type=float, default=90)
    p.add_argument('--load-critical', type=float, default=2, help='Load average divided by logical CPU count')
    p.add_argument('--gpu-temp-critical', type=float, default=85)
    p.add_argument('--require-gpu', action='store_true')
    args = p.parse_args(argv)
    try:
        mem = mem_pct()
        usage = shutil.disk_usage(args.disk_path)
        disk = round(100 * usage.used / usage.total, 1)
        load = os.getloadavg()
        cpus = os.cpu_count() or 1
        gpu = gpu_metrics()
        alerts = check(mem, disk, load[0] / cpus, gpu, args)
        result = {'utc': datetime.now(timezone.utc).isoformat(), 'hostname': os.uname().nodename, 'status': 'CRITICAL' if alerts else 'OK', 'memory_used_pct': mem, 'disk_used_pct': disk, 'disk_path': args.disk_path, 'load_1m': round(load[0], 2), 'logical_cpus': cpus, 'gpu': gpu, 'network': network_metrics(), 'alerts': alerts}
        print(json.dumps(result, indent=2))
        return 2 if alerts else 0
    except (OSError, KeyError, ValueError, ZeroDivisionError) as e:
        print(json.dumps({'status': 'UNKNOWN', 'error': str(e)}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
