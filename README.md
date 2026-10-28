# GPU Node Healthcheck

[![Tests](https://github.com/HarryKCy/gpu-node-healthcheck/actions/workflows/test.yml/badge.svg)](https://github.com/HarryKCy/gpu-node-healthcheck/actions/workflows/test.yml)

A lightweight, standard-library Python monitoring project for **Linux infrastructure health and observability**. It provides command-line health checks and a Prometheus HTTP exporter for host resources and network interfaces, with **optional NVIDIA GPU telemetry**. A Docker Compose stack supplies Prometheus and an automatically provisioned Grafana dashboard.

This is a hands-on Linux/SRE engineering portfolio project focused on explicit failure states, automated testing, and reproducible monitoring configuration.

## Architecture

```text
Linux host
  ├── CPU load, memory, filesystem usage
  ├── Network interfaces, traffic counters, errors and drops
  └── NVIDIA telemetry (optional; nvidia-smi)
              │
              ▼
     Python monitoring collectors
              │
        ┌─────┴───────────┐
        ▼                 ▼
   CLI health report   HTTP exporter
   healthcheck.py      127.0.0.1:9105/metrics
                           │  scrape every 15 seconds
                           ▼
                       Prometheus
                       127.0.0.1:9090
                           │
                           ▼
                         Grafana
                       127.0.0.1:3000
                 Provisioned datasource + dashboard
```

The exporter runs on the Linux host; Prometheus and Grafana run in Docker containers using **host networking** and loopback-bound HTTP endpoints. The provided Compose configuration targets a Linux development/test environment, not a public-facing production deployment.

## Capabilities

- CPU load, memory utilization, and filesystem usage checks.
- Network interface diagnostics, cumulative RX/TX counters, and error/drop counters.
- Optional NVIDIA GPU collection using `nvidia-smi`, with explicit states for unavailable hardware, unsupported readings, and collection failures.
- JSON-formatted CLI health output and configurable thresholds.
- Prometheus-compatible metrics on a local HTTP endpoint (`9105`).
- Prometheus 3.7.0 and Grafana 12.2.0 deployment using Docker Compose.
- Automatically provisioned Grafana Prometheus datasource and dashboard, using stable UIDs and read-only configuration mounts.
- Automated unit and integration-style tests using Python's standard library, plus GitHub Actions CI.

A host without NVIDIA support can still be healthy: missing optional GPU telemetry is **not** treated as proof of a failed Linux host.

## Requirements

**Standalone monitoring:**

- Linux
- Python 3.11 or newer recommended (GitHub Actions exercises Python 3.11–3.14)
- No third-party Python packages required
- Optional NVIDIA drivers and `nvidia-smi` for GPU telemetry

**Full monitoring stack:**

- Docker Engine and Docker Compose plugin
- Local ports `9105`, `9090`, and `3000` available

The stack is configured for Linux host networking. Prometheus expects the Python exporter on the same host at `127.0.0.1:9105`.

## Quick Start

```bash
git clone https://github.com/HarryKCy/gpu-node-healthcheck.git
cd gpu-node-healthcheck

# Run a one-shot host health check
python3 healthcheck.py

# Example: use a custom memory critical threshold
python3 healthcheck.py --memory-critical 80

# Treat missing or unusable GPU telemetry as required
python3 healthcheck.py --require-gpu
```

The CLI exit status uses `0` for OK, `2` for CRITICAL, and `3` for UNKNOWN.

## Run Prometheus and Grafana

**Terminal 1 — start the exporter:**

```bash
python3 exporter.py
```

Verify the local metrics endpoint:

```bash
curl http://127.0.0.1:9105/metrics
```

Keep the exporter running while using the monitoring stack.

**Terminal 2 — start the containers:**

```bash
sudo docker compose up -d
sudo docker compose ps
```

Open:

- Prometheus: <http://127.0.0.1:9090>
- Grafana: <http://127.0.0.1:3000>

Grafana automatically loads the **GPU Node Prometheus** datasource and the **GPU Node Healthcheck** dashboard from version-controlled provisioning files. **No manual datasource creation or dashboard import is required.** If this is your first Grafana deployment, securely configure the administrator credentials and replace any default password.

To stop the Compose stack without removing named volumes:

```bash
sudo docker compose stop
```

To recreate containers after changing mounts or Compose settings, use `sudo docker compose up -d`; simply starting an existing stopped container does not apply new mounts. Do **not** use `down -v` if you intend to preserve existing Grafana/Prometheus data.

### Provisioning files

```text
compose.yaml
monitoring/
  prometheus.yml
  grafana/provisioning/
    datasources/prometheus.yml
    dashboards/gpu-node.yml
dashboards/
  gpu-node-overview.json
```

Provisioning configuration and dashboard JSON are read-only mounts. The Compose stack stores application data in named Docker volumes.

## Metrics and interpretation

The dashboard separates **Linux host health**, **exporter/scrape status**, **network activity**, and **optional GPU collection state**.

- Counter-based network charts use Prometheus rate calculations. Shortly after the exporter starts, rate panels may show no data until enough scrape samples are available.
- Zero network traffic or zero observed errors is distinct from missing telemetry.
- GPU metrics may be absent on machines without NVIDIA drivers or compatible hardware; the dashboard reports collection state instead of inventing readings.
- Unsupported GPU sensors should not be interpreted as valid zero readings.

Metric definitions and exact labels are maintained in `prometheus.py` and the monitoring collectors. Consult the running `/metrics` endpoint for the actual available series on a given machine.

## Testing and CI

Run the Python tests locally:

```bash
python3 -m unittest discover -s tests -v
```

**Verified locally on Ubuntu 24.04 / Python 3.12**, 55 tests passed. The suite uses mocked NVIDIA responses and does not require a physical GPU.

GitHub Actions runs tests against Python **3.11, 3.12, 3.13, and 3.14**, and separately checks Docker Compose configuration, dashboard JSON, and Prometheus configuration. See the [workflow runs](https://github.com/HarryKCy/gpu-node-healthcheck/actions) for current CI results.

### Runtime validation performed

An isolated Docker Compose deployment was tested using separate project-scoped volumes and alternate localhost ports. Validation confirmed:

- Prometheus and Grafana containers reached healthy states.
- The Grafana datasource and dashboard were automatically provisioned.
- The exporter was scrapeable and Grafana could query Prometheus.
- All 16 dashboard PromQL queries executed successfully.
- Live CPU, memory, disk, and network metrics were visible in Grafana.
- On a laptop without NVIDIA support, GPU telemetry was reported as unavailable rather than fabricated.

These observations validate the Linux-only environment; they do **not** constitute validation against physical NVIDIA GPUs.

## Project layout

```text
.github/workflows/test.yml     GitHub Actions CI
healthcheck.py                 CLI and host/GPU collection
network.py                     Network interface diagnostics
prometheus.py                  Prometheus metric formatting
exporter.py                    HTTP metrics exporter
compose.yaml                   Prometheus + Grafana containers
monitoring/                    Prometheus and Grafana provisioning
dashboards/                    Version-controlled dashboard JSON
tests/                         Automated Python tests
README.md                      Project documentation
```

## Author

**Harry Karasavvas** — Linux and Infrastructure Engineering
GitHub: [HarryKCy](https://github.com/HarryKCy)

## License

No license has been assigned. All rights remain with the repository owner unless a license is added.
