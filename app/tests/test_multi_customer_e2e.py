"""
End-to-end multi-customer integration test.

Exercises the whole path against the running stack:
    generator -> Kafka -> consumer -> IoTDB, and Grafana's tenant setup.

Marked `integration` and skipped automatically when the stack is not up,
so the default `pytest app/tests` run stays hermetic and fast:

    pytest app/tests -m integration          # run only these
    pytest app/tests -m "not integration"    # skip them explicitly

The assertions are deliberately about *isolation* as much as about
throughput. A pipeline that delivers data quickly but leaks one
customer's readings into another's series is worse than one that is
merely slow.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from base64 import b64encode

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fleet import load_fleet

pytestmark = [pytest.mark.integration, pytest.mark.slow]

IOTDB_CONTAINER = os.environ.get("IOTDB_CONTAINER", "iotdb")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:13000")
GRAFANA_ADMIN_USER = os.environ.get("GRAFANA_ADMIN_USER", "admin")
GRAFANA_ADMIN_PASSWORD = os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin")
CUSTOMER_USER_PASSWORD = os.environ.get("CUSTOMER_USER_PASSWORD", "customer123")

# Turbines the task requires proof for. The fleet has nine; these three
# are the ones that must show two customers writing concurrently.
REQUIRED_DEVICES = (
    "root.digitaltwin.customer1.site1.turbine01",
    "root.digitaltwin.customer1.site1.turbine02",
    "root.digitaltwin.customer2.site1.turbine03",
)
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
def row_counts_over_window():
    """Row counts for every required device before and after a 30-second
    observation window. Module-scoped: the window is paid for once."""
    before = {device: _count_rows(device) for device in REQUIRED_DEVICES}
    time.sleep(OBSERVATION_WINDOW_S)
    after = {device: _count_rows(device) for device in REQUIRED_DEVICES}
    return before, after


def grafana_request(path: str, user: str, password: str):
    token = b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"{GRAFANA_URL}{path}", headers={"Authorization": f"Basic {token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except urllib.error.URLError as exc:
        pytest.skip(f"Grafana not reachable at {GRAFANA_URL}: {exc.reason}")


class TestGeneratorsAreProducing:
    @pytest.mark.parametrize("service", ["c1-t01", "c1-t02", "c2-t03"])
    def test_generator_logs_produced_telemetry(self, service):
        logs = subprocess.run(
            ["docker", "logs", "--tail", "400", f"turbine-generator-{service}"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert "Produced telemetry" in logs.stdout + logs.stderr

    def test_every_fleet_generator_container_is_running(self, fleet):
        for turbine in fleet.turbines:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}",
                 f"turbine-{turbine.service_name}"],
                capture_output=True, text=True, timeout=30, check=False,
            )
            assert result.stdout.strip() == "healthy", turbine.service_name


class TestConsumerRoutesToEveryDevice:
    def test_all_required_devices_exist_in_iotdb(self):
        output = iotdb_query("SHOW DEVICES root.digitaltwin.**")
        for device in REQUIRED_DEVICES:
            assert device in output, f"{device} missing from IoTDB"

    def test_every_required_device_accumulates_rows(self, row_counts_over_window):
        before, after = row_counts_over_window
        for device in REQUIRED_DEVICES:
            assert after[device] > before[device], (
                f"{device} gained no rows in {OBSERVATION_WINDOW_S}s "
                f"({before[device]} -> {after[device]})"
            )

    def test_no_data_loss_over_the_window(self, row_counts_over_window):
        """At ~1 Hz a 30-second window should yield roughly 30 rows per
        device. Allow generous slack for batch flush timing at the window
        edges, but catch a device that is only trickling."""
        before, after = row_counts_over_window
        for device in REQUIRED_DEVICES:
            gained = after[device] - before[device]
            assert gained >= OBSERVATION_WINDOW_S * 0.5, (
                f"{device} gained only {gained} rows in {OBSERVATION_WINDOW_S}s"
            )

    def test_consumer_reports_processed_batches(self):
        logs = subprocess.run(
            ["docker", "logs", "--tail", "500", "turbine-consumer"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert "Processed batch" in logs.stdout + logs.stderr

    def test_recent_readings_are_physically_plausible(self):
        """Guards against the failure mode where rows arrive but every
        value is null or clipped -- a green pipeline writing garbage."""
        output = iotdb_query(
            "SELECT last_value(TURBINE_SPEED_RPM) "
            "FROM root.digitaltwin.customer1.site1.turbine01"
        )
        values = [
            float(cell)
            for line in output.splitlines()
            for cell in (c.strip() for c in line.split("|"))
            if cell.replace(".", "", 1).replace("-", "", 1).isdigit()
        ]
        assert values, f"no RPM value returned:\n{output}"
        assert any(0 <= v <= 13000 for v in values), values


class TestNoCrossCustomerLeakage:
    def test_each_customers_subtree_holds_only_its_own_turbines(self, fleet):
        for customer in fleet.customers:
            output = iotdb_query(f"SHOW DEVICES root.digitaltwin.{customer.customer_id}.**")
            own_turbines = {t.turbine_id for t in customer.turbines}
            for other in fleet.customers:
                if other.customer_id == customer.customer_id:
                    continue
                for turbine in other.turbines:
                    if turbine.turbine_id in own_turbines:
                        continue
                    assert turbine.turbine_id not in output, (
                        f"{turbine.turbine_id} ({other.customer_id}) appears under "
                        f"{customer.customer_id}'s subtree"
                    )

    def test_customer2_subtree_contains_no_customer1_data(self):
        output = iotdb_query("SHOW DEVICES root.digitaltwin.customer2.**")
        assert "customer1" not in output
        assert "turbine01" not in output


class TestGrafanaTenantIsolation:
    def test_admin_sees_one_org_per_customer(self, fleet):
        status, orgs = grafana_request("/api/orgs", GRAFANA_ADMIN_USER, GRAFANA_ADMIN_PASSWORD)
        assert status == 200
        names = {org["name"] for org in orgs}
        for customer in fleet.customers:
            assert customer.display_name in names

    @pytest.mark.parametrize("customer_id", ["customer1", "customer2", "customer3"])
    def test_customer_user_belongs_to_exactly_one_org(self, fleet, customer_id):
        customer = fleet.customer(customer_id)
        status, orgs = grafana_request(
            "/api/user/orgs", customer.grafana_login, CUSTOMER_USER_PASSWORD
        )
        assert status == 200, f"{customer.grafana_login} could not authenticate"
        names = [org["name"] for org in orgs]
        assert names == [customer.display_name], (
            f"{customer.grafana_login} can see orgs {names}; expected only "
            f"{customer.display_name}"
        )

    def test_customer1_cannot_see_customer2_org(self, fleet):
        customer1 = fleet.customer("customer1")
        _, orgs = grafana_request(
            "/api/user/orgs", customer1.grafana_login, CUSTOMER_USER_PASSWORD
        )
        assert "Customer2" not in {org["name"] for org in orgs}

    @pytest.mark.parametrize("customer_id", ["customer1", "customer2", "customer3"])
    def test_customer_sees_only_their_own_datasource(self, fleet, customer_id):
        customer = fleet.customer(customer_id)
        status, sources = grafana_request(
            "/api/datasources", customer.grafana_login, CUSTOMER_USER_PASSWORD
        )
        if status == 403:
            pytest.skip("Viewer role cannot list datasources on this Grafana version")
        assert status == 200
        uids = {source["uid"] for source in sources}
        assert customer.datasource_uid in uids
        for other in fleet.customers:
            if other.customer_id != customer.customer_id:
                assert other.datasource_uid not in uids

    @pytest.mark.parametrize("customer_id", ["customer1", "customer2", "customer3"])
    def test_customer_dashboard_loads_for_its_owner(self, fleet, customer_id):
        customer = fleet.customer(customer_id)
        status, dashboard = grafana_request(
            f"/api/dashboards/uid/{customer.dashboard_uid}",
            customer.grafana_login,
            CUSTOMER_USER_PASSWORD,
        )
        assert status == 200, f"{customer.dashboard_uid} did not load"
        assert dashboard["dashboard"]["title"] == f"{customer.display_name} Fleet"
        assert dashboard["dashboard"]["panels"]

    def test_customer1_cannot_load_customer2_dashboard(self, fleet):
        customer1 = fleet.customer("customer1")
        customer2 = fleet.customer("customer2")
        status, _ = grafana_request(
            f"/api/dashboards/uid/{customer2.dashboard_uid}",
            customer1.grafana_login,
            CUSTOMER_USER_PASSWORD,
        )
        assert status in (403, 404), (
            f"customer1 loaded customer2's dashboard (HTTP {status}) -- tenant leak"
        )

    def test_dashboards_query_only_their_owners_device_paths(self, fleet):
        # Fetched as the owning user, not as admin: admin lives in org 1
        # and gets a 404 for every tenant dashboard, which would make this
        # test vacuously pass.
        for customer in fleet.customers:
            status, payload = grafana_request(
                f"/api/dashboards/uid/{customer.dashboard_uid}",
                customer.grafana_login,
                CUSTOMER_USER_PASSWORD,
            )
            assert status == 200, f"{customer.dashboard_uid} did not load"
            # Panels template the turbine segment ($turbine_id) so the
            # dashboard can filter to one unit. Isolation therefore rests on
            # the *fixed* part of the path: everything up to the turbine name
            # must be a site this customer owns, and the templated segment
            # must be the last one, so no variable value can climb out of
            # the subtree.
            own_prefixes = {t.device_path.rsplit(".", 1)[0] for t in customer.turbines}
            for panel in payload["dashboard"]["panels"]:
                for target in panel.get("targets", []):
                    for path in target["prefixPath"]:
                        fixed, _, templated = path.rpartition(".")
                        assert fixed in own_prefixes, (
                            f"{customer.customer_id} panel {panel['title']!r} queries "
                            f"{path!r}, outside its own device paths"
                        )
                        assert templated == "$turbine_id", (
                            f"{customer.customer_id} panel {panel['title']!r} templates "
                            f"{templated!r}; only the turbine segment may be variable"
                        )

    def test_dashboards_expose_a_turbine_filter_listing_only_own_turbines(self, fleet):
        """The dropdown is both the feature and a tenant boundary: it must
        offer every turbine the customer owns and no turbine they do not."""
        for customer in fleet.customers:
            status, payload = grafana_request(
                f"/api/dashboards/uid/{customer.dashboard_uid}",
                customer.grafana_login,
                CUSTOMER_USER_PASSWORD,
            )
            assert status == 200, f"{customer.dashboard_uid} did not load"
            variables = {
                v["name"]: v for v in payload["dashboard"]["templating"]["list"]
            }
            assert "turbine_id" in variables, "no turbine filter on the dashboard"
            turbine_variable = variables["turbine_id"]
            assert turbine_variable["multi"] is False, (
                "IoTDB paths have no brace alternation, so a multi-select "
                "variable would interpolate to a query matching nothing"
            )
            offered = {opt["value"] for opt in turbine_variable["options"]}
            own = {t.turbine_id for t in customer.turbines}
            everyone_else = {t.turbine_id for t in fleet.turbines} - own
            assert own <= offered, f"{customer.customer_id} cannot select all its turbines"
            assert not (offered & everyone_else), (
                f"{customer.customer_id} is offered another tenant's turbines"
            )

    def test_dashboards_rename_sensors_to_display_names(self, fleet):
        """The whole point of sensor_mappings.json: an operator should read
        "Gearbox Bearing Temp A", not "TT_109A"."""
        customer = fleet.customer("customer1")
        status, payload = grafana_request(
            f"/api/dashboards/uid/{customer.dashboard_uid}",
            customer.grafana_login,
            CUSTOMER_USER_PASSWORD,
        )
        assert status == 200
        display_names = [
            prop["value"]
            for panel in payload["dashboard"]["panels"]
            for override in panel.get("fieldConfig", {}).get("overrides", [])
            for prop in override["properties"]
            if prop["id"] == "displayName"
        ]
        assert any("Gearbox Bearing Temp A" in name for name in display_names), display_names
