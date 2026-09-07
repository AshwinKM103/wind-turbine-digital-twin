"""Unit tests for kafka_consumer.py's pure functions (no Kafka/IoTDB required)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kafka_consumer import MEASUREMENTS, payload_to_row, validate_payload  # noqa: E402


class TestValidatePayload:
    def test_accepts_well_formed_payload(self):
        payload = {
            "event_time_ms": 1725600000000,
            "customer_id": "customer1",
            "turbine_id": "turbine01",
            "seq_no": 1,
            "metrics": {"GB_TRQ": 0.024},
        }
        validate_payload(payload)  # should not raise

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            validate_payload(["not", "a", "dict"])

    def test_rejects_missing_required_field(self):
        payload = {"customer_id": "c1", "turbine_id": "t1", "seq_no": 1}
        with pytest.raises(ValueError, match="missing required fields"):
            validate_payload(payload)

    def test_rejects_non_dict_metrics(self):
        payload = {
            "event_time_ms": 1, "customer_id": "c1", "turbine_id": "t1",
            "seq_no": 1, "metrics": "not-a-dict",
        }
        with pytest.raises(ValueError, match="metrics must be an object"):
            validate_payload(payload)

    def test_rejects_non_numeric_event_time(self):
        payload = {
            "event_time_ms": "not-a-number", "customer_id": "c1",
            "turbine_id": "t1", "seq_no": 1, "metrics": {},
        }
        with pytest.raises(ValueError, match="event_time_ms must be numeric"):
            validate_payload(payload)


class TestPayloadToRow:
    def test_maps_known_measurement(self):
        payload = {"event_time_ms": 1725600000000, "seq_no": 42, "metrics": {"GB_TRQ": 0.024}}
        ts, row = payload_to_row(payload)
        assert ts == 1725600000000
        gb_trq_index = MEASUREMENTS.index("GB_TRQ")
        assert row[gb_trq_index] == 0.024

    def test_missing_metric_becomes_none(self):
        payload = {"event_time_ms": 1, "seq_no": 1, "metrics": {}}
        _, row = payload_to_row(payload)
        assert all(v is None for v in row[:-1])  # all sensor fields None, seq_no excluded

    def test_seq_no_is_int_not_float(self):
        payload = {"event_time_ms": 1, "seq_no": 7, "metrics": {}}
        _, row = payload_to_row(payload)
        assert row[MEASUREMENTS.index("seq_no")] == 7

    def test_malformed_metric_value_becomes_none_not_exception(self):
        payload = {"event_time_ms": 1, "seq_no": 1, "metrics": {"GB_TRQ": "not-a-number"}}
        _, row = payload_to_row(payload)
        assert row[MEASUREMENTS.index("GB_TRQ")] is None


class TestSchemaConsistency:
    """The consumer's tablet types must equal the device template's types.

    These drifted apart unnoticed for the whole single-turbine phase:
    DATA_TYPES declared PYRO_T as DOUBLE while iotdb-schema.sql declared
    FLOAT. Nothing failed, because IoTDB auto-created every series from
    the consumer's own types. The first write to a device that actually
    carried the template failed with "registered type FLOAT, inserting
    type DOUBLE". This test compares the two directly so the next such
    edit fails in CI instead of in production.
    """

    @staticmethod
    def _types_from_ddl():
        import re
        from pathlib import Path

        ddl = (Path(__file__).resolve().parents[1] / "config" / "iotdb-schema.sql").read_text()
        body = re.search(r"CREATE DEVICE TEMPLATE turbine_template \((.*?)\n\)", ddl, re.S)
        assert body, "device template not found in iotdb-schema.sql"
        declared = re.findall(
            r"^\s*(\w+)\s+(FLOAT|DOUBLE|INT32|INT64|BOOLEAN|TEXT)\b", body.group(1), re.M
        )
        return declared

    def test_measurement_names_match_the_device_template(self):
        assert [name for name, _ in self._types_from_ddl()] == MEASUREMENTS

    def test_data_types_match_the_device_template(self):
        from kafka_consumer import DATA_TYPES

        declared = {name: type_name for name, type_name in self._types_from_ddl()}
        for measurement, data_type in zip(MEASUREMENTS, DATA_TYPES):
            assert data_type.name == declared[measurement], (
                f"{measurement}: consumer sends {data_type.name}, "
                f"schema declares {declared[measurement]}"
            )
