#!/usr/bin/env python3
"""Generate native promtool cases from dashboard expressions; stdlib only."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dashboard', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    dashboard = json.loads(args.dashboard.read_text(encoding='utf-8'))
    queries = []
    for panel in dashboard['panels']:
        if panel['id'] in (4, 5):
            for target in panel.get('targets', []):
                expr = target['expr'].replace('$__rate_interval', '1m').replace('$instance', '.*')
                if '$' in expr:
                    raise SystemExit('Unsubstituted Grafana variable; review query before running')
                queries.append(expr)
    if len(queries) != 6:
        raise SystemExit('Expected six network queries; review generator if layout changed')
    labels = '{job="gpu-node-healthcheck",instance="synthetic-node:9105",interface="eth0"}'
    metrics = [f'gpu_node_network_{direction}_{field}_total'
               for field in ('bytes', 'errors', 'dropped') for direction in ('rx', 'tx')]
    tests = []
    for scenario in ('counter_collection_failed', 'exporter_scrape_failed', 'healthy_control'):
        healthy = scenario == 'healthy_control'
        counter = '150 300 450 600' if healthy else '150 300 450 stale'
        series = [{'series': metric + labels, 'values': counter} for metric in metrics]
        series.extend([
            {'series': 'gpu_node_network_collection_success' + labels,
             'values': '1 1 1 0' if scenario == 'counter_collection_failed' else '1 1 1 1'},
            {'series': 'up{job="gpu-node-healthcheck",instance="synthetic-node:9105"}',
             'values': '1 1 1 0' if scenario == 'exporter_scrape_failed' else '1 1 1 1'},
        ])
        expected = [{'labels': '{interface="eth0",instance="synthetic-node:9105",job="gpu-node-healthcheck"}',
                     'value': 10}] if healthy else []
        tests.append({'name': scenario, 'interval': '15s', 'input_series': series,
                      'promql_expr_test': [{'expr': expr, 'eval_time': '45s',
                                           'exp_samples': expected} for expr in queries]})
    # Controls for real zero traffic, initial sampling and recovery.
    import copy
    healthy_test = tests[-1]
    for name, values, when, expected in (
        ('zero_traffic', '150 150 150 150', '45s', 0),
        ('startup', '150', '0s', None),
        ('recovery', '150 300 stale 600 750 900 1050 1200', '105s', 10),
    ):
        case = copy.deepcopy(healthy_test)
        case['name'] = name
        for series in case['input_series']:
            series['values'] = values if '_total{' in series['series'] else '1 1 1 1 1 1 1 1'
        if name == 'recovery':
            case['input_series'][-2]['values'] = '1 1 0 1 1 1 1 1'
            case['input_series'][-1]['values'] = '1 1 0 1 1 1 1 1'
        for assertion in case['promql_expr_test']:
            assertion['eval_time'] = when
            if expected is None:
                assertion['exp_samples'] = []
            else:
                assertion['exp_samples'][0]['value'] = expected
        tests.append(case)
    # Different interfaces/nodes/jobs must not grant one another collection health.
    case = copy.deepcopy(healthy_test)
    case['name'] = 'matching_isolation'
    case['input_series'][-2]['values'] = '0 0 0 0'
    for instance, interface, job in (
        ('synthetic-node:9105', 'eth1', 'gpu-node-healthcheck'),
        ('other-node:9105', 'eth0', 'gpu-node-healthcheck'),
        ('synthetic-node:9105', 'eth0', 'other-job'),
    ):
        suffix = f'{{job="{job}",instance="{instance}",interface="{interface}"}}'
        case['input_series'].extend({'series': metric + suffix, 'values': '150 300 450 600'} for metric in metrics)
        case['input_series'].append({'series': 'gpu_node_network_collection_success' + suffix, 'values': '1 1 1 1'})
        if instance != 'synthetic-node:9105' or job != 'gpu-node-healthcheck':
            case['input_series'].append({'series': f'up{{job="{job}",instance="{instance}"}}', 'values': '1 1 1 1'})
    for assertion in case['promql_expr_test']:
        assertion['exp_samples'] = [
            {'labels': '{interface="eth1",instance="synthetic-node:9105",job="gpu-node-healthcheck"}', 'value': 10},
            {'labels': '{interface="eth0",instance="other-node:9105",job="gpu-node-healthcheck"}', 'value': 10},
        ]
    tests.append(case)
    result = {'rule_files': [], 'evaluation_interval': '15s', 'tests': tests}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(f'Wrote {len(queries) * len(tests)} assertions; native execution still required')


if __name__ == '__main__':
    main()
