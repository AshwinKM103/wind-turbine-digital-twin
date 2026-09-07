"""Tests for the fleet topology config and the artifacts generated from it."""

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from fleet import Fleet, FleetConfigError, Turbine, _validate, load_fleet

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
SENSOR_MAPPINGS_PATH = REPO_ROOT / "app" / "config" / "sensor_mappings.json"
FLEET_SCHEMA_PATH = REPO_ROOT / "app" / "config" / "iotdb-schema-fleet.sql"


@pytest.fixture(scope="module")
def fleet():
    return load_fleet()


def _turbine(customer="customer1", turbine="turbine01", port=8101) -> Turbine:
    return Turbine(customer_id=customer, site_id="site1", turbine_id=turbine, health_port=port)


class TestFleetConfig:
    def test_expected_fleet_shape(self, fleet):
        counts = {c.customer_id: len(c.turbines) for c in fleet.customers}
        assert counts == {"customer1": 2, "customer2": 3, "customer3": 4}

    def test_device_paths_are_unique_and_well_formed(self, fleet):
        pattern = re.compile(r"^root\.digitaltwin\.customer\d+\.site\d+\.turbine\d+$")
        paths = [t.device_path for t in fleet.turbines]
        assert len(set(paths)) == len(paths) == 9
        for path in paths:
            assert pattern.match(path), path

    def test_service_names_follow_the_generator_convention(self, fleet):
        names = [t.service_name for t in fleet.turbines]
        assert "generator-c1-t01" in names
        assert "generator-c2-t03" in names
        assert "generator-c3-t09" in names

    def test_unknown_customer_raises(self, fleet):
        with pytest.raises(FleetConfigError, match="unknown customer_id"):
            fleet.customer("customer99")

    def test_missing_file_raises_config_error(self, tmp_path):
        with pytest.raises(FleetConfigError, match="not found"):
            load_fleet(tmp_path / "absent.json")

    def test_malformed_json_raises_config_error(self, tmp_path):
        broken = tmp_path / "fleet.json"
        broken.write_text("{not json")
        with pytest.raises(FleetConfigError, match="not valid JSON"):
            load_fleet(broken)


class TestFleetValidation:
    """These guard the two topology mistakes that look like a working
    stack: duplicated device paths (silent data mixing) and duplicated
    health ports (a container that cannot bind)."""

    def _fleet_with(self, turbines):
        from fleet import Customer

        return Fleet(
            device_path_root="root.digitaltwin",
            customers=(
                Customer(
                    customer_id="customer1",
                    display_name="Customer1",
                    grafana_org_id=2,
                    grafana_login="customer1@company.com",
                    datasource_uid="iotdb-customer1",
                    dashboard_uid="customer1-fleet",
                    turbines=tuple(turbines),
                ),
            ),
        )

    def test_rejects_duplicate_device_path(self):
        duplicated = self._fleet_with([_turbine(port=8101), _turbine(port=8102)])
        with pytest.raises(FleetConfigError, match="duplicate device path"):
            _validate(duplicated)

    def test_rejects_duplicate_health_port(self):
        clashing = self._fleet_with(
            [_turbine(turbine="turbine01", port=8101), _turbine(turbine="turbine02", port=8101)]
        )
        with pytest.raises(FleetConfigError, match="health port 8101 claimed by both"):
            _validate(clashing)

    def test_rejects_customer_with_no_turbines(self):
        with pytest.raises(FleetConfigError, match="has no turbines"):
            _validate(self._fleet_with([]))

    def test_rejects_empty_fleet(self):
        with pytest.raises(FleetConfigError, match="no customers"):
            _validate(Fleet(device_path_root="root.digitaltwin", customers=()))


class TestGeneratedArtifactsAreCurrent:
    """Every generated file is regenerated in-memory and compared against
    what is committed. These fail when someone edits fleet.json or
    sensor_profiles.py without rerunning the generators -- the drift that
    would otherwise ship a dashboard pointing at a turbine that no longer
    exists."""

    def test_sensor_mappings_file_is_not_stale(self):
        from generate_sensor_mappings import build_mappings

        committed = json.loads(SENSOR_MAPPINGS_PATH.read_text())
        assert committed == build_mappings()

    def test_fleet_schema_file_is_not_stale(self):
        from generate_fleet_schema import render

        assert FLEET_SCHEMA_PATH.read_text() == render()

    def test_compose_has_one_generator_service_per_turbine(self, fleet):
        compose_text = COMPOSE_PATH.read_text()
        for turbine in fleet.turbines:
            assert f"  {turbine.service_name}:" in compose_text
            assert f"HEALTH_CHECK_PORT={turbine.health_port}" in compose_text
            assert f"TURBINE_ID={turbine.turbine_id}" in compose_text

    def test_compose_generator_block_is_not_stale(self):
        from generate_compose_generators import render_block

        assert render_block() in COMPOSE_PATH.read_text()

    def test_schema_activates_every_turbine(self, fleet):
        schema = FLEET_SCHEMA_PATH.read_text()
        for turbine in fleet.turbines:
            assert f"CREATE TIMESERIES USING DEVICE TEMPLATE ON {turbine.device_path};" in schema


class TestSensorMappings:
    def test_covers_every_measurement(self):
        from kafka_consumer import MEASUREMENTS

        mappings = json.loads(SENSOR_MAPPINGS_PATH.read_text())["sensors"]
        assert set(mappings) == {m for m in MEASUREMENTS if m != "seq_no"}

    def test_display_names_are_unique_and_human_readable(self):
        mappings = json.loads(SENSOR_MAPPINGS_PATH.read_text())["sensors"]
        names = [m["display_name"] for m in mappings.values()]
        assert len(set(names)) == len(names)
        for name in names:
            assert not re.match(r"^[A-Z]{2,4}_\d", name), f"{name} is still a raw sensor id"

    def test_known_rename_is_present(self):
        mappings = json.loads(SENSOR_MAPPINGS_PATH.read_text())["sensors"]
        assert mappings["TT_109A"]["display_name"] == "Gearbox Bearing Temp A"

    def test_every_sensor_has_a_usable_range(self):
        mappings = json.loads(SENSOR_MAPPINGS_PATH.read_text())["sensors"]
        for name, mapping in mappings.items():
            assert mapping["normal_range"]["min"] < mapping["normal_range"]["max"], name
            assert mapping["absolute_range"]["min"] <= mapping["normal_range"]["min"], name
            assert mapping["absolute_range"]["max"] >= mapping["normal_range"]["max"], name
