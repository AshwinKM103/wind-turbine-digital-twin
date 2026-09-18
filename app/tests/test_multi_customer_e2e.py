"""
End-to-end integration test against the running stack.

Exercises the whole live path: replay-server -> Kafka -> consumer -> IoTDB.

Marked `integration` and skipped automatically when the stack is not up,
so the default `pytest app/tests` run stays hermetic and fast:

    pytest app/tests -m integration          # run only these
    pytest app/tests -m "not integration"    # skip them explicitly
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fleet import load_fleet
from kafka_consumer import build_device_path

pytestmark = [pytest.mark.integration, pytest.mark.slow]

IOTDB_CONTAINER = os.environ.get("IOTDB_CONTAINER", "iotdb")
OBSERVATION_WINDOW_S = 30


def iotdb_query(sql: str) -> str:
    """Run one statement through the IoTDB CLI inside the container."""
    result = subprocess.run(
        [
            "docker", "exec", IOTDB_CONTAINER,
            "/iotdb/sbin/start-cli.sh", "-h", "127.0.0.1", "-p", "6667",
            "-u", "root", "-pw", "root", "-e", sql,
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    return result.stdout + result.stderr


def _count_rows(device_path: str) -> int:
    output = iotdb_query(f"SELECT COUNT(seq_no) FROM {device_path}")
    for line in output.splitlines():
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) == 1 and cells[0].isdigit():
            return int(cells[0])
    return 0


def _stack_is_up() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", IOTDB_CONTAINER],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return result.stdout.strip() == "true"
    except (subprocess.SubprocessError, OSError):
        return False


@pytest.fixture(scope="module", autouse=True)
def require_running_stack():
    if not _stack_is_up():
        pytest.skip(f"stack not running (container {IOTDB_CONTAINER!r} is down)")


@pytest.fixture(scope="module")
def fleet():
    return load_fleet()


@pytest.fixture(scope="module")
def required_devices(fleet):
    """IoTDB-quoted device paths: fleet.Turbine.device_path is unquoted, but
    hyphenated identifiers like `zephyr-energy` require backtick-quoting in
    SQL (see kafka_consumer.quote_path_node)."""
    return tuple(
        build_device_path(
            customer_id=t.customer_id, site_id=t.site_id, turbine_id=t.turbine_id
        )
        for t in fleet.turbines
    )


@pytest.fixture(scope="module")
def row_counts_over_window(required_devices):
    """Row counts for every device before and after a 30-second observation
    window. Module-scoped: the window is paid for once."""
    before = {device: _count_rows(device) for device in required_devices}
    time.sleep(OBSERVATION_WINDOW_S)
    after = {device: _count_rows(device) for device in required_devices}
    return before, after


class TestReplayServerIsProducing:
    def test_replay_server_container_is_healthy(self):
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", "replay-server"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.stdout.strip() == "healthy"

    def test_replay_server_logs_replayed_samples(self):
        logs = subprocess.run(
            ["docker", "logs", "--tail", "400", "replay-server"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert "Replayed sample" in logs.stdout + logs.stderr


class TestConsumerRoutesToEveryDevice:
    def test_all_required_devices_exist_in_iotdb(self, required_devices):
        output = iotdb_query("SHOW DEVICES root.digitaltwin.**")
        for device in required_devices:
            assert device in output, f"{device} missing from IoTDB"

    def test_every_required_device_accumulates_rows(self, row_counts_over_window):
        before, after = row_counts_over_window
        for device, before_count in before.items():
            assert after[device] > before_count, (
                f"{device} gained no rows in {OBSERVATION_WINDOW_S}s "
                f"({before_count} -> {after[device]})"
            )

    def test_no_data_loss_over_the_window(self, row_counts_over_window):
        """At ~1 Hz a 30-second window should yield roughly 30 rows per
        device. Allow generous slack for batch flush timing at the window
        edges, but catch a device that is only trickling."""
        before, after = row_counts_over_window
        for device, before_count in before.items():
            gained = after[device] - before_count
            assert gained >= OBSERVATION_WINDOW_S * 0.5, (
                f"{device} gained only {gained} rows in {OBSERVATION_WINDOW_S}s"
            )

    def test_consumer_container_is_healthy(self):
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", "turbine-consumer"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.stdout.strip() == "healthy"

    def test_recent_readings_are_physically_plausible(self, required_devices):
        """Guards against the failure mode where rows arrive but every
        value is null or clipped -- a green pipeline writing garbage."""
        output = iotdb_query(
            f"SELECT last_value(TURBINE_SPEED_RPM) FROM {required_devices[0]}"
        )
        values = [
            float(cell)
            for line in output.splitlines()
            for cell in (c.strip() for c in line.split("|"))
            if cell.replace(".", "", 1).replace("-", "", 1).isdigit()
        ]
        assert values, f"no RPM value returned:\n{output}"
        assert any(0 <= v <= 13000 for v in values), values
