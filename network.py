#!/usr/bin/env python3
"""Read-only Linux network interface statistics."""

from pathlib import Path


SYS_NET = Path("/sys/class/net")


def read_value(path, default=None):
    """Read a sysfs value safely."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return default


def network_metrics(sys_net=SYS_NET):
    """Collect Linux network interface statistics."""
    interfaces = []

    if not sys_net.exists():
        return interfaces

    for interface in sorted(sys_net.iterdir()):
        name = interface.name

        if name == "lo":
            continue

        stats = interface / "statistics"

        def counter(key):
            value = read_value(stats / key, "0")
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        interfaces.append({
            "name": name,
            "state": read_value(interface / "operstate", "unknown"),
            "rx_bytes": counter("rx_bytes"),
            "tx_bytes": counter("tx_bytes"),
            "rx_errors": counter("rx_errors"),
            "tx_errors": counter("tx_errors"),
            "rx_dropped": counter("rx_dropped"),
            "tx_dropped": counter("tx_dropped"),
        })

    return interfaces
