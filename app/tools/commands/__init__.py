"""Commands package for thingsboard_admin CLI."""

from __future__ import annotations

from app.tools.commands.auth_command import register_auth_parser
from app.tools.commands.dashboard_command import register_dashboard_parser
from app.tools.commands.entity_command import register_entity_parser
from app.tools.commands.health_command import register_health_parser
from app.tools.commands.metadata_command import register_metadata_parser
from app.tools.commands.rulechain_command import register_rulechain_parser
from app.tools.commands.widget_command import register_widget_parser

__all__ = [
    "register_auth_parser",
    "register_entity_parser",
    "register_widget_parser",
    "register_rulechain_parser",
    "register_metadata_parser",
    "register_health_parser",
    "register_dashboard_parser",
]
