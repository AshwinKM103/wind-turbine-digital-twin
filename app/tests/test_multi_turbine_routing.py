"""
Tests for the consumer's multi-turbine fan-out.

One Kafka topic carries the whole fleet, so a single batch routinely mixes
customers. These tests pin the property that matters most in a
multi-tenant system: a message is written to the device path derived from
its own identifiers, and never to anyone else's.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kafka_consumer import (
    BufferedRecord,
    device_path_for,
    group_by_device,
    validate_payload,
)


def _payload(customer="customer1", turbine="turbine01", **overrides):
    payload = {
        "event_time_ms": 1725600000000,
        "customer_id": customer,
        "turbine_id": turbine,
        "seq_no": 1,
        "metrics": {"GB_TRQ": 1.0},
    }
    payload.update(overrides)
    return payload


class TestDevicePathRouting:
    def test_builds_path_from_payload_identifiers(self):
        assert (
            device_path_for(_payload("customer2", "turbine03"))
            == "root.digitaltwin.customer2.site1.turbine03"
        )

    def test_uses_payload_site_id_when_present(self):
        path = device_path_for(_payload(site_id="site9"))
        assert path == "root.digitaltwin.customer1.site9.turbine01"

    def test_falls_back_to_configured_site_when_absent(self):
        """Older producers predate site_id; such messages must still route."""
        assert device_path_for(_payload()).endswith(".site1.turbine01")

    @pytest.mark.parametrize(
        "customer,turbine",
        [
            ("customer1", "turbine01"),
            ("customer1", "turbine02"),
            ("customer2", "turbine03"),
            ("customer3", "turbine09"),
        ],
    )
    def test_each_turbine_gets_a_distinct_path(self, customer, turbine):
        path = device_path_for(_payload(customer, turbine))
        assert path == f"root.digitaltwin.{customer}.site1.{turbine}"

    def test_rejects_path_traversal_in_customer_id(self):
        """A dot would let a producer write outside its own tenant subtree."""
        with pytest.raises(ValueError, match="customer_id is not a valid identifier"):
            validate_payload(_payload(customer="customer1.site1.turbine01"))

    @pytest.mark.parametrize(
        "bad_id",
        ["", "cust omer", "customer*", "root.digitaltwin", "-leading-dash", "a" * 65, "cust'omer"],
    )
    def test_rejects_malformed_identifiers(self, bad_id):
        with pytest.raises(ValueError, match="is not a valid identifier"):
            validate_payload(_payload(customer=bad_id))

    def test_rejects_non_string_identifier(self):
        with pytest.raises(ValueError, match="turbine_id is not a valid identifier"):
            validate_payload(_payload(turbine=42))

    def test_rejects_malformed_site_id(self):
        with pytest.raises(ValueError, match="site_id is not a valid identifier"):
            device_path_for(_payload(site_id="site1.turbine02"))


class TestGroupByDevice:
    def _record(self, customer, turbine, seq):
        payload = _payload(customer, turbine)
        return BufferedRecord(device_path_for(payload), 1000 + seq, [seq], f"msg{seq}")

    def test_splits_a_mixed_batch_by_device(self):
        records = [
            self._record("customer1", "turbine01", 0),
            self._record("customer2", "turbine03", 1),
            self._record("customer1", "turbine01", 2),
            self._record("customer1", "turbine02", 3),
        ]
        groups = group_by_device(records)
        assert set(groups) == {
            "root.digitaltwin.customer1.site1.turbine01",
            "root.digitaltwin.customer1.site1.turbine02",
            "root.digitaltwin.customer2.site1.turbine03",
        }
        assert len(groups["root.digitaltwin.customer1.site1.turbine01"]) == 2

    def test_no_record_lands_in_another_tenants_group(self):
        records = [
            self._record("customer1", "turbine01", 0),
            self._record("customer2", "turbine03", 1),
            self._record("customer3", "turbine06", 2),
        ]
        for device_path, group in group_by_device(records).items():
            for record in group:
                assert record.device_path == device_path

    def test_preserves_record_order_within_a_group(self):
        records = [self._record("customer1", "turbine01", seq) for seq in range(5)]
        group = group_by_device(records)["root.digitaltwin.customer1.site1.turbine01"]
        assert [r.timestamp for r in group] == [1000, 1001, 1002, 1003, 1004]

    def test_loses_no_records(self):
        records = [
            self._record("customer1", "turbine01", 0),
            self._record("customer2", "turbine03", 1),
            self._record("customer2", "turbine04", 2),
            self._record("customer3", "turbine06", 3),
        ]
        groups = group_by_device(records)
        assert sum(len(g) for g in groups.values()) == len(records)

    def test_empty_batch_yields_no_groups(self):
        assert group_by_device([]) == {}

    def test_single_device_batch_is_one_group(self):
        records = [self._record("customer1", "turbine01", seq) for seq in range(3)]
        assert len(group_by_device(records)) == 1
