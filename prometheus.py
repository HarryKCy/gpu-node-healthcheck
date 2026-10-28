"""Convert GPU Node Healthcheck results to Prometheus text metrics."""

import math


def escape_label(value):
    """Escape values for Prometheus labels."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def sample(name, value, labels=None):
    """Format a metric in Prometheus text exposition format."""
    if value is None:
        return ""

    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Invalid numeric value for {name}: {value!r}")

    if isinstance(value, bool):
        value = int(value)
    label_text = ""

    if labels:
        label_text = "{" + ",".join(
            f'{key}="{escape_label(val)}"'
            for key, val in labels.items()
        ) + "}"

    return f"{name}{label_text} {value}\n"


def metric(name, value, description, metric_type="gauge", labels=None):
    """Render one metric with metadata (also used by standalone callers)."""
    if value is None:
        return ""
    return (f"# HELP {name} {description}\n# TYPE {name} {metric_type}\n"
            + sample(name, value, labels))


def format_metrics(result):
    """Render each family once, without reparsing or changing label content."""
    families = {}

    def add(name, value, description, metric_type="gauge", labels=None):
        if value is None:
            return
        if name not in families:
            families[name] = [f"# HELP {name} {description}\n# TYPE {name} {metric_type}\n"]
        families[name].append(sample(name, value, labels))

    add(
        "gpu_node_memory_used_percent",
        result["memory_used_pct"],
        "Linux memory utilization percentage"
    )

    add(
        "gpu_node_disk_used_percent",
        result["disk_used_pct"],
        "Filesystem utilization percentage"
    )

    add(
        "gpu_node_load_1m",
        result["load_1m"],
        "Linux one minute load average"
    )

    add(
        "gpu_node_logical_cpus",
        result["logical_cpus"],
        "Number of logical CPUs"
    )

    add(
        "gpu_node_health_status",
        {"OK": 0, "CRITICAL": 2}.get(result["status"], 3),
        "Node health status, 0 OK, 2 critical, 3 unknown"
    )

    for iface in result.get("network", []):
        labels = {"interface": iface["name"]}

        success = iface.get("collection_success", True)
        add("gpu_node_network_collection_success", int(success),
            "Whether all interface counters were collected", labels=labels)
        state = iface.get("state", "unknown")
        add("gpu_node_network_interface_info", 1, "Reported Linux interface state",
            labels={**labels, "state": state})
        if not success:
            continue

        for field in (
            "rx_bytes",
            "tx_bytes",
            "rx_errors",
            "tx_errors",
            "rx_dropped",
            "tx_dropped",
        ):
            add(
                f"gpu_node_network_{field}_total",
                iface[field],
                f"Network interface {field}",
                metric_type="counter",
                labels=labels
            )

    gpu_result = result.get("gpu", {})
    state = gpu_result.get("state", "unknown")
    add("gpu_node_gpu_collection_info", 1, "NVIDIA collection state; absence is not a device fault",
        labels={"state": state})
    add("gpu_node_gpu_collection_success", int(state == "ok"),
        "Whether all requested NVIDIA telemetry was collected")
    if state in ("ok", "partial", "no_devices"):
        add("gpu_node_gpu_devices", len(gpu_result.get("devices", [])),
            "Detected GPUs; omitted when device presence is unknown")

    for gpu in gpu_result.get("devices", []):
        labels = {
            "gpu": gpu["index"],
            "name": gpu["name"]
        }

        for field, metric_name in (
            ("temp_c", "temperature_celsius"),
            ("util_pct", "utilization_percent"),
            ("memory_used_mib", "memory_used_mib"),
            ("memory_total_mib", "memory_total_mib"),
        ):
            add(
                f"gpu_node_gpu_{metric_name}",
                gpu[field],
                f"NVIDIA GPU {field}",
                labels=labels
            )

    return "".join("".join(family) for family in families.values())
