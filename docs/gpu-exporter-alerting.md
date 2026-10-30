# GPU Node Exporter — Availability Alerting

## Purpose

Detect when Prometheus cannot successfully scrape the GPU node
healthcheck exporter.

## Architecture

GPU Node Exporter
        |
        v
Prometheus (15-second scrape interval)
        |
        v
GPUNodeExporterUnavailable
        |
        v
Operational investigation

## Alert Definition

Alert: GPUNodeExporterUnavailable

Expression:

    up{job="gpu-node-healthcheck"} == 0

Severity: warning

Pending duration: 2 minutes

The alert fires after the exporter target has continuously failed
scraping for the configured duration.

## Investigation

1. Verify exporter process availability.
2. Check connectivity to 127.0.0.1:9105.
3. Inspect exporter logs and HTTP responses.
4. Check NVIDIA driver and nvidia-smi availability.
5. Inspect Linux CPU, memory, disk and network health.
6. Verify successful Prometheus scraping after recovery.

## Limitations

- Detects exporter scrape failures, not every GPU hardware failure.
- Does not detect targets removed entirely from service discovery.
- No Alertmanager notification routing is configured.
- GPU-specific thresholds require separate alerting rules.

## Recovery Verification

Confirm that the Prometheus `up` metric returns 1.

Verify that the alert returns to the inactive state.

Record the incident timeline, cause, impact and recovery actions.

## Validation

Static validation:

    promtool check rules monitoring/alerts/gpu-node.yml

    promtool check config monitoring/prometheus.yml

Runtime validation:

    Simulate exporter unavailability in an isolated lab.

    Observe inactive → pending → firing → inactive transitions.

Runtime validation must be performed before claiming that the
alert lifecycle has been tested successfully.
