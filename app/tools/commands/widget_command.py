"""Widget deployment subcommands for thingsboard_admin."""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

from app.tools.commands.base import BaseCommand
from app.tools.thingsboard_core.widget_service import ThingsboardWidgetService

logger = logging.getLogger("tb_admin.widget")

REPO_ROOT = Path(__file__).resolve().parents[3]
WIDGET_DIR = REPO_ROOT / "app" / "thingsboard" / "widgets"
WIDGET_JS = WIDGET_DIR / "turbine-3d-babylon.js"
BABYLON_JSON = WIDGET_DIR / "turbine-3d-babylon.widget-type.json"
MIMIC_JSON = WIDGET_DIR / "turbine-mimic.widget-type.json"
THRESHOLD_JSON = WIDGET_DIR / "turbine-threshold-config.widget-type.json"
HEADROOM_JSON = WIDGET_DIR / "turbine-headroom-monitor.widget-type.json"

BABYLON_VERSION = "6.49.0"
BABYLON_RESOURCES = [
    {"url": f"https://cdn.babylonjs.com/v{BABYLON_VERSION}/babylon.js", "isModule": False},
    {"url": f"https://cdn.babylonjs.com/v{BABYLON_VERSION}/gui/babylon.gui.min.js", "isModule": False},
    {"url": f"https://cdn.babylonjs.com/v{BABYLON_VERSION}/loaders/babylonjs.loaders.min.js", "isModule": False},
]

TELEMETRY_LABELS = {
    "TURBINE_SPEED_RPM": "Speed",
    "GB_TRQ": "Torque",
    "FT_110A": "Inlet flow",
    "FT_162": "Leakage flow",
    "ACT_POS_FB": "Actuator position",
}


def _extract_block(source: str, var_name: str) -> str:
    pattern = re.compile(r"const\s+" + re.escape(var_name) + r"\s*=\s*`(.*?)`;\s*\n", re.DOTALL)
    match = pattern.search(source)
    if not match:
        raise ValueError(f"Could not find template literal block: {var_name}")
    return match.group(1)


def _extract_controller_script(source: str) -> str:
    start = source.find("// CONTROLLER_SCRIPT_START")
    end = source.find("// CONTROLLER_SCRIPT_END")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Could not find CONTROLLER_SCRIPT_START/END markers")
    return source[start + len("// CONTROLLER_SCRIPT_START"):end].strip()


def _telemetry_data_keys(source: str) -> list[dict]:
    pattern = re.compile(r"T3D_DEVICE_TELEMETRY_KEYS\s*=\s*\[(.*?)\];", re.DOTALL)
    match = pattern.search(source)
    if not match:
        raise ValueError("Could not find T3D_DEVICE_TELEMETRY_KEYS array in widget source")
    keys = re.findall(r'"([^"]+)"', match.group(1))
    return [{"name": k, "type": "timeseries", "label": TELEMETRY_LABELS.get(k, k)} for k in keys]


def build_babylon_descriptor(source: str) -> dict[str, Any]:
    template_html = _extract_block(source, "TEMPLATE_HTML")
    template_css = _extract_block(source, "TEMPLATE_CSS")
    controller_script = _extract_controller_script(source)
    default_config = {
        "datasources": [
            {
                "type": "entity",
                "entityAliasId": None,
                "dataKeys": [
                    {"name": "meshId", "type": "attribute", "label": "meshId"},
                    {"name": "healthScore", "type": "attribute", "label": "healthScore"},
                    {"name": "healthStatus", "type": "attribute", "label": "healthStatus"},
                    {"name": "activeAlertsCount", "type": "attribute", "label": "activeAlertsCount"},
                    {"name": "limitSensor", "type": "attribute", "label": "limitSensor"},
                    {"name": "warningLimit", "type": "attribute", "label": "warningLimit"},
                    {"name": "alarmLimit", "type": "attribute", "label": "alarmLimit"},
                    {"name": "criticalLimit", "type": "attribute", "label": "criticalLimit"},
                ],
            },
            {"type": "entity", "entityAliasId": None, "dataKeys": _telemetry_data_keys(source)},
        ],
        "timewindow": {"realtime": {"timewindowMs": 60000}},
        "showTitle": False,
        "backgroundColor": "transparent",
        "color": "rgba(255,255,255,0.87)",
        "padding": "0px",
        "settings": {
            "modelUrl": "/api/resource/general/tenant/turbine_rig_prototype.glb",
            "cameraPosition": {"alpha": -1.2, "beta": 1.1, "radius": 9},
        },
        "title": "Turbine 3D Digital Twin (Babylon.js)",
        "dropShadow": False,
        "enableFullscreen": False,
        "widgetStyle": {},
        "widgetCss": "",
        "titleStyle": {},
    }
    return {
        "type": "latest",
        "sizeX": 12,
        "sizeY": 9,
        "resources": BABYLON_RESOURCES,
        "templateHtml": template_html,
        "templateCss": template_css,
        "controllerScript": controller_script,
        "settingsSchema": "{}",
        "dataKeySettingsSchema": "{}",
        "defaultConfig": json.dumps(default_config),
    }


class WidgetCommand(BaseCommand):
    """Widget deployment command."""

    @classmethod
    def get_widget_service(cls, args: argparse.Namespace) -> ThingsboardWidgetService:
        cfg, session, http = cls.init_session(args, require_password=True, is_sysadmin=False)
        if not http:
            raise ValueError("Tenant admin password is required for widget operations.")
        return ThingsboardWidgetService(http)

    @classmethod
    def deploy_thresholds(cls, service: ThingsboardWidgetService) -> None:
        if THRESHOLD_JSON.exists():
            data = json.loads(THRESHOLD_JSON.read_text(encoding="utf-8"))
            service.save_or_update_widget_type(data["descriptor"], fqn="turbine_threshold_config", name="Turbine Threshold Configurator")
        if HEADROOM_JSON.exists():
            data = json.loads(HEADROOM_JSON.read_text(encoding="utf-8"))
            service.save_or_update_widget_type(data["descriptor"], fqn="turbine_headroom_monitor", name="Turbine Headroom & Limits Monitor")
        logger.info("✓ Threshold widgets deployed")

    @classmethod
    def deploy_babylon(cls, service: ThingsboardWidgetService) -> None:
        source = WIDGET_JS.read_text(encoding="utf-8")
        descriptor = build_babylon_descriptor(source)
        packaged = {
            "fqn": "turbine_3d_babylon",
            "name": "Turbine 3D Digital Twin (Babylon.js)",
            "deprecated": False,
            "description": "Custom Babylon.js turbine 3D digital twin",
            "descriptor": descriptor,
        }
        BABYLON_JSON.write_text(json.dumps(packaged, indent=2) + "\n", encoding="utf-8")
        service.save_or_update_widget_type(descriptor, fqn="turbine_3d_babylon", name="Turbine 3D Digital Twin (Babylon.js)")
        logger.info("✓ Babylon 3D widget deployed")

    @classmethod
    def deploy_copilot(cls, service: ThingsboardWidgetService) -> None:
        copilot_json = WIDGET_DIR / "turbine-copilot.widget-type.json"
        if copilot_json.exists():
            data = json.loads(copilot_json.read_text(encoding="utf-8"))
            service.save_or_update_widget_type(data.get("descriptor", data), fqn="turbine_copilot_chat", name="Turbine Copilot Chat")
            logger.info("✓ Copilot chat widget deployed from JSON")
        else:
            logger.warning("Copilot widget JSON not found at %s", copilot_json)

    @classmethod
    def deploy_mimic(cls, service: ThingsboardWidgetService) -> None:
        if MIMIC_JSON.exists():
            data = json.loads(MIMIC_JSON.read_text(encoding="utf-8"))
            service.save_or_update_widget_type(data["descriptor"], fqn="turbine_mimic", name="Turbine Process Mimic")
            logger.info("✓ Turbine mimic widget deployed")

    @classmethod
    def run_deploy_widget(cls, args: argparse.Namespace) -> int:
        target = getattr(args, "target", "all")
        try:
            service = cls.get_widget_service(args)
        except Exception as e:
            return cls.handle_error(e, "Widget deployment connection")

        if target in ("thresholds", "all"):
            cls.deploy_thresholds(service)
        if target in ("babylon-3d", "all"):
            cls.deploy_babylon(service)
        if target in ("copilot", "all"):
            cls.deploy_copilot(service)
        if target in ("mimic", "all"):
            cls.deploy_mimic(service)
        return 0


deploy_thresholds = WidgetCommand.deploy_thresholds
deploy_babylon = WidgetCommand.deploy_babylon
deploy_copilot = WidgetCommand.deploy_copilot
deploy_mimic = WidgetCommand.deploy_mimic
run_deploy_widget = WidgetCommand.run_deploy_widget


def register_widget_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("widget", help="Widget deployment management")
    widget_subs = parser.add_subparsers(dest="widget_command", required=True)

    deploy_p = widget_subs.add_parser("deploy", help="Deploy widget types")
    deploy_p.add_argument("target", choices=["thresholds", "babylon-3d", "copilot", "mimic", "all"], help="Target widget to deploy")
    deploy_p.set_defaults(handler=WidgetCommand.run_deploy_widget)
