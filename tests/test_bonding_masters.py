"""Regression tests for Linux bonding control entries."""

import tempfile
import unittest
from pathlib import Path

from network import network_metrics


class BondingMastersRegressionTests(unittest.TestCase):

    def test_bonding_masters_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # Simulate the Linux bonding control entry.
            (root / "bonding_masters").write_text("bond0\n")

            # Simulate a genuine bond interface.
            bond = root / "bond0"
            stats = bond / "statistics"
            stats.mkdir(parents=True)

            (bond / "operstate").write_text("up")

            counters = (
                "rx_bytes",
                "tx_bytes",
                "rx_errors",
                "tx_errors",
                "rx_dropped",
                "tx_dropped",
            )

            for name in counters:
                (stats / name).write_text("0")

            result = network_metrics(root)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["name"], "bond0")
            self.assertEqual(result[0]["state"], "up")
            self.assertTrue(result[0]["collection_success"])

            self.assertNotIn(
                "bonding_masters",
                [interface["name"] for interface in result],
            )


if __name__ == "__main__":
    unittest.main()
