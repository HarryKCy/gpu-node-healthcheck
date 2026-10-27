# GPU Node Healthcheck

[![Tests](https://github.com/HarryKCy/gpu-node-healthcheck/actions/workflows/test.yml/badge.svg)](https://github.com/HarryKCy/gpu-node-healthcheck/actions/workflows/test.yml)

A lightweight Linux infrastructure monitoring tool with optional NVIDIA GPU telemetry and Prometheus integration.

## Features

- Linux memory, disk and CPU load monitoring
- NVIDIA GPU temperature, utilization and memory statistics
- Network interface status and RX/TX counters
- Network errors and dropped packet statistics
- JSON health reports
- Configurable critical thresholds
- Prometheus-compatible metrics
- HTTP exporter on port 9105
- Automated Python tests
- GitHub Actions CI

## Requirements

- Linux
- Python 3.10 or newer
- Optional NVIDIA drivers and nvidia-smi

No additional Python packages required.

## Quick Start

Clone the repository:

    git clone https://github.com/HarryKCy/gpu-node-healthcheck.git
    cd gpu-node-healthcheck

Run a health check:

    python3 healthcheck.py

Run with a custom memory threshold:

    python3 healthcheck.py --memory-critical 80

Require NVIDIA GPU telemetry:

    python3 healthcheck.py --require-gpu

## Prometheus Exporter

Start the exporter:

    python3 exporter.py

Open the metrics endpoint:

    http://127.0.0.1:9105/metrics

Test using curl:

    curl http://127.0.0.1:9105/metrics

The exporter binds to localhost by default.

## Exit Codes

- 0 = OK
- 2 = CRITICAL
- 3 = UNKNOWN

## Automated Tests

Run:

    python3 -m unittest discover -s tests -v

The project currently includes 12 automated tests.

## Project Structure

    gpu-node-healthcheck/
        healthcheck.py
        network.py
        prometheus.py
        exporter.py
        tests/
        .github/workflows/test.yml
        .gitignore
        README.md

## Limitations

- NVIDIA GPU telemetry requires compatible hardware and drivers.
- GPU metrics have been tested with simulated data.
- Network counters are cumulative, not packet loss rates.
- The exporter is designed for local or trusted environments.
- This is an educational and portfolio project.

## Future Improvements

- Grafana dashboard
- More NVIDIA GPU health indicators
- Network error-rate calculations
- Additional exporter tests
- Container deployment

## Author

Harry Karasavvas

Senior Infrastructure Engineer

GitHub: https://github.com/HarryKCy

## License

No license has been assigned.
