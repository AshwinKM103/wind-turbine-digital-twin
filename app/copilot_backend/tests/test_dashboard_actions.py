"""Tests for allowlisted dashboard-navigation actions.

Verifies the model can only ever produce a navigation intent for one of the
fixed, live-verified dashboards — never an arbitrary ID or URL.
"""

from __future__ import annotations

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.copilot_backend import dashboard_actions


class TestBuildOpenDashboardAction:
    def test_should_resolve_known_key_to_action(self):
        action = dashboard_actions.build_open_dashboard_action("scada_mimic")

        assert action["action"] == "OPEN_DASHBOARD"
        assert action["dashboardId"] == dashboard_actions.DASHBOARD_ALLOWLIST["scada_mimic"]["dashboardId"]
        assert action["dashboardKey"] == "scada_mimic"
        assert "label" in action

    def test_should_reject_unknown_key(self):
        with pytest.raises(dashboard_actions.DashboardActionError):
            dashboard_actions.build_open_dashboard_action("not_a_real_dashboard")

    def test_should_reject_empty_key(self):
        with pytest.raises(dashboard_actions.DashboardActionError):
            dashboard_actions.build_open_dashboard_action("")

    def test_allowlist_entries_should_have_uuid_shaped_ids(self):
        import re

        uuid_re = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
        for key, entry in dashboard_actions.DASHBOARD_ALLOWLIST.items():
            assert uuid_re.match(entry["dashboardId"]), f"{key} has a non-UUID dashboardId"

    def test_all_allowlist_keys_are_resolvable(self):
        for key in dashboard_actions.DASHBOARD_ALLOWLIST:
            action = dashboard_actions.build_open_dashboard_action(key)
            assert action["dashboardKey"] == key
