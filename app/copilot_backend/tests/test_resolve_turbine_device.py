"""Tests for tb_tools.resolve_turbine_device.

Tests verify the server-side entity resolution contract that closes the
"entity_id hallucination" bug: the LLM/widget must never be trusted to name
its own ThingsBoard entity ID. resolve_turbine_device is the only path that
is allowed to produce an entity_id, and it must always verify against the
live ThingsBoard device registry.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.copilot_backend import thingsboard_tools
from app.copilot_backend.thingsboard_tools import ToolError, resolve_turbine_device


def _device(name: str, device_id: str) -> dict:
    return {"id": {"id": device_id, "entityType": "DEVICE"}, "name": name}


class TestResolveTurbineDevice:
    def test_resolves_known_turbine_id_via_fleet_json_name(self):
        """A turbine_id from fleet.json should resolve via its
        '{customer}.{site}.{turbine}' ThingsBoard device name."""
        client = MagicMock()
        client.find_device_by_name.side_effect = lambda name: (
            _device(name, "abc-123") if name == "zephyr-energy.cascade-ridge.boreas" else None
        )

        result = resolve_turbine_device(client, "boreas")

        assert result == {
            "entity_type": "DEVICE",
            "entity_id": "abc-123",
            "device_name": "zephyr-energy.cascade-ridge.boreas",
        }

    def test_raises_tool_error_for_unknown_turbine(self):
        """An unresolvable turbine_id must raise, never silently return a
        hallucinated/guessed identifier."""
        client = MagicMock()
        client.find_device_by_name.return_value = None

        with pytest.raises(ToolError):
            resolve_turbine_device(client, "not-a-real-turbine")

    def test_raises_tool_error_for_empty_turbine_id(self):
        client = MagicMock()
        with pytest.raises(ToolError):
            resolve_turbine_device(client, "")

    def test_verifies_raw_uuid_against_live_registry_instead_of_trusting_it(self):
        """If a caller already supplies what looks like a device UUID, it must
        still be checked against ThingsBoard's live list_devices() rather than
        being accepted at face value."""
        client = MagicMock()
        real_uuid = "f82c5c10-afee-11f1-b871-bd111a5de747"
        client.list_devices.return_value = [_device("zephyr-energy.cascade-ridge.boreas", real_uuid)]

        result = resolve_turbine_device(client, real_uuid)

        assert result["entity_id"] == real_uuid
        client.list_devices.assert_called_once()

    def test_rejects_uuid_not_found_in_live_registry(self):
        """A syntactically valid UUID that doesn't exist in ThingsBoard must
        still be rejected, not trusted blindly."""
        client = MagicMock()
        client.list_devices.return_value = []

        with pytest.raises(ToolError):
            resolve_turbine_device(client, "00000000-0000-0000-0000-000000000000")

    def test_falls_back_to_turbine_id_as_device_name_if_not_in_fleet_json(self):
        """A turbine_id absent from fleet.json should still be tried directly
        as a ThingsBoard device name before giving up."""
        client = MagicMock()
        client.find_device_by_name.side_effect = lambda name: (
            _device(name, "xyz-999") if name == "some-directly-named-device" else None
        )

        result = resolve_turbine_device(client, "some-directly-named-device")

        assert result["entity_id"] == "xyz-999"
