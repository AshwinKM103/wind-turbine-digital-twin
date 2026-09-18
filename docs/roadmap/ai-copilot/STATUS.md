# AI Copilot Status

## Done
- Thin dashboard-aware widget deployed via [deploy_copilot_widget.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/tools/deploy_copilot_widget.py) connected to external FastAPI service in [main.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/main.py).
- Deterministic read-only tool layer implemented in [tb_tools.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/tb_tools.py): `get_latest_telemetry`, `get_telemetry_range`, `list_alarms`, `get_alarm_details`, `get_sensor_catalog`, `get_operating_limits`, and `build_chart_spec`.
- Anomaly service implemented in [anomaly_service.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/anomaly_service.py) supporting IsolationForest scoring and deterministic threshold analytics.
- Dashboard action generator implemented in [dashboard_actions.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/dashboard_actions.py) with strict allowlist validation (`DASHBOARD_ALLOWLIST`) and component navigation payloads.
- Safety boundaries enforced in [orchestrator.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/orchestrator.py): `MAX_TOOL_CALLS_PER_TURN = 3`, zero physical-control or RPC tools registered, and exception redaction across streamed responses.
- Unit test suite implemented and passing in [tests/](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/tests/):
  - [test_tb_tools.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/tests/test_tb_tools.py)
  - [test_dashboard_actions.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/tests/test_dashboard_actions.py)
  - [test_orchestrator_safety.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/tests/test_orchestrator_safety.py)
  - [test_model_gateway.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/tests/test_model_gateway.py)
  - [test_anomaly_service.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/tests/test_anomaly_service.py)
  - [test_main_contract.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/tests/test_main_contract.py)

## In Progress
- Dependency environment alignment: `scikit-learn==1.5.1` declared in [requirements.txt](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/requirements.txt) pending installation and verification in the target deployment container/runtime.

## Pending / Not Started
- LangGraph state machine migration: transition from current deterministic loop in [orchestrator.py](file:///home/ashwinkm/Digital%20Twins/Apache_IOTDB/app/copilot_backend/orchestrator.py) to explicit LangGraph graph state nodes.
- MCP exposure boundary: exposing selected internal tools through ThingsBoard MCP server wrappers for external tool consumers.
- Hybrid RAG document ingestion pipeline for technical manuals and operating procedures.

## Open Decisions
- State machine engine: whether to adopt LangGraph or retain the lightweight deterministic orchestrator loop to avoid external framework runtime overhead.
- MCP boundary scope: which subset of `tb_tools` and analytics endpoints should be exposed via MCP vs kept private to FastAPI internal routes.
