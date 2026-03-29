"""Unit tests for docker-stats-exporter app.py.

These tests mock the Docker SDK so no running Docker daemon is required.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Provide a minimal stub for the 'docker' package so the module can be
# imported without the real SDK installed in the test environment.
# ---------------------------------------------------------------------------
def _ensure_docker_stub():
    if "docker" not in sys.modules:
        docker_mod = types.ModuleType("docker")
        docker_mod.from_env = MagicMock()
        sys.modules["docker"] = docker_mod


_ensure_docker_stub()

# Load app.py directly (directory name contains a hyphen, so normal import won't work).
_app_path = Path(__file__).parent.parent / "app.py"
_spec = importlib.util.spec_from_file_location("app", _app_path)
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)  # type: ignore[union-attr]


class TestNetworkAggregation(unittest.TestCase):
    """collect_loop should sum RX/TX across all network interfaces."""

    def _make_container(self, name, cid, rx, tx, service="svc"):
        c = MagicMock()
        c.name = name
        c.id = cid + "000000000000"  # docker IDs are 64 chars; we slice [:12]
        c.labels = {"com.docker.compose.service": service}
        c.stats.return_value = {
            "networks": {
                "eth0": {"rx_bytes": rx, "tx_bytes": tx},
            }
        }
        return c

    def test_single_container_metrics_set(self):
        """Gauge labels and values are set correctly for one container."""
        container = self._make_container("web", "abc123def456", rx=1000, tx=500)

        with patch("docker.from_env") as mock_from_env, \
                patch("time.sleep", side_effect=StopIteration):
            mock_client = MagicMock()
            mock_client.containers.list.return_value = [container]
            mock_from_env.return_value = mock_client

            with patch.object(app.RX, "labels") as mock_rx_labels, \
                    patch.object(app.TX, "labels") as mock_tx_labels:
                mock_rx_gauge = MagicMock()
                mock_tx_gauge = MagicMock()
                mock_rx_labels.return_value = mock_rx_gauge
                mock_tx_labels.return_value = mock_tx_gauge

                try:
                    app.collect_loop(poll_interval=0)
                except StopIteration:
                    pass

                mock_rx_labels.assert_called_once_with(
                    container="web", id="abc123def456", service="svc"
                )
                mock_rx_gauge.set.assert_called_once_with(1000)
                mock_tx_labels.assert_called_once_with(
                    container="web", id="abc123def456", service="svc"
                )
                mock_tx_gauge.set.assert_called_once_with(500)

    def test_multiple_interfaces_summed(self):
        """RX/TX bytes are summed across multiple network interfaces."""
        c = MagicMock()
        c.name = "db"
        c.id = "deadbeef1234" + "0" * 52
        c.labels = {}
        c.stats.return_value = {
            "networks": {
                "eth0": {"rx_bytes": 100, "tx_bytes": 50},
                "eth1": {"rx_bytes": 200, "tx_bytes": 75},
            }
        }

        with patch("docker.from_env") as mock_from_env, \
                patch("time.sleep", side_effect=StopIteration):
            mock_client = MagicMock()
            mock_client.containers.list.return_value = [c]
            mock_from_env.return_value = mock_client

            with patch.object(app.RX, "labels") as mock_rx_labels, \
                    patch.object(app.TX, "labels") as mock_tx_labels:
                mock_rx_gauge = MagicMock()
                mock_tx_gauge = MagicMock()
                mock_rx_labels.return_value = mock_rx_gauge
                mock_tx_labels.return_value = mock_tx_gauge

                try:
                    app.collect_loop(poll_interval=0)
                except StopIteration:
                    pass

                mock_rx_gauge.set.assert_called_once_with(300)
                mock_tx_gauge.set.assert_called_once_with(125)

    def test_no_networks_key_does_not_raise(self):
        """Containers with no 'networks' key in stats should not crash the loop."""
        c = MagicMock()
        c.name = "no-net"
        c.id = "0000000000001234"
        c.labels = {}
        c.stats.return_value = {}  # missing 'networks'

        with patch("docker.from_env") as mock_from_env, \
                patch("time.sleep", side_effect=StopIteration):
            mock_client = MagicMock()
            mock_client.containers.list.return_value = [c]
            mock_from_env.return_value = mock_client

            with patch.object(app.RX, "labels") as mock_rx_labels, \
                    patch.object(app.TX, "labels") as mock_tx_labels:
                mock_rx_labels.return_value = MagicMock()
                mock_tx_labels.return_value = MagicMock()

                try:
                    app.collect_loop(poll_interval=0)
                except StopIteration:
                    pass

                # Should still call set with 0 bytes
                mock_rx_labels.return_value.set.assert_called_once_with(0)
                mock_tx_labels.return_value.set.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
