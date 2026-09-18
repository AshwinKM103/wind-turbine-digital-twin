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
SENSOR_MAPPINGS_PATH = REPO_ROOT / "app" / "config" / "sensor_mappings.json"
FLEET_SCHEMA_PATH = REPO_ROOT / "app" / "config" / "iotdb-schema-fleet.sql"


@pytest.fixture(scope="module")
def fleet():
    return load_fleet()


def _turbine(customer="zephyr-energy", turbine="boreas", port=8101) -> Turbine:
    return Turbine(
        customer_id=customer, site_id="cascade-ridge", turbine_id=turbine, health_port=port
    )


class TestFleetConfig:
    def test_expected_fleet_shape(self, fleet):
        counts = {c.customer_id: len(c.turbines) for c in fleet.customers}
        assert counts == {"zephyr-energy": 1}

    def test_device_paths_are_unique_and_well_formed(self, fleet):
        pattern = re.compile(r"^root\.digitaltwin\.[a-z0-9-]+\.[a-z0-9-]+\.[a-z0-9-]+$")
        paths = [t.device_path for t in fleet.turbines]
        assert len(set(paths)) == len(paths) == 1
        for path in paths:
            assert pattern.match(path), path
        assert "root.digitaltwin.zephyr-energy.cascade-ridge.boreas" in paths

    def test_unknown_customer_raises(self, fleet):
        with pytest.raises(FleetConfigError, match="unknown customer_id"):
            fleet.customer("unknown-customer")

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
                    customer_id="zephyr-energy",
                    display_name="Zephyr Energy",
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
            [_turbine(turbine="boreas", port=8101), _turbine(turbine="zephyrus", port=8101)]
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

    def test_schema_activates_every_turbine(self, fleet):
        from kafka_consumer import quote_path_node

        schema = FLEET_SCHEMA_PATH.read_text()
        for turbine in fleet.turbines:
            quoted_path = ".".join(
                [
                    "root.digitaltwin",
                    quote_path_node(turbine.customer_id),
                    quote_path_node(turbine.site_id),
                    quote_path_node(turbine.turbine_id),
                ]
            )
            assert f"CREATE TIMESERIES USING DEVICE TEMPLATE ON {quoted_path};" in schema


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
