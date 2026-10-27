#!/usr/bin/env python3
"""Read-only Linux network interface statistics."""

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)


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

    # A failed directory read is a collection failure, not an empty healthy host.
    try:
        entries = sorted(sys_net.iterdir())
    except FileNotFoundError:
        return interfaces

    for interface in entries:
        name = interface.name

        if name == "lo":
            continue

        stats = interface / "statistics"

        counters_ok = True

        def counter(key):
            nonlocal counters_ok
            value = read_value(stats / key)
            try:
                number = int(value)
                if number < 0:
                    raise ValueError("Negative network counter")
                return number
            except (TypeError, ValueError):
                counters_ok = False
                LOGGER.warning("Unavailable network counter: %s/%s", name, key)
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
        # Keep legacy JSON zeros, but prevent the exporter from reporting them
        # as measured counters when an interface disappears or reads fail.
        interfaces[-1]["collection_success"] = counters_ok

    return interfaces
