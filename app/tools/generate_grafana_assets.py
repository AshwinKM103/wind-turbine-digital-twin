#!/usr/bin/env python3
"""
generate_grafana_assets.py - Render per-customer Grafana dashboards.

Emits one fleet dashboard per customer:

  provisioning/dashboards/json/<customer>/<customer>.json  (imported into org by setup_grafana_orgs.py)

Every panel is filtered to one turbine by the `turbine_id` dashboard
variable (see _turbine_variable): panels query
`root.digitaltwin.<customer>.<site>.$turbine_id`, so the dropdown selects
a single unit, or "All turbines" for the fleet-wide view.

Tenant isolation rests on two things:
  1. the datasource each dashboard references exists only inside that
     customer's Grafana org (created by scripts/setup_grafana_orgs.py), and
  2. every panel query here is prefix-scoped to that customer's device
     paths. Only the final, turbine-name segment is templated, so no value
     of `turbine_id` -- including one typed straight into the URL -- can
     reach outside the customer's own subtree.
A user in org 2 can therefore reach neither another org's datasource nor,
through their own, another customer's series.

scripts/setup_grafana_orgs.py imports these into the right org. They are
deliberately not file-provisioned: Grafana refuses to start when a
provisioning file names an org that does not exist yet.

Panels rename measurements to their display names (TT_109A ->
"Gearbox Bearing Temp A") via fieldConfig overrides generated from
sensor_mappings.json, so the mapping is never duplicated by hand.

Regenerate after editing fleet.json or sensor_profiles.py:
    python app/tools/generate_grafana_assets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "app" / "src"))

from fleet import Customer, load_fleet

SENSOR_MAPPINGS_PATH = REPO_ROOT / "app" / "config" / "sensor_mappings.json"
DASHBOARD_JSON_DIR = REPO_ROOT / "provisioning" / "dashboards" / "json"

DATASOURCE_TYPE = "apache-iotdb-datasource"
GENERATED_BY = "app/tools/generate_grafana_assets.py"

# Name of the dashboard variable that picks which turbine the panels show.
# Panels reference it as `$turbine_id` inside their prefixPath; the IoTDB
# datasource runs getTemplateSrv().replace() over every prefixPath entry,
# so the substitution happens before the query is built.
TURBINE_VARIABLE = "turbine_id"

# IoTDB's single-level path wildcard. Offered as one more entry in the same
# dropdown so the fleet-wide view the dashboard used to give is still one
# click away rather than being removed.
ALL_TURBINES_VALUE = "*"
ALL_TURBINES_LABEL = "All turbines"

# Channels each panel shows. Kept short deliberately: a fleet dashboard is
# for spotting which turbine needs attention, not for reading all 61
# channels at once -- that is the per-turbine drill-down's job.
RPM_MEASUREMENT = "TURBINE_SPEED_RPM"
TEMPERATURE_MEASUREMENTS = ["TT_109A", "TT_110A", "TT_110B", "TT_120", "RTD_219A", "RTD_220"]
# Pressure is split across two panels rather than one, because these five
# channels do not share a scale. PT_150A runs 118-169 kg/cm2 while the oil
# and lube channels sit at 2-3.4, so on a single linear axis the hydraulic
# trace pinned the others to the floor as a flat line. Grouping by
# magnitude gives each group a readable axis.
OIL_PRESSURE_MEASUREMENTS = ["PT_110A", "PT_120", "PT_160"]
LINE_PRESSURE_MEASUREMENTS = ["PT_109A", "PT_150A"]
PRESSURE_MEASUREMENTS = LINE_PRESSURE_MEASUREMENTS + OIL_PRESSURE_MEASUREMENTS
VIBRATION_MEASUREMENTS = ["XT_600", "XT_601", "ZT_600", "ZT_601"]
STATUS_MEASUREMENTS = [RPM_MEASUREMENT, "GB_TRQ", "HP_DEMAND", "ACT_POS_FB"]

# Per-category series colours. Each panel gets one hue family so a glance at
# a chart says which quantity it plots (blues = temperature, greens =
# pressure, oranges = vibration) without reading the title.
#
# Within a family the shades run light -> dark rather than cycling hues.
# Lightness is a second, hue-independent channel, so the series stay
# separable under red-green and blue-yellow colour blindness, where a
# rainbow palette would collapse. _series_style pairs that with a dashed
# line on alternating series, giving a shape cue that survives greyscale
# printing and any form of colour vision deficiency.
CATEGORY_PALETTES = {
    "temperature": [
        "super-light-blue",
        "light-blue",
        "blue",
        "dark-blue",
        "light-purple",
        "purple",
    ],
    "pressure": [
        "super-light-green",
        "light-green",
        "green",
        "dark-green",
        "semi-dark-green",
    ],
    "vibration": ["super-light-orange", "light-orange", "orange", "dark-orange"],
}

# Dash pattern applied to every other series, so neighbouring shades are
# told apart by line texture and not by colour alone.
DASH_LINE_STYLE = {"fill": "dash", "dash": [10, 6]}


def load_sensor_mappings() -> dict:
    return json.loads(SENSOR_MAPPINGS_PATH.read_text())["sensors"]


def _unit_of(mapping: dict) -> str:
    """The Grafana unit token to render a channel's values with.

    sensor_mappings.json carries `grafana_unit` for every channel Grafana
    has a built-in formatter for. Where it has none the file stores the
    literal "none", which would print a bare number -- the reason the
    status tiles read "6.83" with no hint that it means torque. Those fall
    back to Grafana's `suffix:` custom-unit form so the engineering unit
    from the same mapping is appended instead: "6.83 kN.m".
    """
    grafana_unit = mapping["grafana_unit"]
    if grafana_unit != "none":
        return grafana_unit
    return f"suffix:{mapping['unit']}"


def _decimals_of(mapping: dict) -> int:
    """How many decimals a channel deserves.

    Driven by magnitude: a five-digit RPM reading needs no fractional part
    (and ".0" only lengthens a number that must fit in a tile), while a
    torque of 6.83 kN.m would lose all its resolution rounded to "7".
    """
    return 0 if abs(mapping["normal_range"]["max"]) >= 1000 else 2


def _threshold_steps(mapping: dict) -> dict:
    """Green below the channel's warning point, orange to critical, red above.

    Taken from the same `thresholds` block the anomaly detector uses, so a
    tile turns orange exactly when the detector would call the reading a
    warning -- the dashboard cannot drift from the alerting logic.
    """
    return {
        "mode": "absolute",
        "steps": [
            {"color": "green", "value": None},
            {"color": "orange", "value": round(mapping["thresholds"]["warning"], 3)},
            {"color": "red", "value": round(mapping["thresholds"]["critical"], 3)},
        ],
    }


def _field_matcher(turbine_id: str, measurement: str) -> dict:
    """Match a field whether or not the query wrapped it in an aggregate.

    The IoTDB datasource names each series by its full path, so a raw
    measurement query yields
    `root.digitaltwin.<customer>.<site>.<turbine>.<measurement>` while an
    aggregate yields `last_value(<that same path>)`. Anchoring on the
    measurement alone with `$` matched only the first form, so every
    override on the aggregate-based status panel -- display name AND unit
    -- was silently dropped and the tiles fell back to printing the raw
    query text. The optional trailing paren admits both forms.
    """
    return {"id": "byRegexp", "options": f".*{turbine_id}\\.{measurement}\\)?$"}


def _rename_overrides(
    measurements: list[str],
    mappings: dict,
    turbine_ids: list[str],
    *,
    with_thresholds: bool = False,
    palette: list[str] | None = None,
) -> list:
    """Grafana field overrides that swap the raw series name for a human one.

    One override per (turbine, measurement) pair renames the field to
    "turbine01 - Gearbox Bearing Temp A" and applies that channel's unit
    and decimal precision. `with_thresholds` adds the green/orange/red
    scale for panels that colour by value; `palette` assigns the panel's
    hue family and dash pattern.
    """
    overrides = []
    for turbine_id in turbine_ids:
        for index, measurement in enumerate(measurements):
            mapping = mappings.get(measurement)
            if mapping is None:
                raise KeyError(f"{measurement} missing from sensor_mappings.json")
            properties = [
                {
                    "id": "displayName",
                    "value": f"{turbine_id} - {mapping['display_name']}",
                },
                {"id": "unit", "value": _unit_of(mapping)},
                {"id": "decimals", "value": _decimals_of(mapping)},
            ]
            if with_thresholds:
                properties.append({"id": "thresholds", "value": _threshold_steps(mapping)})
            if palette:
                properties.extend(_series_style(index, palette))
            overrides.append(
                {"matcher": _field_matcher(turbine_id, measurement), "properties": properties}
            )
    return overrides


def _series_style(index: int, palette: list[str]) -> list:
    """Fixed colour, plus a dash pattern on every other series.

    Two encodings for one distinction: viewers who see the hues get a
    colour, and viewers who do not still get solid-versus-dashed.
    """
    properties = [
        {
            "id": "color",
            "value": {"mode": "fixed", "fixedColor": palette[index % len(palette)]},
        }
    ]
    if index % 2 == 1:
        properties.append({"id": "custom.lineStyle", "value": DASH_LINE_STYLE})
    return properties


def _site_prefixes(customer: Customer) -> list[str]:
    """The `root.digitaltwin.<customer>.<site>` prefix of each site this
    customer owns, in declaration order and de-duplicated.

    Derived by trimming the turbine segment off a device_path rather than
    re-spelling the path format, so fleet.py stays the only place that
    knows how a device path is built.
    """
    prefixes = (t.device_path.rsplit(".", 1)[0] for t in customer.turbines)
    return list(dict.fromkeys(prefixes))


def _target(customer: Customer, expressions: list[str], ref_id: str = "A") -> dict:
    """One query, scoped to this customer's sites and to the single turbine
    selected in the dropdown.

    The customer and site segments are baked in and only the leaf is
    templated, which is what keeps this the query-level half of tenant
    isolation. A user who hand-edits `var-turbine_id` in the URL can still
    only move within `root.digitaltwin.<their customer>.<their site>.*`;
    there is no value of the variable that reaches another tenant, because
    a prefix cannot be escaped from the right-hand end.
    """
    return {
        "refId": ref_id,
        "sqlType": "SQL: Full Customized",
        "expression": expressions,
        "prefixPath": [f"{prefix}.${TURBINE_VARIABLE}" for prefix in _site_prefixes(customer)],
        "condition": "",
    }


def _datasource_ref(customer: Customer) -> dict:
    return {"type": DATASOURCE_TYPE, "uid": customer.datasource_uid}


def _rpm_panel(customer: Customer, mappings: dict) -> dict:
    turbine_ids = [t.turbine_id for t in customer.turbines]
    rpm = mappings[RPM_MEASUREMENT]
    return {
        "id": 1,
        "title": f"Rotor Speed - ${TURBINE_VARIABLE}",
        "description": (
            "Last reported rotor speed. Green below the normal-operation "
            f"ceiling of {round(rpm['thresholds']['warning'])} rpm, red above the "
            f"overspeed limit of {round(rpm['thresholds']['critical'])} rpm."
        ),
        "type": "gauge",
        "gridPos": {"h": 6, "w": 6, "x": 0, "y": 0},
        "datasource": _datasource_ref(customer),
        "targets": [_target(customer, [f"last_value({RPM_MEASUREMENT})"])],
        "fieldConfig": {
            "defaults": {
                "unit": rpm["grafana_unit"],
                "decimals": 0,
                "min": 0,
                "max": round(rpm["absolute_range"]["max"]),
                "thresholds": _threshold_steps(rpm),
            },
            "overrides": _rename_overrides([RPM_MEASUREMENT], mappings, turbine_ids),
        },
        "options": {
            "showThresholdMarkers": True,
            # Off: Grafana draws these rotated and overlapping on a gauge
            # this size, which produced an illegible smear of digits at the
            # arc's end. The threshold values live in the panel description
            # instead.
            "showThresholdLabels": False,
            "text": {"titleSize": 14, "valueSize": 32},
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
    }


def _status_panel(customer: Customer, mappings: dict) -> dict:
    """The four headline operating numbers, as compact labelled tiles.

    Sized 16 columns wide rather than 12 so each of the four tiles gets
    roughly 300px on a 1080p screen: enough for the full channel name on
    one line instead of the clipped text the narrower layout produced.

    `valueSize` is pinned because a stat panel otherwise scales its number
    to fill the tile, which is what produced the 100px-tall digits. 34px
    stays legible across the room while leaving the name room to breathe.
    """
    turbine_ids = [t.turbine_id for t in customer.turbines]
    return {
        "id": 2,
        "title": f"Operating Status - ${TURBINE_VARIABLE}",
        "description": (
            "Latest value of the four headline operating channels. Each tile "
            "is green in normal range, orange past that channel's warning "
            "threshold and red past critical. Thresholds come from "
            "sensor_mappings.json, the same source the anomaly detector uses."
        ),
        "type": "stat",
        "gridPos": {"h": 6, "w": 18, "x": 6, "y": 0},
        "datasource": _datasource_ref(customer),
        "targets": [
            _target(customer, [f"last_value({m})" for m in STATUS_MEASUREMENTS])
        ],
        "options": {
            # "none", not "area": the query is last_value(), which returns a
            # single point per channel, so there is no series for a sparkline
            # to draw. Asking for one only reserved empty vertical space
            # under each number.
            "graphMode": "none",
            # "value" tints the number and leaves the tile background
            # neutral. "background" flooded all four tiles with saturated
            # colour, which read as an alarm state even when everything was
            # nominal and drowned out the text.
            "colorMode": "value",
            "textMode": "value_and_name",
            "justifyMode": "auto",
            "wideLayout": False,
            "text": {"titleSize": 14, "valueSize": 34},
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
        "fieldConfig": {
            "defaults": {"unit": "none"},
            # with_thresholds: each channel carries its own green/orange/red
            # scale, because a torque of 7.5 and an actuator position of 7.5
            # mean entirely different things.
            "overrides": _rename_overrides(
                STATUS_MEASUREMENTS, mappings, turbine_ids, with_thresholds=True
            ),
        },
    }


def _timeseries_panel(
    panel_id: int,
    title: str,
    measurements: list[str],
    unit: str,
    grid_pos: dict,
    customer: Customer,
    mappings: dict,
    *,
    category: str,
    axis_label: str,
    description: str = "",
) -> dict:
    """One trend chart for a family of channels.

    The legend sits below the plot rather than beside it. On the right it
    consumed close to half the panel width -- the Vibration chart gave more
    room to four legend rows than to the data -- and its columns still
    clipped. Underneath, the plot keeps the full width and the legend gets
    a readable table.
    """
    turbine_ids = [t.turbine_id for t in customer.turbines]
    return {
        "id": panel_id,
        "title": title,
        "description": description,
        "type": "timeseries",
        "gridPos": grid_pos,
        "datasource": _datasource_ref(customer),
        "targets": [_target(customer, measurements)],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {
                    "drawStyle": "line",
                    "lineWidth": 2,
                    # No fill. These channels sample about once a second and
                    # are noisy, so a filled area under a spiky trace became
                    # a solid block of colour that hid every other series on
                    # the panel.
                    "fillOpacity": 0,
                    # These channels sample about once a second, so markers
                    # would merge into a solid band and hide the line.
                    "showPoints": "never",
                    "pointSize": 3,
                    "axisLabel": axis_label,
                    "axisPlacement": "left",
                    # Softens the y-axis onto the operating band while
                    # letting a genuine excursion push the axis out, so a
                    # single spike no longer flattens the whole trace the
                    # way it did on the Vibration chart.
                    "axisSoftMin": _soft_min(measurements, mappings),
                    "axisSoftMax": _soft_max(measurements, mappings),
                    "spanNulls": True,
                },
            },
            "overrides": _rename_overrides(
                measurements,
                mappings,
                turbine_ids,
                palette=CATEGORY_PALETTES[category],
            ),
        },
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "bottom",
                "calcs": ["lastNotNull", "min", "max"],
                "sortBy": "Last *",
                "sortDesc": True,
            },
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def _soft_min(measurements: list[str], mappings: dict) -> float:
    return round(min(mappings[m]["normal_range"]["min"] for m in measurements), 2)


def _soft_max(measurements: list[str], mappings: dict) -> float:
    return round(max(mappings[m]["thresholds"]["critical"] for m in measurements), 2)


def _turbine_variable(customer: Customer) -> dict:
    """Dropdown that selects which turbine every panel shows.

    Single-select on purpose. Grafana renders a multi-value variable as
    `{turbine01,turbine02}`, and IoTDB's path grammar has no brace
    alternation -- a multi-select would produce a query that silently
    matches nothing. Fleet-wide viewing is served by the explicit
    "All turbines" entry, which interpolates to IoTDB's `*` wildcard and
    reproduces exactly what this dashboard showed before the variable
    existed.
    """
    turbine_ids = [t.turbine_id for t in customer.turbines]
    default = turbine_ids[0]
    options = [(ALL_TURBINES_LABEL, ALL_TURBINES_VALUE)] + [(tid, tid) for tid in turbine_ids]
    return {
        "name": TURBINE_VARIABLE,
        "type": "custom",
        "label": "Turbine",
        "multi": False,
        "includeAll": False,
        # Grafana's custom-variable grammar: "label : value" pairs.
        "query": ", ".join(f"{label} : {value}" for label, value in options),
        "options": [
            {"text": label, "value": value, "selected": value == default}
            for label, value in options
        ],
        "current": {"text": default, "value": default, "selected": True},
    }


def build_dashboard(customer: Customer, mappings: dict) -> dict:
    turbine_ids = [t.turbine_id for t in customer.turbines]
    return {
        "title": f"{customer.display_name} Fleet",
        "uid": customer.dashboard_uid,
        "tags": ["fleet", customer.customer_id],
        "schemaVersion": 39,
        "version": 1,
        "editable": True,
        "timezone": "browser",
        "refresh": "5s",
        "time": {"from": "now-15m", "to": "now"},
        "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m", "15m", "1h"]},
        "description": (
            f"GENERATED by {GENERATED_BY} from app/config/fleet.json. "
            f"Scoped to {customer.customer_id} ({len(turbine_ids)} turbines). "
            f"Use the Turbine dropdown to pick one unit, or "
            f"'{ALL_TURBINES_LABEL}' for the whole fleet."
        ),
        "templating": {
            "list": [
                {
                    # Constant, not editable: letting a viewer retype
                    # CUSTOMER_ID would be a tenant-isolation hole. The
                    # variable exists so panel titles and future queries can
                    # reference it, not so it can be changed.
                    "name": "CUSTOMER_ID",
                    "type": "constant",
                    "label": "Customer",
                    "query": customer.customer_id,
                    "current": {"text": customer.customer_id, "value": customer.customer_id},
                    "hide": 2,
                },
                _turbine_variable(customer),
            ]
        },
        "panels": [
            _rpm_panel(customer, mappings),
            _status_panel(customer, mappings),
            # Two balanced rows of two. Height 13 leaves the bottom legend
            # room for every series: at height 9 with the legend on the
            # right, the six-channel Temperature table was clipped after
            # four rows, and at 12 it still lost the sixth.
            _timeseries_panel(
                3,
                "Gearbox & Generator Temperatures",
                TEMPERATURE_MEASUREMENTS,
                "celsius",
                {"h": 13, "w": 12, "x": 0, "y": 6},
                customer,
                mappings,
                category="temperature",
                axis_label="Temperature (°C)",
                description=(
                    "Gearbox bearing, gearbox oil and generator winding "
                    "temperatures. A bearing running steadily hotter than its "
                    "neighbours is an early wear signal."
                ),
            ),
            _timeseries_panel(
                4,
                "Gearbox Vibration",
                VIBRATION_MEASUREMENTS,
                "accMS2",
                {"h": 13, "w": 12, "x": 12, "y": 6},
                customer,
                mappings,
                category="vibration",
                axis_label="Acceleration (m/s²)",
                description=(
                    "Gearbox vibration on the X, Y and Z axes. Rising "
                    "broadband amplitude is the classic gearbox degradation "
                    "indicator."
                ),
            ),
            _timeseries_panel(
                5,
                "Oil & Lube Pressures",
                OIL_PRESSURE_MEASUREMENTS,
                # Was "none", which printed bare numbers and left the reader
                # to guess the scale. These three channels are all kg/cm2,
                # for which Grafana has no built-in formatter.
                "suffix:kg/cm2",
                {"h": 13, "w": 12, "x": 0, "y": 19},
                customer,
                mappings,
                category="pressure",
                axis_label="Pressure (kg/cm²)",
                description=(
                    "Gearbox oil, lube-oil header and inlet B pressures, "
                    "which all share a 2-3.5 kg/cm² operating band. A falling "
                    "lube-oil header pressure precedes most oil-system faults."
                ),
            ),
            _timeseries_panel(
                6,
                "Inlet & Hydraulic Pressures",
                LINE_PRESSURE_MEASUREMENTS,
                "suffix:kg/cm2",
                {"h": 13, "w": 12, "x": 12, "y": 19},
                customer,
                mappings,
                category="pressure",
                axis_label="Pressure",
                description=(
                    "The two high-range pressure channels, kept off the oil "
                    "panel because their operating bands (31 bar and "
                    "118-169 kg/cm²) would flatten it. Grafana gives each "
                    "unit its own axis."
                ),
            ),
        ],
    }


def main() -> int:
    fleet = load_fleet()
    mappings = load_sensor_mappings()

    for customer in fleet.customers:
        # Each org's provider reads its own subdirectory; this isolation prevents
        # cross-tenant access through file provisioning (setup_grafana_orgs.py
        # imports dashboards via API, not file provisioning).
        target_dir = DASHBOARD_JSON_DIR / customer.customer_id
        target_dir.mkdir(parents=True, exist_ok=True)
        dashboard = build_dashboard(customer, mappings)
        (target_dir / f"{customer.customer_id}.json").write_text(
            json.dumps(dashboard, indent=2) + "\n"
        )
        print(
            f"{customer.customer_id}: dashboard with {len(dashboard['panels'])} panels, "
            f"{len(customer.turbines)} turbines, org {customer.grafana_org_id}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
