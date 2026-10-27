"""Convert GPU Node Healthcheck results to Prometheus text metrics."""


def escape_label(value):
    """Escape values for Prometheus labels."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def metric(name, value, description, metric_type="gauge", labels=None):
    """Format a metric in Prometheus text exposition format."""
    if value is None:
        return ""

    label_text = ""

    if labels:
        label_text = "{" + ",".join(
            f'{key}="{escape_label(val)}"'
            for key, val in labels.items()
        ) + "}"

    return (
        f"# HELP {name} {description}\n"
        f"# TYPE {name} {metric_type}\n"
        f"{name}{label_text} {value}\n"
    )



def format_metrics(result):
    """Generate valid Prometheus text metrics."""
    output = []
    declared = set()

    def add(name, value, description, metric_type="gauge", labels=None):
        if value is None:
            return

        block = metric(
            name,
            value,
            description,
            metric_type=metric_type,
            labels=labels
        )

        lines = block.strip().splitlines()

        if name not in declared:
            output.extend(lines)
            declared.add(name)
        else:
            output.extend(
                line for line in lines
                if not line.startswith("# HELP ")
                and not line.startswith("# TYPE ")
            )

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
        0 if result["status"] == "OK" else 2,
        "Node health status, 0 OK, 2 critical"
    )

    for iface in result.get("network", []):
        labels = {"interface": iface["name"]}

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

    for gpu in result.get("gpu", {}).get("devices", []):
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

    return "\n".join(output) + "\n"
