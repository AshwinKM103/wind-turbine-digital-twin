"""Rule chain provisioning subcommands for thingsboard_admin CLI.

Provides commands to create and configure the ISO 10816-3 Dynamic Threshold Alarm
Rule Chain in ThingsBoard, injecting TBEL scripts for vibration and pyrometer alarm
filters, alarm creation, and clearing nodes.

Exported Classes:
    RuleChainCommand: Handler for rule chain deployment and device profile linking.

Exported Functions:
    register_rulechain_parser: Registers rule chain subcommands with argparse.
    run_deploy_rulechain: Entry point alias for deploying the rule chain.
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

from app.tools.commands.base import BaseCommand

logger = logging.getLogger("tb_admin.rulechain")

RULE_CHAIN_NAME = "Turbine Dynamic Threshold Alarms"
TURBINE_DEVICE_PROFILE_ID = os.environ.get("TB_DEVICE_PROFILE_ID", "f82b98c0-afee-11f1-b871-bd111a5de747")


def _build_nodes_and_connections() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Constructs ThingsBoard rule engine nodes and connection definitions.

    Builds message type filter nodes, TBEL JavaScript filter scripts for vibration
    and temperature limits, and corresponding alarm creation/clear nodes.

    Returns:
        A tuple containing (nodes, connections) formatted for ThingsBoard rule chain metadata.
    """
    vib_filter_tbel = (
        "var limit = (metadata.shared_threshold_XT_600_alarm != null) ? "
        "parseFloat(metadata.shared_threshold_XT_600_alarm) : 6.0;\n"
        "return msg.XT_600 != null && msg.XT_600 > limit;"
    )
    vib_clear_tbel = (
        "var limit = (metadata.shared_threshold_XT_600_alarm != null) ? "
        "parseFloat(metadata.shared_threshold_XT_600_alarm) : 6.0;\n"
        "return msg.XT_600 != null && msg.XT_600 <= limit;"
    )
    vib_alarm_details_tbel = (
        "var details = {};\n"
        "if (metadata.prevAlarmDetails != null) {\n"
        "    details = JSON.parse(metadata.prevAlarmDetails);\n"
        "    metadata.remove('prevAlarmDetails');\n"
        "}\n"
        "details.XT_600 = msg.XT_600;\n"
        "details.threshold = 6.0;\n"
        "details.standard = 'ISO 10816-3 Class III Zone D Trip';\n"
        "details.message = 'Radial vibration probe XT_600 breached alarm trip threshold (' + "
        "msg.XT_600 + ' mm/s > 6.0 mm/s)';\n"
        "return details;"
    )
    vib_clear_details_tbel = (
        "var details = {};\n"
        "if (metadata.prevAlarmDetails != null) {\n"
        "    details = JSON.parse(metadata.prevAlarmDetails);\n"
        "    metadata.remove('prevAlarmDetails');\n"
        "}\n"
        "details.clearedAt_XT_600 = msg.XT_600;\n"
        "details.message = 'Radial vibration returned to normal range (' + msg.XT_600 + ' mm/s <= 6.0 mm/s)';\n"
        "return details;"
    )
    pyro_filter_tbel = (
        "var limit = (metadata.shared_threshold_PYRO_T_alarm != null) ? "
        "parseFloat(metadata.shared_threshold_PYRO_T_alarm) : 350.0;\n"
        "return msg.PYRO_T != null && msg.PYRO_T > limit;"
    )
    pyro_clear_tbel = (
        "var limit = (metadata.shared_threshold_PYRO_T_alarm != null) ? "
        "parseFloat(metadata.shared_threshold_PYRO_T_alarm) : 350.0;\n"
        "return msg.PYRO_T != null && msg.PYRO_T <= limit;"
    )
    pyro_alarm_details_tbel = (
        "var details = {};\n"
        "if (metadata.prevAlarmDetails != null) {\n"
        "    details = JSON.parse(metadata.prevAlarmDetails);\n"
        "    metadata.remove('prevAlarmDetails');\n"
        "}\n"
        "details.PYRO_T = msg.PYRO_T;\n"
        "details.threshold = 350.0;\n"
        "details.standard = 'API 612 Core Thermal Trip';\n"
        "details.message = 'Core pyrometer PYRO_T breached thermal trip threshold (' + "
        "msg.PYRO_T + ' °C > 350.0 °C)';\n"
        "return details;"
    )
    pyro_clear_details_tbel = (
        "var details = {};\n"
        "if (metadata.prevAlarmDetails != null) {\n"
        "    details = JSON.parse(metadata.prevAlarmDetails);\n"
        "    metadata.remove('prevAlarmDetails');\n"
        "}\n"
        "details.clearedAt_PYRO_T = msg.PYRO_T;\n"
        "details.message = 'Core temperature returned below trip threshold (' + msg.PYRO_T + ' °C <= 350.0 °C)';\n"
        "return details;"
    )

    nodes = [
        {"type": "org.thingsboard.rule.engine.filter.TbMsgTypeSwitchNode", "name": "Message Type Switch", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {}, "additionalInfo": {"layoutX": 80, "layoutY": 250}},
        {"type": "org.thingsboard.rule.engine.telemetry.TbMsgTimeseriesNode", "name": "Save Timeseries", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 1, "configuration": {"defaultTTL": 0, "useServerTs": False, "processingSettings": {"type": "ON_EVERY_MESSAGE"}}, "additionalInfo": {"layoutX": 380, "layoutY": 100}},
        {"type": "org.thingsboard.rule.engine.telemetry.TbMsgAttributesNode", "name": "Save Attributes", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 2, "configuration": {"scope": "SERVER_SCOPE", "notifyDevice": False, "sendAttributesUpdatedNotification": False}, "additionalInfo": {"layoutX": 380, "layoutY": 400}},
        {"type": "org.thingsboard.rule.engine.filter.TbJsFilterNode", "name": "Filter ISO Vibration Alarm (XT_600 > 6.0)", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {"scriptLang": "TBEL", "tbelScript": vib_filter_tbel, "jsScript": vib_filter_tbel}, "additionalInfo": {"layoutX": 380, "layoutY": 200}},
        {"type": "org.thingsboard.rule.engine.filter.TbJsFilterNode", "name": "Filter Vibration Normal (XT_600 <= 6.0)", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {"scriptLang": "TBEL", "tbelScript": vib_clear_tbel, "jsScript": vib_clear_tbel}, "additionalInfo": {"layoutX": 680, "layoutY": 250}},
        {"type": "org.thingsboard.rule.engine.action.TbCreateAlarmNode", "name": "Create Turbine Vibration Alarm", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {"alarmType": "Turbine Vibration Alarm", "severity": "CRITICAL", "propagate": True, "propagateToOwner": False, "propagateToTenant": True, "useMessageAlarmData": False, "overwriteAlarmDetails": True, "dynamicSeverity": False, "relationTypes": [], "scriptLang": "TBEL", "alarmDetailsBuildTbel": vib_alarm_details_tbel, "alarmDetailsBuildJs": vib_alarm_details_tbel}, "additionalInfo": {"layoutX": 680, "layoutY": 150}},
        {"type": "org.thingsboard.rule.engine.action.TbClearAlarmNode", "name": "Clear Turbine Vibration Alarm", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {"alarmType": "Turbine Vibration Alarm", "scriptLang": "TBEL", "alarmDetailsBuildTbel": vib_clear_details_tbel, "alarmDetailsBuildJs": vib_clear_details_tbel}, "additionalInfo": {"layoutX": 980, "layoutY": 250}},
        {"type": "org.thingsboard.rule.engine.filter.TbJsFilterNode", "name": "Filter ISO Overheat Alarm (PYRO_T > 350.0)", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {"scriptLang": "TBEL", "tbelScript": pyro_filter_tbel, "jsScript": pyro_filter_tbel}, "additionalInfo": {"layoutX": 380, "layoutY": 300}},
        {"type": "org.thingsboard.rule.engine.filter.TbJsFilterNode", "name": "Filter Overheat Normal (PYRO_T <= 350.0)", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {"scriptLang": "TBEL", "tbelScript": pyro_clear_tbel, "jsScript": pyro_clear_tbel}, "additionalInfo": {"layoutX": 680, "layoutY": 370}},
        {"type": "org.thingsboard.rule.engine.action.TbCreateAlarmNode", "name": "Create Turbine Overheat Alarm", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {"alarmType": "Turbine Overheat Alarm", "severity": "CRITICAL", "propagate": True, "propagateToOwner": False, "propagateToTenant": True, "useMessageAlarmData": False, "overwriteAlarmDetails": True, "dynamicSeverity": False, "relationTypes": [], "scriptLang": "TBEL", "alarmDetailsBuildTbel": pyro_alarm_details_tbel, "alarmDetailsBuildJs": pyro_alarm_details_tbel}, "additionalInfo": {"layoutX": 680, "layoutY": 300}},
        {"type": "org.thingsboard.rule.engine.action.TbClearAlarmNode", "name": "Clear Turbine Overheat Alarm", "debugSettings": None, "singletonMode": False, "queueName": None, "configurationVersion": 0, "configuration": {"alarmType": "Turbine Overheat Alarm", "scriptLang": "TBEL", "alarmDetailsBuildTbel": pyro_clear_details_tbel, "alarmDetailsBuildJs": pyro_clear_details_tbel}, "additionalInfo": {"layoutX": 980, "layoutY": 370}},
    ]
    connections = [
        {"fromIndex": 0, "toIndex": 1, "type": "Post telemetry"},
        {"fromIndex": 0, "toIndex": 2, "type": "Post attributes"},
        {"fromIndex": 0, "toIndex": 3, "type": "Post telemetry"},
        {"fromIndex": 0, "toIndex": 7, "type": "Post telemetry"},
        {"fromIndex": 3, "toIndex": 5, "type": "True"},
        {"fromIndex": 3, "toIndex": 4, "type": "False"},
        {"fromIndex": 4, "toIndex": 6, "type": "True"},
        {"fromIndex": 7, "toIndex": 9, "type": "True"},
        {"fromIndex": 7, "toIndex": 8, "type": "False"},
        {"fromIndex": 8, "toIndex": 10, "type": "True"},
    ]
    return nodes, connections


class RuleChainCommand(BaseCommand):
    """Rule chain provisioning and attachment command.

    Automates the deployment of dynamic alarm processing chains and attaches
    them as default chains to turbine device profiles in ThingsBoard.
    """

    @classmethod
    def run_deploy_rulechain(cls, args: argparse.Namespace) -> int:
        """Provisions ISO 10816-3 Dynamic Threshold Alarm Rule Chain.

        Args:
            args: Parsed command-line arguments containing server and credentials.

        Returns:
            Zero on successful rule chain deployment, non-zero on error.
        """
        cfg, session, http = cls.init_session(args, require_password=True, is_sysadmin=False)
        if not http:
            return 1

        # 1. Get or create rule chain
        existing_rc = None
        res = http.get("/api/ruleChains?pageSize=50&page=0")
        for rc in (res.get("data", []) if isinstance(res, dict) else []):
            if rc.get("name") == RULE_CHAIN_NAME:
                existing_rc = rc
                break

        if existing_rc:
            rc_id = existing_rc["id"]["id"]
            logger.info("Found existing Rule Chain '%s' (ID: %s)", RULE_CHAIN_NAME, rc_id)
        else:
            created = http.post(
                "/api/ruleChain",
                data={
                    "name": RULE_CHAIN_NAME,
                    "type": "CORE",
                    "debugMode": False,
                    "additionalInfo": {"description": "Dynamic ISO Threshold Alarm Processing"},
                },
            )
            rc_id = created["id"]["id"]
            logger.info("Created new Rule Chain '%s' (ID: %s)", RULE_CHAIN_NAME, rc_id)

        # 2. Metadata configuration
        nodes, connections = _build_nodes_and_connections()
        meta_payload = {
            "ruleChainId": {"entityType": "RULE_CHAIN", "id": rc_id},
            "firstNodeIndex": 0,
            "nodes": nodes,
            "connections": connections,
            "ruleChainConnections": None,
        }
        http.post("/api/ruleChain/metadata", data=meta_payload)
        logger.info("Configured %d nodes and %d connections in rule chain %s", len(nodes), len(connections), rc_id)

        # 3. Assign to Device Profile if available
        try:
            dp = http.get(f"/api/deviceProfile/{TURBINE_DEVICE_PROFILE_ID}")
            if isinstance(dp, dict) and "id" in dp:
                dp["defaultRuleChainId"] = {"entityType": "RULE_CHAIN", "id": rc_id}
                http.post("/api/deviceProfile", data=dp)
                logger.info("Assigned rule chain %s as defaultRuleChainId on turbine Device Profile", rc_id)
        except Exception as e:
            logger.warning("Could not set defaultRuleChainId on Device Profile: %s", e)

        return 0


run_deploy_rulechain = RuleChainCommand.run_deploy_rulechain


def register_rulechain_parser(subparsers: argparse._SubParsersAction) -> None:
    """Registers the rulechain subcommands and argument options.

    Args:
        subparsers: Subparser collection from argparse root command.
    """
    parser = subparsers.add_parser("rulechain", help="Rule chain management")
    rc_subs = parser.add_subparsers(dest="rulechain_command", required=True)

    deploy_p = rc_subs.add_parser("deploy", help="Deploy ISO 10816-3 dynamic threshold rule chain")
    deploy_p.set_defaults(handler=RuleChainCommand.run_deploy_rulechain)
