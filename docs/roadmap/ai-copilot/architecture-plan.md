# Production Turbine Copilot for ThingsBoard

The strongest architecture is a **thin, dashboard-aware ThingsBoard chat widget connected to a dedicated AI orchestration service**. ThingsBoard should remain the system of record for entities, telemetry, alarms and visualization, while the AI backend handles tool orchestration, RAG, model routing, authorization and access to separate anomaly, forecasting and predictive-maintenance services.

No mature, production-ready, drop-in ThingsBoard conversational copilot was found. The most reusable ThingsBoard-specific implementation is [conversational-analytics](https://github.com/sambertibus99/conversational-analytics), complemented by the official [ThingsBoard MCP server](https://github.com/thingsboard/thingsboard-mcp); neither alone supplies the complete dashboard-aware, safety-governed turbine solution.

**Research cutoff:** September 15, 2026.

## Executive findings

1. **Do not run the agent inside a ThingsBoard widget.** Use the widget as a presentation and context-integration layer; keep credentials, model access, RAG, authorization and tool execution in an external backend.
2. **Use deterministic tools rather than asking the LLM to interpret raw telemetry.** Services should calculate ranges, aggregates, correlations, trends, limit violations and ML results; the LLM should select tools and explain returned evidence.
3. **Use LangGraph or an equivalent explicit state machine.** A free-form multi-agent swarm is harder to secure, test and predict.
4. **Support MCP at the integration boundary, not as the core application architecture.** Implement a typed internal tool layer first and expose selected tools through MCP where interoperability is valuable.
5. **Keep dashboard actions separate from equipment actions.** Navigation, highlighting and ephemeral chart creation are UI operations; RPC and control are physical-system operations and need a separate approval and interlock domain.
6. **Launch with no physical-control tools registered.** Future control should follow proposal → validation → human approval → external execution, with the safety system remaining authoritative.
7. **Use hybrid RAG with metadata and permission filters.** Engineering documents, structured asset metadata, telemetry and analytics outputs require different retrieval methods.
8. **Treat current dashboard context as signed application state**, not conversational inference. The widget should explicitly send turbine, component, selected sensors, time window and dashboard state.

---

## Integration feasibility

| Capability | Classification | Recommended implementation |
| --- | --- | --- |
| Chat panel in a dashboard | **Native framework, custom implementation** | ThingsBoard custom widget with an external chat API |
| Live telemetry | **Native / proven** | Existing widget subscriptions for display; telemetry WebSocket or REST through the backend for AI tools |
| Historical telemetry | **Native / proven** | ThingsBoard timeseries REST API with aggregation and bounded time ranges |
| Current entity | **Native / proven** | Resolve widget datasource and entity alias inside the widget |
| Dashboard state | **Native / proven** | Read state parameters and state-controller information from widget context |
| Component selection | **Straightforward custom development** | Maintain selected component/entity in dashboard state or shared widget context |
| Alarms | **Native / proven** | Alarm REST APIs and existing dashboard subscriptions |
| Attributes and metadata | **Native / proven** | Attribute and entity-relation APIs |
| Rule Engine connection | **Native / proven** | REST/API-call nodes, message queues or integration nodes to publish analytics results |
| Chat response streaming | **Straightforward custom development** | SSE or WebSocket from the AI service to the widget |
| Markdown and citations | **Straightforward custom development** | Sanitize Markdown; render citations as controlled links |
| Charts inside chat | **Straightforward custom development** | Return a restricted chart specification and render it client-side |
| Navigate to another view | **Straightforward custom development** | Return a typed UI action; widget invokes the dashboard state controller |
| Select or highlight a sensor | **Straightforward custom development** | Dashboard event/context service or selected-entity state parameter |
| Dynamically reconfigure existing widgets | **Possible but complex** | State changes, alias changes or shared context; avoid directly modifying widget internals |
| Create permanent dashboard widgets | **Possible but complex** | Administrative API, dashboard JSON mutation and version control; not suitable as an ordinary chat action |
| iframe chat application | **Straightforward** | Embed a separately deployed UI with signed context bootstrap |
| React/Vue web component | **Possible but complex** | Bundle inside a custom widget or load a tightly controlled static application |
| Platform-wide floating assistant | **Possible but fragile** | Requires shell customization or PE-supported custom navigation; dashboard widgets are safer |
| General LLM/RAG backend | **Better external** | Dedicated AI service |
| Document ingestion/vector indexing | **Better external** | Independent RAG ingestion pipeline |
| Time-series ML | **Better external** | Dedicated versioned analytics services |
| Physical command execution | **Better external and separately governed** | Control gateway, approval workflow and PLC/SCADA interlocks |
| Long-running agent workflows | **Better external** | Durable orchestration and job infrastructure |

ThingsBoard’s custom-widget framework, entity aliases, dashboard states, telemetry interfaces, alarms and Rule Engine are the relevant native building blocks; they are documented under the current [widget development](https://thingsboard.io/docs/user-guide/contribution/widgets-development/), [dashboard](https://thingsboard.io/docs/user-guide/dashboards/), [telemetry](https://thingsboard.io/docs/user-guide/telemetry/), [alarm](https://thingsboard.io/docs/user-guide/alarms/) and [Rule Engine](https://thingsboard.io/docs/user-guide/rule-engine-2-0/overview/) documentation.

### Native AI status

The official [thingsboard/thingsboard-mcp](https://github.com/thingsboard/thingsboard-mcp) repository is the clearest ThingsBoard-owned AI integration found. Its repository contains a Java/Maven implementation, Dockerfile, security policy and conventional server structure, but it should be treated as an external AI-access interface rather than evidence of a complete native dashboard chat experience.

A production deployment should therefore assume that the **chat UI, conversational state, RAG and orchestration remain custom components**, even when the official MCP server supplies some ThingsBoard-facing tools.

### Community versus PE

Core dashboards, custom widgets, entity aliases, telemetry, alarms, REST access, WebSocket access, device RPC and Rule Engine capabilities are available in the general ThingsBoard platform. Consequently, the proposed copilot is technically achievable with Community Edition.

Professional Edition is more attractive where the deployment needs richer enterprise integrations, white-labeling, custom navigation, reporting, operational support or advanced access-management features. Exact CE/PE boundaries should be verified against the deployed ThingsBoard release because licensing and feature packaging evolve independently of the custom AI architecture.

---

## Existing implementations

### Ranked ThingsBoard projects

| Rank | Project | Architecture and value | License/activity | Reuse assessment |
| --- | --- | --- | --- | --- |
| 1 | [sambertibus99/conversational-analytics](https://github.com/sambertibus99/conversational-analytics) | Chainlit UI → LangGraph supervisor/data/statistics/visualization agents → custom ThingsBoard MCP → REST telemetry; supports multi-turn questions, dynamic charts, statistical tools and large-result storage | README describes an academic thesis rather than a verified conventional open-source license; active commits were observed through March 2026 | **Best ThingsBoard-specific reference.** Reuse the MCP client, time parsing, data-agent patterns, state persistence, correlation logic, chart protocol, tests and failure handling. Replace fixed credentials, robot-specific telemetry map, Chainlit-only UI and unrestricted agent planning |
| 2 | [thingsboard/thingsboard-mcp](https://github.com/thingsboard/thingsboard-mcp) | Official standalone MCP integration implemented in Java/Maven | Official repository with Docker and security assets; inspect its current license and tool definitions before redistribution | **Best official integration base.** Wrap or extend only the required read APIs; benchmark authorization, pagination and tenant isolation before production |
| 3 | [gigwegbe/function-calling-for-sensors-at-the-edge](https://github.com/gigwegbe/function-calling-for-sensors-at-the-edge) | ThingsBoard REST access combined with LangGraph supervisors, extraction agents, visualization agents and Chainlit experiments | Research-oriented repository with several preliminary and notebook implementations | Useful for function-calling and visualization examples, but requires consolidation, secret removal, tests and production authorization |
| 4 | [sambertibus99/conversational-analytics – ThingsBoard MCP design](https://github.com/sambertibus99/conversational-analytics/blob/master/docs/design/thingsboard_mcp_server.md) | Documents eight ThingsBoard tools, asynchronous REST access and file-backed handling of results that exceed practical LLM context limits | Part of the active thesis repository | Strong blueprint for bounded telemetry retrieval and avoiding raw timeseries in the prompt |
| 5 | Generic ThingsBoard custom widget | Widget context → AI backend → typed UI actions | Governed by the ThingsBoard deployment’s license | This is the necessary integration shell even when another repository supplies the backend |

The first-ranked repository implements tools for devices, device details, telemetry keys, latest telemetry, historical telemetry, data availability and attributes. It also documents retry/backoff, cycle limits, graceful errors, multi-turn state and a DuckDB session store; recent commits report several hundred passing tests and fixes for timestamp alignment, dataset leakage and raw-versus-aggregated query selection. [conversational-analytics](https://github.com/sambertibus99/conversational-analytics)

Its major weakness is that the ThingsBoard device identifier and tenant credentials are configured centrally. A turbine deployment must replace this with per-user authorization, tenant-scoped entity resolution and an asset/component semantic layer.

### Industrial copilot projects

| Project | Relevant implementation | License/maturity | Turbine reuse |
| --- | --- | --- | --- |
| [Somya170/shopfloor-copilot](https://github.com/Somya170/shopfloor-copilot) | Next.js, Flask/[Socket.IO](http://Socket.IO), TimescaleDB, Redis, Qdrant, LangChain, Groq/Ollama, JWT/RBAC, reports and live telemetry | MIT; updated September 2026; README says real hardware, Dockerization and offline mode are still roadmap items | Reuse chat UI, RAG composition, WebSocket patterns, report generation and service decomposition; replace simulator and TimescaleDB path with ThingsBoard adapters |
| [SparshM8/DocOps](https://github.com/SparshM8/DocOps) | Next.js → Node gateway → FastAPI; LangGraph/Gemini RAG, Qdrant, WebSocket telemetry, QR asset context and browser WebGPU inference | MVP; updated August 2026; README openly identifies simulated telemetry, local user storage and scalability gaps; license not verified | Valuable for asset-scanning context, document ingestion, air-gapped packaging and offline UX; substantial security and persistence work required |
| [Farhan-0000/Engineering-Failure-Copilot](https://github.com/Farhan-0000/Engineering-Failure-Copilot) | FastAPI, Streamlit, Ollama, LangChain, Plotly and document/telemetry report generation | MIT; July 2026; README says FAISS retrieval, memory and RBAC remain incomplete | Good local demonstration and report pipeline, but not a production base |
| [orcunku/AgenticWindFarm](https://github.com/orcunku/AgenticWindFarm) | Wind-turbine telemetry, WebSockets, ML fault filtering, diagnostic RAG, MCP-style tool discovery and maintenance routing | Created and updated August 2026; very early project and no verified license | Exact domain fit, useful vocabulary and workflow reference; validate every claimed capability and isolate its ML components |
| [zavora-ai/mcp-scada](https://github.com/zavora-ai/mcp-scada) | Rust MCP server with assets, tags, historian, alarms, work orders, audit, dry-run interlocks and approval-gated commands | Apache-2.0; reference/in-memory implementation; updated August 2026 | **Best safety-pattern reference**, not a ThingsBoard adapter. Reuse risk classifications, approval binding, expiration, audit and fail-closed semantics |
| [mongodb-industry-solutions/manufacturing-car-manual-RAG](https://github.com/mongodb-industry-solutions/manufacturing-car-manual-RAG) | Multiple retrieval approaches over complex technical manuals | Industry-solution example; license must be checked before reuse \[[github](https://github.com/mongodb-industry-solutions/manufacturing-car-manual-RAG)\] | Useful benchmark for evaluating retrieval strategies on manuals rather than for telemetry integration |
| [operational-ai-copilot](https://github.com/sylvainbonnot/operational-ai-copilot) | RAG over manuals and maintenance tickets with intent-driven industrial incident workflows | Small demonstration repository | Useful incident-analysis taxonomy; insufficient evidence for production maturity |
| [a7madgamaltantawy/ai-telemetry-copilot](https://github.com/a7madgamaltantawy/ai-telemetry-copilot) | Sensor anomaly results plus natural-language RAG explanations | Demonstration-level | Useful for answer composition; anomaly logic must remain outside the conversational agent |

`shopfloor-copilot` is the best non-ThingsBoard full-stack example because it explicitly combines live telemetry, document retrieval, model selection, RBAC, reports and WebSocket updates. Its README also separates TimescaleDB telemetry, Qdrant knowledge, Redis messaging and Groq/Ollama inference, a useful pattern even though it is not ThingsBoard-native. [shopfloor-copilot](https://github.com/Somya170/shopfloor-copilot)

`mcp-scada` is particularly relevant to future control. It distinguishes read-only points from writable setpoints, performs a dry-run before commands, checks lockout/tagout, fault state, critical alarms and engineering ranges, binds approval to exact arguments, expires approval state and records rejected as well as executed commands. It explicitly warns that software gates are not substitutes for PLC/RTU and hardware protection. [mcp-scada](https://github.com/zavora-ai/mcp-scada)

### Licensing caution

Projects without a clear OSI license grant should be treated as **reference-only**, even if their source is publicly visible. In particular, the thesis repository and several 2026 demonstration projects require explicit license verification before code is incorporated into a commercial or internal product.

---

## Recommended architecture

```
flowchart LR
    OP[Operator] --> TBUI[ThingsBoard Dashboard]
    TBUI --> CW[Copilot Custom Widget]

    CW -->|Signed context + question| GW[AI Gateway]
    GW --> AUTH[Identity and Policy]
    AUTH --> ORCH[LangGraph Orchestrator]

    ORCH --> ET[Entity and Sensor Catalog]
    ORCH --> TT[Telemetry Tools]
    ORCH --> AT[Alarm and Event Tools]
    ORCH --> RAG[Engineering RAG]
    ORCH --> AN[Anomaly Results Service]
    ORCH --> FC[Forecast Results Service]
    ORCH --> PM[Predictive Maintenance Service]
    ORCH --> UIA[Dashboard Action Planner]

    ET --> TB[ThingsBoard APIs]
    TT --> TB
    AT --> TB

    RAG --> VS[(Vector and Keyword Index)]
    RAG --> DOC[(Controlled Documents)]
    RAG --> META[(Asset/AAS Metadata)]

    AN --> TS[(Analytics Store)]
    FC --> TS
    PM --> TS

    ORCH --> MR[Model Router]
    MR --> CLOUD[OpenAI / Anthropic / Gemini]
    MR --> LOCAL[vLLM / Ollama / Other OpenAI-compatible Server]

    UIA -->|Typed UI actions| CW
    CW -->|Validated navigation/highlight/chart| TBUI
```

### Architectural modification

The user’s proposed chain is directionally correct, but “LLM → tools” should not imply that the model directly owns data access. The safer sequence is:

**Authenticated request → policy-filtered tool registry → deterministic orchestrator → domain tools → model synthesis → output validator → client-side UI action handler.**

The LLM should never receive arbitrary API credentials or discover all tenant assets. Tools must receive an authorization context generated by the backend and enforce scope independently of the model’s arguments.

---

## Dashboard context

### Context envelope

The widget should produce an explicit context envelope on every turn:

```
{
  "schemaVersion": "1.0",
  "tenantId": "tenant-42",
  "userId": "operator-17",
  "roles": ["TURBINE_OPERATOR"],
  "dashboardId": "windfarm-ops",
  "dashboardState": "gearbox-detail",
  "stateParams": {
    "turbineId": "WTG-07",
    "componentId": "WTG-07/GEARBOX"
  },
  "selectedEntities": [
    {
      "entityType": "ASSET",
      "entityId": "...",
      "semanticId": "WTG-07/GEARBOX"
    }
  ],
  "selectedSensors": ["GBX_VIB_DE", "GBX_VIB_NDE"],
  "timeWindow": {
    "mode": "history",
    "startTs": 1789471800000,
    "endTs": 1789493400000,
    "timezone": "Asia/Kolkata"
  },
  "visibleTelemetryKeys": [
    "gearbox_vibration_rms",
    "gearbox_oil_temperature",
    "rotor_speed"
  ],
  "activeAlarmIds": ["alarm-123"],
  "capabilities": [
    "navigate",
    "highlight",
    "render_ephemeral_chart"
  ],
  "conversationId": "...",
  "contextRevision": 31
}
```

The backend must not trust entity IDs merely because the browser supplied them. It must revalidate that the authenticated user can access each entity and normalize identifiers against ThingsBoard’s asset relations or an independent asset registry.

### Context lifecycle

1. The widget initializes and resolves its entity aliases.
2. It subscribes to dashboard-state and selection changes.
3. A compact context snapshot accompanies each chat turn.
4. The backend verifies and enriches the snapshot using ThingsBoard.
5. Follow-up questions inherit the prior validated context.
6. Any dashboard-state change increments `contextRevision`.
7. If the conversation refers to stale context, the assistant states that the view changed and refreshes the necessary evidence.

For “Why is vibration increasing?” the orchestrator should resolve the selected gearbox, map “vibration” to permitted sensors, determine the dashboard time window, retrieve an appropriate aggregate or trend summary, retrieve active alarms, request existing anomaly results and search relevant diagnostic material. The LLM should synthesize those results rather than calculate a diagnosis from visually sampled values.

---

## ThingsBoard tools

### Read-only server tools

| Tool | Purpose | Important constraints |
| --- | --- | --- |
| `resolve_dashboard_context` | Validate current turbine, component and state | Never accept an unverified entity from the browser |
| `list_component_sensors` | Discover telemetry keys through semantic metadata | Return engineering unit, sampling expectations and description |
| `get_latest_telemetry` | Retrieve current values | Include timestamp, quality and staleness |
| `get_telemetry_range` | Historical values | Require bounded range, key count, interval and maximum points |
| `get_telemetry_summary` | Min/max/mean/percentiles/slope | Compute outside the LLM |
| `compare_signals` | Align and compare PT111/PT112 | Define resampling and missing-data rules |
| `get_attributes` | Operating limits and static metadata | Distinguish configured limits from inferred norms |
| `get_entity_relations` | Traverse turbine/component/sensor hierarchy | Enforce maximum depth and result count |
| `list_alarms` | Current and historical alarms | Include lifecycle state and acknowledgement |
| `get_alarm_details` | Alarm definition and related telemetry | Separate observed facts from suggested causes |
| `get_analysis_results` | Retrieve anomaly/forecast/health results | Include model version and evidence window |
| `search_engineering_knowledge` | Search manuals and procedures | Apply asset, version, role and document-state filters |

### Dashboard tools

Dashboard tools should return **intent objects**, not manipulate ThingsBoard directly from the agent:

```
{
  "action": "OPEN_DASHBOARD_STATE",
  "dashboardId": "windfarm-ops",
  "stateId": "gearbox-detail",
  "params": {
    "turbineId": "WTG-07",
    "componentId": "GEARBOX"
  },
  "label": "Open gearbox view"
}
```

Recommended allowlisted actions are:

- `OPEN_DASHBOARD_STATE`
- `SELECT_ENTITY`
- `SELECT_SENSOR`
- `SET_TIME_WINDOW`
- `HIGHLIGHT_SENSOR`
- `SHOW_EPHEMERAL_CHART`
- `OPEN_ALARM`
- `OPEN_DOCUMENT_SECTION`
- `DOWNLOAD_ANALYSIS_REPORT`

The widget validates action type, entity scope, dashboard allowlist and parameter schema before presenting a button or applying a harmless action. Navigation may execute immediately; selection or time-window changes should normally be represented as visible UI actions so operators retain orientation.

### Example mappings

| User request | Tool sequence | UI result |
| --- | --- | --- |
| “Show turbine speed for the last six hours” | Resolve context → sensor lookup → historical telemetry | Ephemeral chart plus “Open full trend” action |
| “Compare PT111 and PT112” | Validate sensors → retrieve aligned data → deterministic comparison | Overlay chart, data-quality notes and summary |
| “Which sensors are outside normal range?” | Retrieve latest values → obtain configured limits → evaluate limits | Ranked list and highlight actions |
| “Open the gearbox view” | Resolve turbine → generate dashboard state action | Widget invokes approved navigation |
| “Why is gearbox vibration high?” | Telemetry summary → alarms → anomaly result → RAG retrieval | Evidence-backed explanation with uncertainty |
| “Create a visualization” | Query planner → bounded data query → chart-spec generator | Client renders declarative chart; no generated JavaScript |
| “Acknowledge this alarm” | Not included initially | Explain read-only restriction; optionally link to native alarm UI |

Persistent dashboard mutation should be an administrative workflow, not a general assistant tool. Most conversational visualizations should be temporary Vega-Lite, ECharts or Plotly-style specifications rendered in chat.

---

## Tool calling and MCP

### Recommended pattern

Use three layers:

1. **Domain services:** Plain typed application interfaces for telemetry, alarms, documents, analytics and UI actions.
2. **Orchestrator tools:** Narrow schemas exposed to LangGraph, with user authorization injected by the runtime.
3. **Optional MCP adapters:** Expose the same safe tools to other approved AI clients.

This avoids coupling the turbine application to one agent framework while retaining MCP interoperability.

### MCP value

MCP is useful for:

- Standardized tool discovery
- Reusing ThingsBoard tools from different agent hosts
- Separating telemetry, knowledge and analytics servers
- Consistent schemas and tool metadata
- Supporting cloud and self-hosted model clients
- Assigning explicit risk labels to tools

MCP does **not** automatically solve:

- Tenant authorization
- Prompt injection
- Large telemetry payloads
- Tool-loop control
- Model reliability
- Human approval
- OT network safety
- Transactions or durable workflow execution

The custom ThingsBoard MCP in [conversational-analytics](https://github.com/sambertibus99/conversational-analytics) is more directly reusable for telemetry analysis today, while the official [thingsboard-mcp](https://github.com/thingsboard/thingsboard-mcp) should be evaluated for broader coverage and long-term alignment.

### MCP server boundaries

Recommended independent servers:

- `tb-read-mcp`: entities, attributes, telemetry and alarms
- `engineering-kb-mcp`: controlled document retrieval
- `analytics-results-mcp`: anomaly, forecast and maintenance results
- `dashboard-ui-mcp`: optional client-visible UI intents
- `control-proposal-mcp`: future, isolated and unavailable to the ordinary read-only agent

Do not place read and control tools in the same default registry. A model cannot accidentally call a tool that has not been made available.

### Framework choice

| Approach | Recommendation |
| --- | --- |
| Direct API tools | Best foundation; simplest to test and secure |
| MCP | Add for interoperability and tool-server separation |
| LangGraph | Best orchestrator choice for explicit state, retries, approvals and bounded loops |
| LangChain agents | Useful libraries, but avoid an unconstrained generic agent |
| LlamaIndex | Strong option for document ingestion and retrieval; not necessary for telemetry orchestration |
| Custom orchestration only | Viable for a small deterministic MVP |
| Multi-agent supervisor | Use only where tool domains genuinely require separate state or policies |

The ThingsBoard implementation in `conversational-analytics` demonstrates a LangGraph supervisor, separate data/statistics/visualization agents, bounded cycles, persistent multi-turn state and large-data offloading. That is a valuable reference, but the production turbine version should initially use a simpler deterministic graph with fewer agents. [conversational-analytics](https://github.com/sambertibus99/conversational-analytics)

---

## RAG architecture

### Knowledge categories

| Content | Retrieval method |
| --- | --- |
| Manuals and procedures | Hybrid keyword and vector retrieval with reranking |
| Alarm definitions | Structured lookup first; document fallback |
| Operating limits | Structured database or governed asset attributes |
| Sensor metadata | Asset registry, ThingsBoard attributes or AAS submodels |
| Maintenance history | Filtered structured search plus report retrieval |
| Incident reports | Hybrid retrieval with turbine/component/date metadata |
| P&IDs and diagrams | Multimodal extraction with page/image references |
| Live telemetry | Tool call, never vector retrieval |
| Historical telemetry | Time-series query and deterministic computation |
| ML outputs | Versioned analytics-results API |
| Relationships | ThingsBoard entity graph, AAS or graph database |

### Ingestion pipeline

 1. Register source, owner, document type and lifecycle state.
 2. Preserve document version, page, heading, table and figure references.
 3. Extract text and tables with layout-aware parsing.
 4. Create semantically meaningful chunks rather than fixed arbitrary windows.
 5. Attach turbine model, component, sensor, alarm code, language and revision metadata.
 6. Generate embeddings with a replaceable embedding service.
 7. Index text for BM25/keyword retrieval and vectors for semantic retrieval.
 8. Apply a reranker.
 9. Enforce document ACL and validity before retrieval.
10. Return evidence objects containing exact source location and document revision.

For turbine manuals, metadata filtering often matters more than additional agent complexity. A gearbox-maintenance procedure for one turbine model must not be silently applied to another model or superseded manual revision.

### Asset Administration Shell

Where an AAS is available, use its semantic IDs and submodel structure as the canonical bridge between ThingsBoard entity IDs, document sections, sensor keys and analytics models. The AI can then resolve “gearbox bearing temperature” through a semantic asset model instead of depending on prompt-maintained key aliases.

Recommended metadata relationships include:

```
Turbine
  ├─ component → Gearbox
  ├─ sensor → GBX_VIB_DE
  ├─ operating-limit → VibrationLimitSet-v3
  ├─ manual → GearboxManual-revC
  ├─ procedure → GBX-BEARING-INSPECT-04
  └─ analytics-model → GearboxAnomalyModel-2.6
```

### Answer grounding

Each technical answer should distinguish:

- **Observed:** telemetry, timestamp, quality and alarm state
- **Computed:** aggregates or correlations and the method used
- **Model-produced:** anomaly, forecast or health result and model version
- **Documented:** manual/procedure claim with source location
- **Interpretation:** LLM synthesis and uncertainty
- **Recommendation:** suggested operator action, clearly not an executed command

---

## Analytics separation

Specialized models should expose versioned, machine-readable results rather than prose:

```
{
  "analysisType": "anomaly_detection",
  "assetId": "WTG-07",
  "componentId": "GEARBOX",
  "sensorIds": ["GBX_VIB_DE", "GBX_TEMP_OIL"],
  "window": {
    "startTs": 1789471800000,
    "endTs": 1789493400000
  },
  "status": "ANOMALOUS",
  "score": 0.91,
  "severity": "HIGH",
  "features": [
    {
      "name": "vibration_rms",
      "contribution": 0.63
    }
  ],
  "evidenceRefs": ["timeseries://..."],
  "model": {
    "name": "gearbox-anomaly",
    "version": "2.6.1",
    "trainedThrough": "2026-08-31"
  },
  "qualityFlags": [],
  "generatedAt": "2026-09-15T15:52:00Z"
}
```

The conversational service should retrieve these objects using dedicated tools. It may explain that an anomaly model associated the event with rising vibration and temperature, but it must not relabel that output as a confirmed mechanical fault.

### Integration methods

- **Pull:** Agent queries the latest analytics result when a user asks a question.
- **Push:** Analytics service publishes result telemetry or events into ThingsBoard.
- **Event-driven:** Results are written to an analytics store and referenced from a ThingsBoard alarm.
- **Hybrid:** Compact state goes to ThingsBoard; full evidence remains in the analytics service.

The hybrid pattern is recommended. ThingsBoard retains operator-visible state, alarm correlation and dashboard status, while detailed feature contributions, forecast distributions and model artifacts stay in their responsible services.

---

## Conversational UI

### Ranked options

| Rank | UI | Best use | Trade-off |
| --- | --- | --- | --- |
| 1 | Custom ThingsBoard widget with external backend | Production embedded assistant | Best dashboard context; requires widget development |
| 2 | iframe-hosted React chat | Fast MVP | Easy deployment but authentication, sizing and cross-frame messaging need care |
| 3 | Dedicated AI dashboard/page | Deep investigations | More workspace for evidence and charts; less “always available” |
| 4 | Floating assistant | Cross-dashboard use | Requires shell-level integration and can obstruct operational displays |
| 5 | External application | Advanced investigations and administration | Best engineering flexibility, weaker in-dashboard experience |
| 6 | Chainlit iframe | Prototype | Fastest reuse of ThingsBoard research code, but not ideal as final industrial UX |

### Recommended production UI

Use a custom widget that supplies:

- Collapsible right-side panel
- Streaming text
- Stop-generation control
- Evidence and source drawer
- Telemetry cards with timestamp and quality
- Inline declarative charts
- Suggested follow-up questions
- Dashboard navigation buttons
- “Open in full analysis workspace”
- Feedback and incorrect-answer reporting
- Visible context banner: `WTG-07 › Gearbox › Last 6 hours`
- Read-only badge
- Tool activity disclosure such as “Retrieved 3 signals and 2 alarms”

### Reusable interfaces

- [Chainlit](https://github.com/Chainlit/chainlit): most directly reusable because the strongest ThingsBoard-specific project already uses it.
- [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm): MIT-licensed, model-flexible, self-hostable document chat and agent workspace.\[[github](https://github.com/mintplex-labs/anything-llm)\]
- [Open WebUI](https://github.com/open-webui/open-webui): polished self-hosted chat with tools, knowledge and multi-provider support, but current licensing includes branding-related conditions that require review.\[[onyx](https://onyx.app/insights/openwebui-alternatives)\]\[[docs.openwebui](https://docs.openwebui.com/alternatives/anythingllm/)\]
- [CopilotKit](https://github.com/CopilotKit/CopilotKit): useful React copilot components and application-state interaction patterns.
- [assistant-ui](https://github.com/assistant-ui/assistant-ui): useful headless React chat components.
- [Vercel AI SDK](https://github.com/vercel/ai): useful streaming and provider abstractions.

AnythingLLM and Open WebUI are better as independent workspaces or UI references than as the internal ThingsBoard widget itself. AnythingLLM emphasizes document workspaces, while Open WebUI is more chat-first and offers extensible tools and retrieval.\[[docs.openwebui](https://docs.openwebui.com/alternatives/anythingllm/)\]

---

## Model architecture

### Provider abstraction

Define an application-level model interface:

```
generate(messages, tools, response_schema, policy, stream)
embed(texts, model_profile)
rerank(query, documents)
classify(task, schema)
```

A capability registry should indicate whether each configured model supports:

- Native tool calling
- Strict structured output
- Streaming
- Long context
- Images and diagrams
- On-premises deployment
- Data-retention controls
- Required latency class

### Deployment choices

| Option | Strength | Limitation | Recommended role |
| --- | --- | --- | --- |
| OpenAI | Strong structured output and tool ecosystem | Cloud dependency, data-governance review and variable cost | Cloud production profile |
| Anthropic | Strong tool reasoning and long-document performance | Cloud dependency and provider-specific tool behavior | Complex diagnostic synthesis |
| Gemini | Strong multimodal/document capabilities | Cloud dependency and provider-specific integration | Manuals, diagrams and mixed media |
| vLLM | Production-oriented self-hosted serving for supported models | Requires GPU capacity planning and model operations | Primary on-prem inference |
| Ollama | Very simple local model deployment | Less suitable than vLLM for high-concurrency production serving | Development, pilot and edge fallback |
| Hugging Face models | Broad model choice and control | Model evaluation and serving remain the operator’s responsibility | Custom on-prem model portfolio |
| OpenAI-compatible gateway | Decouples application from individual models | Lowest-common-denominator risk | Recommended boundary |

A provider gateway such as LiteLLM or a small internal OpenAI-compatible service can centralize model routing, budgets, retries, redaction and fallback. Avoid embedding provider-specific message formats throughout the ThingsBoard integration.

### Reliability rules

- Use a smaller model for intent classification and simple tool selection.
- Use the primary reasoning model only for evidence synthesis.
- Use deterministic code for arithmetic and statistics.
- Validate every tool call against JSON Schema.
- Set tool-count, token and wall-clock budgets.
- Allow only one bounded replanning loop in the initial release.
- Require citations for document-derived engineering claims.
- Abstain when evidence is missing, stale or contradictory.
- Never let fallback models silently weaken a safety policy.

---

## Security and safety

### Initial read-only posture

- Do not register ThingsBoard RPC, attribute-write, alarm-acknowledgement or dashboard-administration tools.
- Use read-only ThingsBoard credentials and verify permissions server-side.
- Scope every request to tenant, user, entity and time range.
- Place the AI backend outside the direct OT control network.
- Rate-limit telemetry queries and cap requested samples.
- Audit question, validated context, model, prompt version, tools, arguments, returned evidence and UI actions.
- Redact secrets and personal data before model invocation.
- Encrypt chat history and apply explicit retention periods.
- Use separate vector collections or mandatory tenant filters.
- Treat telemetry string values, alarm messages and retrieved documents as untrusted input.

### Prompt injection

Documents, alarm descriptions and telemetry labels can contain malicious or accidental instructions. Defenses should include:

- Retrieved content is tagged as data, never system instructions.
- Tool availability is fixed by server policy, not document text.
- Retrieved documents cannot request additional tools.
- HTML, scripts, hidden text and external links are sanitized during ingestion.
- Retrieval results carry provenance and trust level.
- Low-trust user documents cannot override controlled manuals.
- Tool outputs are schema-validated before entering the model context.
- The response validator rejects ungrounded commands and unsupported claims.
- High-risk recommendations require evidence from controlled sources.

### Future control

Future control must be a separate workflow:

```
LLM recommendation
→ typed control proposal
→ authorization check
→ current-state refresh
→ interlock dry-run
→ impact preview
→ named operator approval
→ optional second approver
→ expiring signed command
→ independent control gateway
→ PLC/SCADA safety checks
→ execution
→ verification and audit
```

The operator must approve the exact asset, command, value, unit and expiry—not a generic “allow the agent” permission. Any value change after approval invalidates the approval.

Further requirements include:

- Separation of duties for critical commands
- Lockout/tagout integration
- Engineering-range validation
- Idempotency keys
- Replay protection
- Short approval expiry
- Fail-closed behavior
- Independent emergency-stop and safety PLC
- No command execution from ordinary chat text
- No chain of autonomous follow-up commands
- Post-command verification from an independent feedback signal

The approval-binding and interlock patterns in [mcp-scada](https://github.com/zavora-ai/mcp-scada) are valuable references, but its own documentation identifies the implementation as an in-memory reference and states that field-level protection remains mandatory.

---

## Recommended stack

| Layer | Primary recommendation | Alternative |
| --- | --- | --- |
| ThingsBoard UI | Custom HTML/JavaScript widget, bundled TypeScript/React where practical | iframe React application |
| Backend API | FastAPI with Pydantic and SSE/WebSocket streaming | Kotlin/Spring Boot for Java-standardized environments |
| Orchestration | LangGraph with explicit state and bounded routes | Custom finite-state workflow |
| Internal tools | Typed Python service interfaces | gRPC domain services |
| MCP | Official/custom ThingsBoard MCP plus restricted adapters | No MCP during MVP |
| Model gateway | LiteLLM or internal OpenAI-compatible gateway | Provider-specific adapters |
| Cloud models | OpenAI, Anthropic or Gemini, selected by evaluated task | Dual-provider failover |
| On-prem models | vLLM | Ollama for pilot and low-volume edge |
| Vector store | Qdrant or PostgreSQL/pgvector | OpenSearch for combined enterprise search |
| Keyword search | PostgreSQL FTS or OpenSearch | Qdrant hybrid capabilities |
| Reranking | Dedicated cross-encoder/reranker service | Provider reranking API |
| Operational DB | PostgreSQL | Existing enterprise relational database |
| Session data | Redis plus PostgreSQL | DuckDB only for local analysis sessions |
| Eventing | Kafka, NATS or existing plant event bus | ThingsBoard Rule Engine webhooks |
| Observability | OpenTelemetry, Prometheus, Grafana and trace store | Existing enterprise APM |
| Policy | Application ABAC/RBAC plus OPA where justified | Internal policy middleware |
| Secrets | Vault/Kubernetes secrets | Enterprise secrets manager |
| Deployment | Kubernetes on-prem/cloud | Docker Compose for MVP |

---

## MVP implementation

### Scope

 1. Read-only chat widget embedded in one turbine dashboard.
 2. Context envelope containing turbine, component and time window.
 3. Latest and historical telemetry tools.
 4. Alarm-list and alarm-detail tools.
 5. Sensor catalog with units and aliases.
 6. Manual/procedure RAG with source citations.
 7. Access to existing anomaly results.
 8. Ephemeral line and comparison charts.
 9. Navigation to approved dashboard states.
10. One cloud model and one local model profile.
11. Full tool and answer audit logging.
12. No RPC, attribute write or alarm acknowledgement.

### Minimal graph

```
Validate request
→ Resolve context
→ Classify intent
→ Select one or more read tools
→ Retrieve evidence
→ Optional document retrieval
→ Synthesize answer
→ Validate claims and UI actions
→ Stream response
```

Use [conversational-analytics](https://github.com/sambertibus99/conversational-analytics) as the primary ThingsBoard telemetry reference, but simplify its multi-agent structure. Use its bounded queries, time parser, telemetry-key lookup, dataset/session patterns and chart-generation interface.

---

## Production implementation

Add:

- Shared OIDC identity and short-lived token exchange
- Per-entity authorization and tenant isolation
- High-availability AI gateway
- Durable conversational checkpoints
- Model/provider failover
- Controlled document workflow with approval and expiry
- Hybrid retrieval and reranking
- Asset/AAS semantic mapping
- Analytics-result registry
- OpenTelemetry traces across model and tool calls
- Prompt/model/tool version capture
- Offline evaluation suite and regression tests
- Adversarial prompt-injection tests
- Data-quality and stale-sensor handling
- Cost, latency and tool-call budgets
- Operator feedback and incident review
- Disaster recovery for vector and conversation stores
- SLOs for response latency, tool success and evidence coverage

Production telemetry tools should return summaries or references to session-side datasets. They should not insert tens of thousands of timeseries samples into the LLM prompt; the ThingsBoard-specific thesis project independently arrived at file-backed/DuckDB patterns to address this problem. [conversational-analytics](https://github.com/sambertibus99/conversational-analytics)

---

## Advanced architecture

The most advanced realistic form is a **context-aware industrial operations copilot platform**, not a single chatbot:

- ThingsBoard custom widget for embedded interaction
- Full-screen investigation workspace for complex analysis
- AAS-backed semantic asset graph
- Event-driven analytics-result service
- Multiple independently versioned ML services
- Governed engineering knowledge platform
- LangGraph workflow with deterministic policy nodes
- Provider-neutral model gateway
- On-prem vLLM with approved cloud fallback
- MCP adapters for external engineering clients
- Declarative dashboard-action protocol
- Digital evidence packages for every diagnosis
- Continuous model and retrieval evaluation
- Future separate control-proposal workflow with dual approval
- Edge fallback capable of answering from local telemetry and cached manuals during WAN outages

The agent should remain primarily an **evidence assembler and operator interface**. Root-cause calculations, prognostics, signal processing, anomaly detection and forecasting remain owned by validated domain services.

## Final ranking

### Best ThingsBoard integrations

1. [conversational-analytics](https://github.com/sambertibus99/conversational-analytics) — strongest reusable ThingsBoard telemetry, MCP, LangGraph and chart implementation; licensing clarification required.
2. [thingsboard-mcp](https://github.com/thingsboard/thingsboard-mcp) — strongest official integration and likely best long-term compatibility path.
3. ThingsBoard custom widget plus REST/WebSocket APIs — mandatory production UI/context foundation.
4. iframe-hosted external copilot — fastest viable MVP.
5. Rule Engine and event-bus integration — best for publishing analytics results, not for hosting the conversation.

### Best reusable codebases

1. [conversational-analytics](https://github.com/sambertibus99/conversational-analytics)
2. [shopfloor-copilot](https://github.com/Somya170/shopfloor-copilot)
3. [mcp-scada](https://github.com/zavora-ai/mcp-scada)
4. [DocOps](https://github.com/SparshM8/DocOps)
5. [Engineering-Failure-Copilot](https://github.com/Farhan-0000/Engineering-Failure-Copilot)
6. [AgenticWindFarm](https://github.com/orcunku/AgenticWindFarm)
7. [manufacturing-car-manual-RAG](https://github.com/mongodb-industry-solutions/manufacturing-car-manual-RAG)

### Best overall design

**ThingsBoard custom widget → authenticated AI gateway → LangGraph deterministic orchestrator → policy-scoped ThingsBoard tools + engineering RAG + analytics-result services → model gateway → validated explanation and declarative dashboard actions.**

This design satisfies model portability, on-prem/cloud deployment, dashboard awareness, industrial data separation and an initially read-only safety posture without forcing ThingsBoard widgets to become an AI application runtime.