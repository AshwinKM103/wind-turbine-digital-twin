# Digital Twin Roadmap & Implementation Tracks

This directory tracks the active work, architecture decisions, and roadmap for the Wind Turbine Digital Twin across four independent technical tracks.

## Tracks

### [3D Turbine Model](3d-turbine/STATUS.md)
GLB reconstruction, Babylon.js interactive 3D viewer widget, sensor-to-mesh mapping, isolation modes, particle systems, and automated browser regression tests. Also contains the reconstruction [blueprint](3d-turbine/blueprint.md), [research report](3d-turbine/research-report.pdf), and [rig specification](3d-turbine/rig-specification.pdf).

### [2D SCADA Mimic Dashboard](2d-scada/STATUS.md)
ThingsBoard SVG mimic widget with live animation, 12 KPI cards, ECharts vibration orbit plot widget, dynamic threshold configurator, headroom monitor, and dashboard deployment scripts.

### [AI Copilot Backend](ai-copilot/STATUS.md)
Thin chat widget integrated with a deterministic FastAPI AI orchestration backend, safety guardrails (max tool calls, no RPC physical control), ThingsBoard read-only tool layer, anomaly scoring service, and the original [architecture plan](ai-copilot/architecture-plan.md).

### [DAQ & Telemetry Pipeline](daq-pipeline/STATUS.md)
End-to-end data pipeline including the multi-state 61-channel synthetic generator, Kafka broker, IoTDB consumer with Tablet batch writing, Kafka-to-MQTT ThingsBoard bridge, historical NI DAQ 1 Hz replay server, and shift PDF report generation.

---

## Keeping Track Status Current

Each track directory contains exactly one `STATUS.md` organized into four concise sections:
- `## Done`: Flat facts with relative file paths providing proof.
- `## In Progress`: Actively ongoing work.
- `## Pending / Not Started`: Planned work and known blockers.
- `## Open Decisions`: Architectural or design questions requiring resolution.

When completing work or changing architecture within a track, update its corresponding `STATUS.md`. Keep updates factual, concise, and backed by code references without narrative padding.

## Historical Archive

The `_archive/` directory contains superseded planning and audit documents kept for reference and historical context:
- `IMPLEMENTATION_PLAN_2026-09-15.md`
- `VERIFICATION_REPORT_2026-09-15.md`
- `override.md`

Files in `_archive/` are historical records and should not be treated as current project status.
