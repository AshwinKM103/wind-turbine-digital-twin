"""ECharts and chart widget builders for ThingsBoard dashboards.

Provides helper constructors to generate schema-compliant ThingsBoard chart definitions,
including multi-axis timeseries line charts and 2D shaft orbit plots.

Exported Functions:
    make_axis: Generates an ECharts Y-axis specification dictionary.
    make_orbit: Generates an orbit plot widget descriptor.
    build_chart_widget: Assembles a complete multi-series time_series_chart widget definition.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def make_axis(
    axis_id: str,
    label: str,
    units: str,
    decimals: int,
    order: int,
    position: str = "left",
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
    split_lines: bool = False,
) -> dict[str, Any]:
    """Builds a schema-compliant ECharts Y-Axis definition for system.time_series_chart.

    Args:
        axis_id: Unique string identifier for the axis (e.g. 'rpm', 'mw').
        label: Axis title label displayed along the axis line.
        units: Engineering units string appended to axis values (e.g. 'RPM', '°C').
        decimals: Decimal precision formatting for axis tick numbers.
        order: Visual placement order of the axis.
        position: Axis placement side ('left' or 'right').
        min_val: Optional fixed minimum axis boundary.
        max_val: Optional fixed maximum axis boundary.
        split_lines: Whether to render horizontal grid split lines.

    Returns:
        Dictionary conforming to ThingsBoard ECharts Y-axis schema.
    """
    axis: dict[str, Any] = {
        "id": axis_id,
        "label": label,
        "units": units,
        "decimals": decimals,
        "order": order,
        "position": position,
        "show": True,
        "labelFont": {
            "family": "Roboto, sans-serif",
            "size": 11,
            "sizeUnit": "px",
            "style": "normal",
            "weight": "700",
            "lineHeight": "1",
        },
        "labelColor": "#94a3b8",
        "showTickLabels": True,
        "tickLabelFont": {
            "family": "Roboto, monospace",
            "size": 10,
            "sizeUnit": "px",
            "style": "normal",
            "weight": "500",
            "lineHeight": "1",
        },
        "tickLabelColor": "#cbd5e1",
        "showTicks": True,
        "ticksColor": "rgba(255, 255, 255, 0.25)",
        "showLine": True,
        "lineColor": "rgba(255, 255, 255, 0.25)",
        "showSplitLines": split_lines,
        "splitLinesColor": "rgba(255, 255, 255, 0.08)",
    }
    if min_val is not None:
        axis["min"] = min_val
    if max_val is not None:
        axis["max"] = max_val
    return axis


def make_orbit(
    title: str,
    x_key: str,
    y_key: str,
    alias_device_id: str,
    subtitle: str = "",
    size_x: int = 12,
    size_y: int = 11,
) -> dict[str, Any]:
    """Builds an orbit plot widget definition for 2D shaft orbit visualization.

    Args:
        title: Main title of the orbit widget.
        x_key: Telemetry timeseries key for X displacement (e.g. 'XT_600').
        y_key: Telemetry timeseries key for Y displacement (e.g. 'YT_600').
        alias_device_id: Entity alias identifier linking the datasource to turbine device.
        subtitle: Optional subtitle string.
        size_x: Grid column span on dashboard layout.
        size_y: Grid row span on dashboard layout.

    Returns:
        ThingsBoard widget dictionary for tenant.turbine_orbit_plot.
    """
    return {
        "typeFullFqn": "tenant.turbine_orbit_plot",
        "type": "latest",
        "title": title,
        "sizeX": size_x,
        "sizeY": size_y,
        "config": {
            "datasources": [
                {
                    "type": "entity",
                    "entityAliasId": alias_device_id,
                    "dataKeys": [
                        {"name": x_key, "type": "timeseries", "label": "X"},
                        {"name": y_key, "type": "timeseries", "label": "Y"},
                    ],
                }
            ],
            "settings": {"subtitle": subtitle},
            "showTitle": False,
            "backgroundColor": "transparent",
            "padding": "0px",
        },
    }


def build_chart_widget(
    title: str,
    keys_and_axes: list[tuple[str, str, str, str, str, int]],
    y_axes: dict[str, dict[str, Any]],
    alias_device_id: str,
    base_default_config: Optional[dict[str, Any]] = None,
    size_x: int = 12,
    size_y: int = 11,
) -> dict[str, Any]:
    """Builds a time_series_chart widget definition with multiple series and yAxes.

    Args:
        title: Title of the chart widget.
        keys_and_axes: List of 6-tuples: (telemetry_name, label, color_hex, y_axis_id, units, decimals).
        y_axes: Dictionary mapping yAxisId strings to make_axis definitions.
        alias_device_id: Entity alias identifier for telemetry datasource.
        base_default_config: Optional base configuration dictionary to merge into.
        size_x: Grid column span on dashboard.
        size_y: Grid row span on dashboard.

    Returns:
        ThingsBoard widget definition for system.time_series_chart.
    """
    chart_cfg: dict[str, Any] = json.loads(json.dumps(base_default_config or {}))
    chart_cfg["showTitle"] = True
    chart_cfg["title"] = title
    chart_cfg["titleColor"] = "#f8fafc"
    chart_cfg["titleStyle"] = {
        "color": "#f8fafc",
        "fontSize": "15px",
        "fontWeight": "600",
        "fontFamily": "Roboto, sans-serif",
    }
    chart_cfg["backgroundColor"] = "#0f172a"
    chart_cfg["color"] = "#f8fafc"
    chart_cfg["padding"] = "8px"
    chart_cfg["widgetStyle"] = {
        "color": "#f8fafc",
    }
    chart_cfg["widgetCss"] = (
        ".mat-subtitle-1.title, .title, .tb-widget-title { color: #f8fafc !important; font-weight: 600 !important; }\n"
        ".tb-time-series-chart-legend-type-label { color: #94a3b8 !important; font-weight: 600 !important; }\n"
        ".tb-time-series-chart-legend-value { color: #f1f5f9 !important; font-weight: 600 !important; }\n"
    )
    chart_cfg["datasources"] = [
        {
            "type": "entity",
            "entityAliasId": alias_device_id,
            "dataKeys": [
                {
                    "name": name,
                    "type": "timeseries",
                    "label": label,
                    "color": color,
                    "units": units,
                    "decimals": decimals,
                    "settings": {
                        "yAxisId": axis_id,
                        "type": "line",
                        "smooth": True,
                        "showSymbol": False,
                    },
                }
                for name, label, color, axis_id, units, decimals in keys_and_axes
            ],
        }
    ]
    if "settings" not in chart_cfg:
        chart_cfg["settings"] = {}
    chart_cfg["settings"]["yAxes"] = y_axes
    chart_cfg["settings"]["showLegend"] = True
    chart_cfg["settings"]["legendLabelColor"] = "#f8fafc"
    chart_cfg["settings"]["legendValueColor"] = "#f1f5f9"
    chart_cfg["settings"]["legendColumnTitleColor"] = "#94a3b8"
    chart_cfg["settings"]["legendLabelFont"] = {
        "family": "Roboto, sans-serif",
        "size": 11,
        "sizeUnit": "px",
        "style": "normal",
        "weight": "500",
        "lineHeight": "1",
    }
    chart_cfg["settings"]["legendColumnTitleFont"] = {
        "family": "Roboto, sans-serif",
        "size": 11,
        "sizeUnit": "px",
        "style": "normal",
        "weight": "700",
        "lineHeight": "1",
    }
    chart_cfg["settings"]["legendValueFont"] = {
        "family": "Roboto, monospace",
        "size": 11,
        "sizeUnit": "px",
        "style": "normal",
        "weight": "600",
        "lineHeight": "1",
    }
    chart_cfg["settings"]["background"] = {
        "type": "color",
        "color": "#0f172a",
        "overlay": {"enabled": False, "color": "rgba(15,23,42,0.72)", "blur": 3},
    }
    chart_cfg["settings"]["tooltipBackgroundColor"] = "rgba(15, 23, 42, 0.95)"
    chart_cfg["settings"]["tooltipValueColor"] = "#f8fafc"
    chart_cfg["settings"]["tooltipDateColor"] = "#94a3b8"
    chart_cfg["settings"]["xAxis"] = {
        "show": True,
        "label": "",
        "labelFont": {"family": "Roboto", "size": 11, "sizeUnit": "px", "style": "normal", "weight": "600", "lineHeight": "1"},
        "labelColor": "#94a3b8",
        "position": "bottom",
        "showTickLabels": True,
        "tickLabelFont": {"family": "Roboto", "size": 10, "sizeUnit": "px", "style": "normal", "weight": "400", "lineHeight": "1"},
        "tickLabelColor": "#94a3b8",
        "ticksFormat": {},
        "showTicks": True,
        "ticksColor": "rgba(255, 255, 255, 0.2)",
        "showLine": True,
        "lineColor": "rgba(255, 255, 255, 0.2)",
        "showSplitLines": True,
        "splitLinesColor": "rgba(255, 255, 255, 0.08)",
    }
    chart_cfg["settings"]["legendConfig"] = {
        "direction": "row",
        "position": "top",
        "sortDataKeys": False,
        "showMin": False,
        "showMax": True,
        "showAvg": True,
        "showTotal": False,
        "showLatest": True,
    }
    chart_cfg["settings"]["dataZoom"] = True
    return {
        "typeFullFqn": "system.time_series_chart",
        "type": "timeseries",
        "title": title,
        "sizeX": size_x,
        "sizeY": size_y,
        "config": chart_cfg,
    }

