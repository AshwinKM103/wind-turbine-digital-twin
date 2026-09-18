"""Dashboard deployment and visibility management subcommands for thingsboard_admin."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from app.tools.commands.base import BaseCommand
from app.tools.commands.widget_command import WIDGET_JS, build_babylon_descriptor
from app.tools.thingsboard_core.echarts_builder import build_chart_widget, make_axis, make_orbit
from app.tools.thingsboard_core.http_client import ThingsboardHttpClient

logger = logging.getLogger("tb_admin.dashboard")

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP_DIR = REPO_ROOT / "app" / "thingsboard" / "dashboards_backup"
DEFAULT_DEVICE_ID = "f82c5c10-afee-11f1-b871-bd111a5de747"
DEFAULT_ROOT_ASSET_ID = "9f243750-b002-11f1-b871-bd111a5de747"

ZEPHYR_TENANT_ID = os.environ.get("TB_TENANT_ID", "f5c4f900-afee-11f1-b871-bd111a5de747")
PARKED_TENANT_ID = "00000000-0000-0000-0000-000000000000"

DASHBOARDS_MAP: dict[str, dict[str, str]] = {
    "scada": {"id": "c5704b70-b04c-11f1-9bfc-5d2538928d0b", "title": "Turbine Process SCADA Mimic (Dedicated)", "slug": "turbine_process_scada_mimic"},
    "rotordynamics": {"id": "c578fe00-b04c-11f1-9bfc-5d2538928d0b", "title": "Turbine Rotordynamics & Vibration (Dedicated)", "slug": "turbine_rotordynamics_and_vibration"},
    "thermodynamics": {"id": "1d1d0d50-b196-11f1-a9d0-15449c55f7bc", "title": "Turbine Thermodynamics & Process Dynamics (Dedicated)", "slug": "turbine_thermodynamics_and_process"},
    "babylon3d": {"id": "3503e260-b0cc-11f1-9bfc-5d2538928d0b", "title": "Turbine 3D Digital Twin (Babylon.js — Animated)", "slug": "turbine_3d_babylon_animated"},
    "thresholds": {"id": "0774c890-b19a-11f1-a9d0-15449c55f7bc", "title": "Turbine Safety & Alarm Thresholds (Dedicated)", "slug": "turbine_safety_and_alarm_thresholds"},
}


def _run_psql(sql: str) -> str:
    cmd = ["docker", "exec", "-i", "thingsboard-postgres", "psql", "-U", "thingsboard", "-d", "thingsboard", "-t", "-A", "-c", sql]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _get_or_create_dash_id(http: ThingsboardHttpClient, title: str, fallback_title: str | None = None) -> str:
    res = http.get("/api/tenant/dashboards?pageSize=100&page=0")
    dashboards = res.get("data", []) if isinstance(res, dict) else []
    for d in dashboards:
        if d.get("title") == title:
            return d["id"]["id"]
    if fallback_title:
        for d in dashboards:
            if d.get("title") == fallback_title:
                return d["id"]["id"]
    new_dash = {
        "title": title,
        "name": title,
        "configuration": {
            "widgets": {},
            "states": {"default": {"name": title, "root": True, "layouts": {"main": {"widgets": {}, "gridSettings": {"backgroundColor": "#0b1120", "columns": 24, "margin": 10, "autoFillHeight": True}}}}},
        },
    }
    res = http.post("/api/dashboard", data=new_dash)
    return res["id"]["id"]


def deploy_split_dashboards(http: ThingsboardHttpClient, base_url: str) -> None:
    device_id = os.getenv("TB_DEVICE_ID", DEFAULT_DEVICE_ID)
    root_asset_id = os.getenv("TB_ROOT_ASSET_ID", DEFAULT_ROOT_ASSET_ID)

    dash_mimic_id = _get_or_create_dash_id(http, "Turbine Process SCADA Mimic (Dedicated)")
    dash_vib_id = _get_or_create_dash_id(http, "Turbine Rotordynamics & Vibration (Dedicated)", fallback_title="Turbine Diagnostics & Multi-Trace Trends (Dedicated)")
    dash_thermo_id = _get_or_create_dash_id(http, "Turbine Thermodynamics & Process Dynamics (Dedicated)")
    dash_thresh_id = _get_or_create_dash_id(http, "Turbine Safety & Alarm Thresholds (Dedicated)")

    chart_def = http.get("/api/widgetType?fqn=system.time_series_chart")
    chart_cfg_def = json.loads(chart_def["descriptor"]["defaultConfig"]) if isinstance(chart_def, dict) else {}

    alias_dev = "a1111111-0000-0000-0000-000000000001"
    alias_subs = "a1111111-0000-0000-0000-000000000002"
    entity_aliases = {
        alias_subs: {"id": alias_subs, "alias": "Turbine Subsystems", "filter": {"type": "relationsQuery", "resolveMultiple": True, "rootEntity": {"entityType": "ASSET", "id": root_asset_id}, "direction": "FROM", "filters": [{"relationType": "Contains", "entityTypes": ["ASSET"]}]}},
        alias_dev: {"id": alias_dev, "alias": "Turbine Device (Boreas)", "filter": {"type": "singleEntity", "singleEntity": {"entityType": "DEVICE", "id": device_id}}},
    }
    grid_settings = {"backgroundColor": "#0b1120", "color": "rgba(255, 255, 255, 0.87)", "columns": 24, "backgroundSizeMode": "100%", "autoFillHeight": True, "mobileAutoFillHeight": False, "mobileRowHeight": 70, "margin": 10, "outerMargin": True}

    # 1. SCADA Mimic
    headline_keys = ["TURBINE_SPEED_RPM", "GB_TRQ", "PYRO_T", "PYRO_GB", "PT_109A", "TT_109A", "FT_110A", "PT_150A", "TT_150A", "XT_600", "XT_601", "XT_604", "XT_605", "ZT_600", "PT_111", "TT_111", "PT_112", "TT_112", "PT_120", "ACT_POS_FB"]
    w_mimic = {"typeFullFqn": "tenant.turbine_mimic", "type": "latest", "title": "Turbine Process SCADA Mimic", "sizeX": 24, "sizeY": 16, "row": 0, "col": 0, "id": "c2222222-0000-0000-0000-000000000002", "config": {"datasources": [{"type": "entity", "entityAliasId": alias_dev, "subscribed": True, "dataKeys": [{"name": k, "type": "timeseries", "label": k} for k in headline_keys]}], "settings": {"title": "Boreas Live SCADA", "maxRpm": 14000}, "showTitle": False, "backgroundColor": "transparent", "color": "#f8fafc", "padding": "0px"}}
    http.post("/api/dashboard", data={"id": {"entityType": "DASHBOARD", "id": dash_mimic_id}, "title": "Turbine Process SCADA Mimic (Dedicated)", "configuration": {"description": "SCADA Mimic", "widgets": {"c2222222-0000-0000-0000-000000000002": w_mimic}, "states": {"default": {"name": "Process SCADA Mimic", "root": True, "layouts": {"main": {"widgets": {"c2222222-0000-0000-0000-000000000002": {"sizeX": 24, "sizeY": 16, "row": 0, "col": 0}}, "gridSettings": grid_settings}}}}, "entityAliases": entity_aliases, "timewindow": {"realtime": {"timewindowMs": 60000}}, "settings": {"showTitle": False, "toolbarAlwaysOpen": True}}})

    # 2. Rotordynamics
    w_o_turb = make_orbit("Turbine Rotor Shaft Orbit (Lissajous)", "XT_600", "XT_601", alias_dev, "Probes: XT_600 vs XT_601", 12, 11)
    w_o_turb["id"] = "c3333333-0000-0000-0000-000000000003"; w_o_turb["row"] = 0; w_o_turb["col"] = 0
    w_o_gb = make_orbit("Gearbox Pinion Shaft Orbit (Lissajous)", "XT_604", "XT_605", alias_dev, "Probes: XT_604 vs XT_605", 12, 11)
    w_o_gb["id"] = "c3333333-0000-0000-0000-000000000004"; w_o_gb["row"] = 0; w_o_gb["col"] = 12
    turb_vib_y = {"turb_vib": make_axis("turb_vib", "Turbine Vibration (mils)", "mils", 3, 0, "left", 0.0, None, True)}
    w_t_vib = build_chart_widget("Turbine Journal Bearing Radial Vibration Trends", [("XT_600", "Turbine Vib X (XT_600)", "#f59e0b", "turb_vib", "mils", 3), ("XT_601", "Turbine Vib Y (XT_601)", "#00e5ff", "turb_vib", "mils", 3)], turb_vib_y, alias_dev, chart_cfg_def, 12, 11)
    w_t_vib["id"] = "c3333333-0000-0000-0000-000000000002"; w_t_vib["row"] = 11; w_t_vib["col"] = 0
    gb_vib_y = {"gb_vib": make_axis("gb_vib", "Gearbox Vib (mils)", "mils", 3, 0, "left", 0.0, 3.0, True), "axial": make_axis("axial", "Thrust Axial Disp (mils)", "mils", 2, 1, "right", None, None, False)}
    w_g_vib = build_chart_widget("Gearbox Bearing Vibration & Shaft Axial Displacement", [("XT_604", "Gearbox Vib X (XT_604)", "#fb7185", "gb_vib", "mils", 3), ("XT_605", "Gearbox Vib Y (XT_605)", "#fb923c", "gb_vib", "mils", 3), ("ZT_600", "Thrust Axial Disp (ZT_600)", "#c084fc", "axial", "mils", 2)], gb_vib_y, alias_dev, chart_cfg_def, 12, 11)
    w_g_vib["id"] = "c3333333-0000-0000-0000-000000000006"; w_g_vib["row"] = 11; w_g_vib["col"] = 12
    vib_widgets = {w["id"]: w for w in [w_o_turb, w_o_gb, w_t_vib, w_g_vib]}
    vib_layout = {k: {"sizeX": w["sizeX"], "sizeY": w["sizeY"], "row": w["row"], "col": w["col"]} for k, w in vib_widgets.items()}
    http.post("/api/dashboard", data={"id": {"entityType": "DASHBOARD", "id": dash_vib_id}, "title": "Turbine Rotordynamics & Vibration (Dedicated)", "configuration": {"description": "Rotordynamics", "widgets": vib_widgets, "states": {"default": {"name": "Rotordynamics & Vibration", "root": True, "layouts": {"main": {"widgets": vib_layout, "gridSettings": grid_settings}}}}, "entityAliases": entity_aliases, "timewindow": {"realtime": {"timewindowMs": 300000}}, "settings": {"showTitle": False, "toolbarAlwaysOpen": True}}})

    # 3. Thermodynamics
    st_y = {"speed": make_axis("speed", "Speed (RPM)", "RPM", 0, 0, "left", 0.0, None, True), "trq": make_axis("trq", "Torque (kN·m)", "kN·m", 3, 1, "right", 0.0, None, False)}
    w_st = build_chart_widget("Turbine Rotor Speed & Drivetrain Torque", [("TURBINE_SPEED_RPM", "Speed", "#38bdf8", "speed", "RPM", 0), ("GB_TRQ", "Torque", "#10b981", "trq", "kN·m", 3)], st_y, alias_dev, chart_cfg_def, 12, 11)
    w_st["id"] = "c4444444-0000-0000-0000-000000000001"; w_st["row"] = 0; w_st["col"] = 0
    th_y = {"pyro": make_axis("pyro", "Core Temp (°C)", "°C", 1, 0, "left", None, None, True), "steam": make_axis("steam", "Steam Cycle Temp (°C)", "°C", 1, 1, "right", None, None, False)}
    w_th = build_chart_widget("Turbine Core Pyrometry & Thermal Profiling", [("PYRO_T", "Turbine Core", "#f43f5e", "pyro", "°C", 1), ("PYRO_GB", "Gearbox", "#c084fc", "pyro", "°C", 1), ("TT_109A", "Inlet Temp", "#f59e0b", "steam", "°C", 1), ("TT_150A", "Exhaust Temp", "#06b6d4", "steam", "°C", 1)], th_y, alias_dev, chart_cfg_def, 12, 11)
    w_th["id"] = "c4444444-0000-0000-0000-000000000002"; w_th["row"] = 0; w_th["col"] = 12
    v_y = {"pos": make_axis("pos", "Position (%)", "%", 1, 0, "left", 0.0, None, True), "flow": make_axis("flow", "Flow (TPH)", "TPH", 3, 1, "right", 0.0, None, False)}
    w_v = build_chart_widget("Steam Governor Valve Positioning & Mass Flow Ingress", [("ACT_POS_FB", "Actuator FB", "#06b6d4", "pos", "%", 1), ("HP_DEMAND", "HP Demand", "#84cc16", "pos", "%", 1), ("FT_110A", "Mass Flow", "#f59e0b", "flow", "TPH", 3)], v_y, alias_dev, chart_cfg_def, 12, 11)
    w_v["id"] = "c4444444-0000-0000-0000-000000000003"; w_v["row"] = 11; w_v["col"] = 0
    p_y = {"inlet": make_axis("inlet", "Admission Header (bar)", "bar", 1, 0, "left", None, None, True), "exp": make_axis("exp", "Expansion Stages (bar)", "bar", 3, 1, "right", 0.0, None, False)}
    w_p = build_chart_widget("Steam Expansion Stage Pressure Profile", [("PT_109A", "Inlet Steam", "#00f2fe", "inlet", "bar", 1), ("PT_110A", "Header Press", "#38bdf8", "inlet", "bar", 1), ("PT_111", "TV1 Admission", "#c084fc", "exp", "bar", 3), ("PT_112", "TV2 Admission", "#fbbf24", "exp", "bar", 3), ("PT_120", "Wheel Case", "#fb7185", "exp", "bar", 3), ("PT_150A", "Exhaust Stage", "#34d399", "exp", "bar", 3)], p_y, alias_dev, chart_cfg_def, 12, 11)
    w_p["id"] = "c4444444-0000-0000-0000-000000000004"; w_p["row"] = 11; w_p["col"] = 12
    thermo_widgets = {w["id"]: w for w in [w_st, w_th, w_v, w_p]}
    thermo_layout = {k: {"sizeX": w["sizeX"], "sizeY": w["sizeY"], "row": w["row"], "col": w["col"]} for k, w in thermo_widgets.items()}
    http.post("/api/dashboard", data={"id": {"entityType": "DASHBOARD", "id": dash_thermo_id}, "title": "Turbine Thermodynamics & Process Dynamics (Dedicated)", "configuration": {"description": "Thermodynamics", "widgets": thermo_widgets, "states": {"default": {"name": "Thermodynamics & Steam Dynamics", "root": True, "layouts": {"main": {"widgets": thermo_layout, "gridSettings": grid_settings}}}}, "entityAliases": entity_aliases, "timewindow": {"realtime": {"timewindowMs": 300000}}, "settings": {"showTitle": False, "toolbarAlwaysOpen": True}}})

    # 4. Thresholds
    w_t_cfg = {"typeFullFqn": "tenant.turbine_threshold_config", "type": "latest", "title": "Turbine Threshold Configurator", "sizeX": 12, "sizeY": 18, "row": 0, "col": 0, "id": "c5555555-0000-0000-0000-000000000001", "config": {"datasources": [], "settings": {}, "showTitle": False, "backgroundColor": "transparent", "padding": "0px"}}
    w_t_hr = {"typeFullFqn": "tenant.turbine_headroom_monitor", "type": "latest", "title": "Turbine Headroom & Limits Monitor", "sizeX": 12, "sizeY": 18, "row": 0, "col": 12, "id": "c5555555-0000-0000-0000-000000000002", "config": {"datasources": [{"type": "entity", "entityAliasId": alias_dev, "subscribed": True, "dataKeys": [{"name": k, "type": "timeseries", "label": k} for k in ["XT_600", "XT_604", "ZT_600", "PYRO_T", "PYRO_GB", "TT_109A", "PT_109A", "TURBINE_SPEED_RPM"]]}], "settings": {}, "showTitle": False, "backgroundColor": "transparent", "padding": "0px"}}
    thresh_widgets = {w["id"]: w for w in [w_t_cfg, w_t_hr]}
    thresh_layout = {k: {"sizeX": w["sizeX"], "sizeY": w["sizeY"], "row": w["row"], "col": w["col"]} for k, w in thresh_widgets.items()}
    http.post("/api/dashboard", data={"id": {"entityType": "DASHBOARD", "id": dash_thresh_id}, "title": "Turbine Safety & Alarm Thresholds (Dedicated)", "configuration": {"description": "Thresholds", "widgets": thresh_widgets, "states": {"default": {"name": "Safety & Alarm Thresholds", "root": True, "layouts": {"main": {"widgets": thresh_layout, "gridSettings": grid_settings}}}}, "entityAliases": entity_aliases, "timewindow": {"realtime": {"timewindowMs": 60000}}, "settings": {"showTitle": False, "toolbarAlwaysOpen": True}}})
    logger.info("✓ Operational split dashboards deployed")


def deploy_babylon_dashboard(http: ThingsboardHttpClient) -> None:
    device_id = os.getenv("TB_DEVICE_ID", DEFAULT_DEVICE_ID)
    root_asset_id = os.getenv("TB_ROOT_ASSET_ID", DEFAULT_ROOT_ASSET_ID)
    dash_id = "3503e260-b0cc-11f1-9bfc-5d2538928d0b"
    widget_id = "d2222222-0000-0000-0000-000000000002"
    sub_alias_id = "b2222222-0000-0000-0000-000000000001"
    dev_alias_id = "b2222222-0000-0000-0000-000000000002"

    source = WIDGET_JS.read_text(encoding="utf-8")
    descriptor = build_babylon_descriptor(source)
    default_config = json.loads(descriptor["defaultConfig"])
    datasources = default_config["datasources"]
    datasources[0]["entityAliasId"] = sub_alias_id
    datasources[1]["entityAliasId"] = dev_alias_id

    dash_payload = {
        "id": {"entityType": "DASHBOARD", "id": dash_id},
        "title": "Turbine 3D Digital Twin (Babylon.js — Animated)",
        "configuration": {
            "description": "Standalone animated Babylon.js turbine 3D digital twin",
            "entityAliases": {
                sub_alias_id: {"id": sub_alias_id, "alias": "Turbine Subsystems", "filter": {"type": "relationsQuery", "resolveMultiple": True, "rootEntity": {"entityType": "ASSET", "id": root_asset_id}, "direction": "FROM", "filters": [{"relationType": "Contains", "entityTypes": ["ASSET"]}]}},
                dev_alias_id: {"id": dev_alias_id, "alias": "Turbine Device (Boreas)", "filter": {"type": "singleEntity", "singleEntity": {"entityType": "DEVICE", "id": device_id}}},
            },
            "widgets": {widget_id: {"id": widget_id, "typeFullFqn": "tenant.turbine_3d_babylon", "type": "latest", "title": "Turbine 3D Digital Twin (Babylon.js — Animated)", "sizeX": 24, "sizeY": 22, "row": 0, "col": 0, "config": {"datasources": datasources, "timewindow": {"realtime": {"timewindowMs": 60000}}, "showTitle": False, "backgroundColor": "transparent", "color": "rgba(255,255,255,0.87)", "padding": "0px", "settings": {"modelUrl": "/api/resource/general/tenant/turbine_rig_prototype.glb", "cameraPosition": {"alpha": -1.2, "beta": 1.1, "radius": 9}}}}},
            "states": {"default": {"name": "3D Digital Twin (Babylon.js)", "root": True, "layouts": {"main": {"widgets": {widget_id: {"sizeX": 24, "sizeY": 22, "row": 0, "col": 0}}, "gridSettings": {"backgroundColor": "#0b1120", "color": "rgba(255, 255, 255, 0.87)", "columns": 24, "backgroundSizeMode": "100%", "autoFillHeight": True, "mobileAutoFillHeight": False, "mobileRowHeight": 70, "margin": 10, "outerMargin": True}}}}},
        },
    }
    try:
        http.get(f"/api/dashboard/{dash_id}")
    except Exception:
        dash_payload.pop("id", None)
    http.post("/api/dashboard", data=dash_payload)
    logger.info("✓ Dedicated Babylon 3D dashboard deployed")


class DashboardCommand(BaseCommand):
    """Dashboard deployment and maintenance command."""

    @classmethod
    def run_deploy_dashboard(cls, args: argparse.Namespace) -> int:
        cfg, session, http = cls.init_session(args, require_password=True, is_sysadmin=False)
        if not http:
            return 1

        target = getattr(args, "target", "all")
        if target in ("split", "all"):
            deploy_split_dashboards(http, cfg.base_url)
        if target in ("babylon", "all"):
            deploy_babylon_dashboard(http)
        return 0

    @classmethod
    def run_dashboard_status(cls, args: argparse.Namespace) -> int:
        res = _run_psql("SELECT id, tenant_id FROM dashboard")
        db_tenants = {}
        for line in res.splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 2:
                db_tenants[parts[0].strip()] = parts[1].strip()

        print("\nDashboard Visibility Status:")
        for key, info in DASHBOARDS_MAP.items():
            is_active = (db_tenants.get(info["id"]) == ZEPHYR_TENANT_ID)
            badge = "VISIBLE" if is_active else "HIDDEN (PARKED)"
            print(f" • [{key:<14}] {info['title']:<52} -> {badge}")
        print()
        return 0

    @classmethod
    def run_dashboard_backup(cls, args: argparse.Namespace) -> int:
        out_dir = Path(getattr(args, "output", None) or BACKUP_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        cfg, session, http = cls.init_session(args, require_password=False, is_sysadmin=False)

        for info in DASHBOARDS_MAP.values():
            dash_id = info["id"]
            saved = False
            if http:
                try:
                    data = http.get(f"/api/dashboard/{dash_id}")
                    (out_dir / f"{info['slug']}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
                    saved = True
                except Exception:
                    pass
            if not saved:
                res = _run_psql(f"SELECT configuration FROM dashboard WHERE id = '{dash_id}'")
                if res:
                    (out_dir / f"{info['slug']}_config.json").write_text(res, encoding="utf-8")
            logger.info("Backed up '%s'", info["title"])
        return 0

    @classmethod
    def run_dashboard_isolate_3d(cls, args: argparse.Namespace) -> int:
        for key, info in DASHBOARDS_MAP.items():
            tenant = ZEPHYR_TENANT_ID if key == "babylon3d" else PARKED_TENANT_ID
            _run_psql(f"UPDATE dashboard SET tenant_id = '{tenant}' WHERE id = '{info['id']}';")
        logger.info("🎉 3D Digital Twin isolated! All other dashboards are parked.")
        return 0

    @classmethod
    def run_dashboard_visibility(cls, args: argparse.Namespace) -> int:
        name = getattr(args, "name", None)
        visible = getattr(args, "visible", True)
        if name not in DASHBOARDS_MAP:
            logger.error("Unknown dashboard key: %s (choose from: %s)", name, list(DASHBOARDS_MAP.keys()))
            return 1
        info = DASHBOARDS_MAP[name]
        target_tenant = ZEPHYR_TENANT_ID if visible else PARKED_TENANT_ID
        _run_psql(f"UPDATE dashboard SET tenant_id = '{target_tenant}' WHERE id = '{info['id']}';")
        logger.info("✓ %s: '%s'", "Unhid (Made Visible)" if visible else "Hid (Parked)", info["title"])
        return 0


run_deploy_dashboard = DashboardCommand.run_deploy_dashboard
run_dashboard_status = DashboardCommand.run_dashboard_status
run_dashboard_backup = DashboardCommand.run_dashboard_backup
run_dashboard_isolate_3d = DashboardCommand.run_dashboard_isolate_3d
run_dashboard_visibility = DashboardCommand.run_dashboard_visibility


def register_dashboard_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("dashboard", help="Dashboard deployment and maintenance")
    dash_subs = parser.add_subparsers(dest="dashboard_command", required=True)

    deploy_p = dash_subs.add_parser("deploy", help="Deploy operational dashboards")
    deploy_p.add_argument("target", choices=["split", "babylon", "all"], help="Dashboard target to deploy")
    deploy_p.set_defaults(handler=DashboardCommand.run_deploy_dashboard)

    status_p = dash_subs.add_parser("status", help="Show dashboard visibility in database")
    status_p.set_defaults(handler=DashboardCommand.run_dashboard_status)

    backup_p = dash_subs.add_parser("backup", help="Dump dashboard JSONs to disk")
    backup_p.add_argument("--output", default=None, help="Directory to save backup JSONs")
    backup_p.set_defaults(handler=DashboardCommand.run_dashboard_backup)

    iso_p = dash_subs.add_parser("isolate-3d", help="Set 3D twin visible, park others")
    iso_p.set_defaults(handler=DashboardCommand.run_dashboard_isolate_3d)

    show_p = dash_subs.add_parser("show", help="Unhide specific dashboard")
    show_p.add_argument("name", choices=list(DASHBOARDS_MAP.keys()), help="Dashboard key")
    show_p.set_defaults(handler=DashboardCommand.run_dashboard_visibility, visible=True)

    hide_p = dash_subs.add_parser("hide", help="Hide specific dashboard")
    hide_p.add_argument("name", choices=list(DASHBOARDS_MAP.keys()), help="Dashboard key")
    hide_p.set_defaults(handler=DashboardCommand.run_dashboard_visibility, visible=False)
