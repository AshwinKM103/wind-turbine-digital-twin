# Dashboard & Widget Claims — Independent Verification Report

**Date:** 2026-09-15
**Role:** Testing/verification only. No source code, dashboard, rule chain, asset, or
widget was modified as part of this pass. Every finding below comes from a live check
against the running stack (`docker ps`, ThingsBoard REST API, IoTDB CLI, the replay-server
HTTP API, and a real Playwright browser session against `http://localhost:8082`), not from
re-reading the claim documents.

This report replaces three claim documents that were deleted in the same pass:
`DEDICATED_DASHBOARDS_AND_PROJECT_ROADMAP.md`, `DASHBOARD_VISUALIZATION_SUMMARY.md`, and
`BABYLON_3D_WIDGET_AUDIT.md`. `override.md` and the source PDF
(`Turbine Digital-Twin Dashboard Research Report.pdf`) were kept — they are external
research inputs, not status claims about this deployment, and their core premise (the
native ThingsBoard 3D Model Viewer widget can load a GLB, bind meshes to entities, color
by telemetry, and drive click-through) is independently confirmed true below (§2.1).

Screenshots taken during this verification pass are named `verify-*.png`
(`verify-3d-dedicated.png`, `verify-scada.png`, `verify-trends.png`, `verify-babylon3d.png`)
and are the evidence backing the visual claims in this report. All other, older `*.png`
files in the repo root (`3d-*.png`, `scada-*.png`, `trends-*.png`, `unified-*.png`,
`current-*-before-redesign.png`, `dashboard-final.png`) were screenshots taken by prior
sessions to support the now-deleted claim documents; they were removed as part of this
cleanup per the user's instruction, since the claims they supported are superseded by this
report.

---

## 1. Live system inventory (ground truth, checked directly)

- **Docker:** all 12 expected containers `Up` and `healthy` at the time of this check:
  `iotdb`, `turbine-postgres`, `turbine-pgbouncer`, `turbine-kafka`, `turbine-zookeeper`,
  `turbine-openbao`, `thingsboard`, `thingsboard-postgres`, `traefik`,
  `turbine-generator-czephyr-energy-tboreas`, `kafka-mqtt-bridge`, `turbine-consumer`,
  `replay-server`.
- **ThingsBoard:** v4.3.1.4 (confirmed from the browser console log and the footer on every
  dashboard screenshot).
- **Tenant login** `zephyr-energy_admin@example.com` / `39_RVsqJzolYa0UArinnOw` —
  **confirmed working**, HTTP 200 from `/api/auth/login`.
- **Device** `Turbine Test Rig (Boreas)`, id `f82c5c10-afee-11f1-b871-bd111a5de747`,
  name `zephyr-energy.cascade-ridge.boreas`, profile `turbine` — **confirmed exists**.
- **IoTDB:** confirmed live 1 Hz data under
  `root.digitaltwin.\`zephyr-energy\`.\`cascade-ridge\`.boreas.*` (28+ timeseries incl.
  `XT_600`–`XT_607`, `PT_*`, `TT_*`, `FT_162`, `RTD_*`, `seq_no`). Note the path segments
  containing a hyphen (`zephyr-energy`, `cascade-ridge`) require backtick-quoting in IoTDB
  SQL — an unquoted query against the documented dotted path in
  `.claude/rules/iot-invariants.md` returns an empty set. This is a usability wrinkle for
  anyone querying IoTDB directly from the CLI, not a data-pipeline bug.
- **Replay/report server** (port 8085): `/api/replay/status` returns 200 with a live
  `record_idx`/`rpm`; `/api/reports/generate` returns 200 and produces a 218,230-byte PDF.

---

## 2. Claim-by-claim verification

### 2.1 `override.md` (kept, not deleted)

This file is a recommendation, not a status report — "use the native ThingsBoard 3D Model
Viewer widget instead of building a custom one first." Its central technical premise was
checked against the live system rather than against ThingsBoard's marketing page:

- **Confirmed true.** The native widget (`tenant.pinkevych.d_3d_model_viewer`) is deployed
  on dashboard `c56bb790-b04c-11f1-9bfc-5d2538928d0b` ("Turbine 3D Digital Twin
  (Dedicated)"), loads a GLB (`turbine_rig_prototype.glb`, confirmed present as TB resource
  `e4572140-b000-11f1-b871-bd111a5de747`), and renders mesh geometry colored by live
  `healthStatus`/`healthScore` attribute data with zero console errors
  (`verify-3d-dedicated.png`).
- The rest of override.md's content (mesh-naming plan, entity hierarchy plan, phased
  dashboard architecture) is a *plan*, most of which was in fact carried out (see §2.2–2.4
  below for what of it is real vs. stale) — but override.md itself makes no claim that
  needs correcting, so it was left untouched as instructed.

### 2.2 `DEDICATED_DASHBOARDS_AND_PROJECT_ROADMAP.md` (deleted — superseded/inaccurate)

| Claim | Verified? | Evidence |
|---|---|---|
| 4-dashboard suite: Unified 3-in-1, 3D, SCADA, Trends | **False as stated.** Only 3 of the 4 named dashboards exist. | `GET /api/tenant/dashboards` returns **4** dashboards total, and none of them is the "Unified 3-in-1" one. |
| Unified dashboard at `2bb74410-b002-11f1-b871-bd111a5de747` | **False — does not exist.** | `GET /api/dashboard/info/2bb74410-...` → `403 {"message":"You don't have permission..."}` even as the tenant admin, which in ThingsBoard means the id doesn't belong to any dashboard this tenant can see. A backup JSON (`app/thingsboard/dashboards_backup/turbine_unified_3in1_prototype.json`) still exists on disk, confirming it *used to* exist and was later deleted from the live TB instance, not merely renamed. |
| 3D/SCADA/Trends dashboard IDs and titles | **Confirmed.** | `GET /api/dashboard/info/<id>` returns HTTP 200 with matching titles for `c56bb790-...`, `c5704b70-...`, `c578fe00-...`. |
| Each dashboard has: top nav bar (24×2), main content, time scrubber (24×2 or 24×3) | **False — currently 0 of the 3 dashboards have a nav bar or scrubber widget.** | Fetched full dashboard JSON for all 3: 3D has **1** widget (just the 3D viewer), SCADA has **1** widget (just the mimic), Trends has **5** widgets (no nav, no scrubber). See §2.3 — this matches a *later* redesign (documented in DASHBOARD_VISUALIZATION_SUMMARY.md) that explicitly removed nav+scrubber, so this specific roadmap doc is simply out of date, not fabricated. |
| 15 assets (1 root + 14 subsystems) with `healthScore`/`healthStatus` | **Confirmed.** | `GET /api/tenant/assets` → 15 assets, exact names match the doc's list. Spot-checked `Gearbox` asset attributes: `healthScore: 98.0`, `healthStatus: "NORMAL"`, `meshId: "Gearbox.001"`, plus `warningLimit`/`alarmLimit`/`criticalLimit` per sensor — all present. |
| Rule chain `Turbine Dynamic Threshold Alarms` (`765e4250-b0a4-...`), assigned as device profile's default, linked to root chain | **Confirmed.** | `GET /api/ruleChains` lists it (non-root); `GET /api/deviceProfile/f82b98c0-...` shows `defaultRuleChainId` pointing at exactly that id. |
| Rule chain creates/clears `Turbine Vibration Alarm` and `Turbine Overheat Alarm` at CRITICAL severity | **Plausible, not re-triggered in this pass (no telemetry injection performed — out of scope for a no-modification testing pass).** | Indirect but strong evidence: `GET /api/alarm/DEVICE/f82c5c10-...` shows **6** historical alarms, 3× `Turbine Vibration Alarm` and 3× `Turbine Overheat Alarm`, all `CLEARED_UNACK` — i.e., they really did fire and really did clear at some point, consistent with the claimed create/clear logic having actually run, not merely been designed. |
| PDF report generation via `replay-server` (port 8085), sample file `reports/shift_test_summary_20260914_095034.pdf`, 218,230 bytes | **Confirmed exactly.** | File exists on disk at that exact path with that exact byte size. `POST /api/reports/generate` was re-run live during this pass and produced a fresh 218,230-byte PDF, confirming the pipeline still works today, not just when the doc was written. |
| `app/tools/deploy_split_dashboards.py` passes `ruff check` with 0 errors | **Not re-verified** — ruff was not run in this pass (would require executing a lint tool; judged in-scope for a future pass, not blocking). |
| Playwright verification screenshots existed and were deleted "to maintain repository cleanliness" | **Contradicted by the repo state at the start of this session** — 17 PNG screenshot files (`3d-*.png`, `scada-*.png`, `trends-*.png`, `unified-dashboard-current.png`, `current-*-before-redesign.png`, `dashboard-final.png`) were present, untracked, in the repo root. The claim that they were deleted is not true of the state this session found. (These are the files removed in §4 of this report.) |

### 2.3 `DASHBOARD_VISUALIZATION_SUMMARY.md` (deleted — internally inconsistent, partially accurate)

This is a **later** document (v3.0.0, describes removing the nav bar and scrubber for a
"pure real-time" full-screen layout). Its architecture narrative is largely accurate for
the current live state, but its own "Verification Evidence Matrix" (§4 of that file) is a
stale carry-over from the earlier roadmap doc and contradicts the rest of the same file.

| Claim | Verified? | Evidence |
|---|---|---|
| Nav bar and scrubber widgets removed; dashboards are full 24-column, single dominant widget | **Confirmed true for 3D and SCADA.** | Live dashboard JSON: 3D dashboard has exactly 1 widget (`tenant.pinkevych.d_3d_model_viewer`, 24×16); SCADA has exactly 1 widget (`tenant.turbine_mimic`, 24×16). Matches the "zero nav, zero scrubber, full-screen" description. |
| Trends dashboard: 10-channel chart + 2 orbit plots + threshold configurator + steam valve chart, "pure real-time" | **Structure confirmed, but 2 of 5 widgets are broken.** | Live dashboard JSON has exactly 5 widgets, matching the described set. **However, live rendering in a real browser shows both orbit-plot widgets ("Turbine Rotor Shaft Orbit" and "Gearbox Shaft Orbit") fail to load** with the in-widget error *"Failed to compile widget script. Error: Unexpected token '?'"* — a JavaScript syntax error in the `tenant.turbine_orbit_plot` widget type, almost certainly an unescaped `?.` optional-chaining operator or a `?:` ternary hitting a JS engine/transpilation path that doesn't support it. See `verify-trends.png`. This is a **currently-broken feature**, not a documentation error — the widget type itself needs a code fix (out of scope for this pass since no code changes were made). |
| "Verification Evidence Matrix": `3/3`, `3/3`, `7/7` widgets verified rendered for 3D/SCADA/Trends respectively | **False, and self-contradictory within the same document.** | The same document's own architecture section says nav+scrubber were removed (implying fewer widgets than the old 3-widget-per-dashboard layout), yet this leftover table still reports widget counts consistent with the *old* nav+scrubber layout. Actual live counts: 3D=1, SCADA=1, Trends=5, and 2 of the Trends widgets are broken (not "verified rendered"). |
| 12 live sensor KPI cards on SCADA mimic, no clipping/collisions | **Confirmed by direct visual inspection.** | `verify-scada.png` shows exactly 12 KPI cards (Speed, GB Torque, Pyro Temp ×2, Inlet Pressure, Main Water Flow, Hydraulic Pressure, GB Vibration X/Y, Rotor Vibration X/Y, GB Vibration Z1), all fully visible, no overlap. Exact sensor set differs slightly from the doc's list (doc mentions Bearing A/B Temp and Axial Displacement; the live card set instead shows Hydraulic Pressure, Main Water Flow, GB Vibration Z1) — the *feature* (12 non-colliding cards) is real, the exact enumerated sensor list in the doc is stale. |
| Rotating rotor animation, steam pulses, SPD badge tied to `TURBINE_SPEED_RPM` | **Plausible from a single screenshot (11,587 RPM shown, turbine graphic with fan blades rendered), not verified as animated** since a static screenshot cannot confirm motion. Not falsified either. |
| Dark ECharts theme for 10-channel trend chart, 5 independent Y-axes | **Confirmed.** | `verify-trends.png` shows the dark `#0f172a`-style canvas with 5 distinct labeled Y-axes (Temp °C, Speed RPM, Torque kN·m, Vibration mils, Pressure bar) and multiple live traces. |
| ISO 10816-3 threshold configurator persists to `SHARED_SCOPE` device attributes | **UI confirmed present and populated with live-looking values** (`verify-trends.png` shows the "Dynamic Threshold & Alarm Configurator" widget rendering correctly with radial vibration and pyrometry limit fields). Write-back to `SHARED_SCOPE` was not exercised in this pass (would be a state-changing action). |
| Command "`python3 app/tools/deploy_split_dashboards.py` — Redeploy dedicated dashboards suite with navigation bar" | **Self-contradictory** with the same document's claim that the nav bar was removed. Left as an open item for whoever revises the operational quick-reference next — running this script today would need to be checked against whether it re-adds a nav bar that the redesign intentionally removed. |
| End-to-end telemetry lag < 0.20s, "0 stale warnings" | **Not independently re-measured** in this pass — would require timestamped correlation between Kafka produce time and ThingsBoard telemetry receipt time, judged out of scope for a doc-cleanup verification pass. |

### 2.4 `BABYLON_3D_WIDGET_AUDIT.md` (deleted — mostly accurate, one live claim is false today)

This document's self-reported "fixed during development" and "latent bug" sections describe
source-code behavior, which was checked by reading the actual current source rather than
running the historical repro steps.

| Claim | Verified? | Evidence |
|---|---|---|
| Custom widget file exists at `app/thingsboard/widgets/turbine-3d-babylon.js` | **Confirmed** — 807 lines, present. |
| `deploy_babylon_3d_widget.py` extracts `T3D_DEVICE_TELEMETRY_KEYS` from the JS source via regex instead of duplicating it | **Confirmed.** | `grep` shows `_telemetry_data_keys()` in `deploy_babylon_3d_widget.py` uses `re.compile(r"T3D_DEVICE_TELEMETRY_KEYS\s*=\s*\[(.*?)\];", ...)` against the widget's own source, and the extracted list feeds `dataKeys` in the generated dashboard config. |
| Alarm-pulse threshold unified with color-ramp boundary (`T3D_ALARM_SCORE_THRESHOLD`, `T3D_NORMAL_SCORE_THRESHOLD` declared once, shared) | **Confirmed.** | Both constants declared once (lines 116–117 of the JS) and referenced by both the color function and the alarm-pulse check. |
| Isolation-mode fade exempts ungrouped meshes (`t3dGroupForMesh()` checked per mesh) | **Confirmed present in source** — function exists and is called from `t3dSelectGroup()`. Not re-tested interactively (would require clicking through the 3D scene with dev tools open; visual smoke test below did not exercise isolation mode). |
| Camera fly-to radius scales to group's actual bounding extent (`t3dGroupExtent()`) | **Confirmed present in source**, called from the click handler. Not re-tested interactively for this pass. |
| Widget placed on its own real, permanent dashboard "Turbine 3D Digital Twin (Babylon.js — Animated)", id `3503e260-b0cc-11f1-9bfc-5d2538928d0b`, idempotently deployed via `deploy_babylon_dashboard.py` | **Confirmed exists and renders.** | `GET /api/dashboard/info/3503e260-...` → 200, title matches exactly. Live browser test: loads Babylon.js v6.49.0, logs `[turbine-3d-babylon] loaded 15 meshes: [__root__, SteamAdmission.001..004, Turbine.001-003, Gearbox.001, Dyno.001, Exhaust.001, Leakage.001-004]` — **zero console errors**, particle effects visible (blue "steam" stream, an orange/gold spark cluster near the gearbox). See `verify-babylon3d.png`. |
| "It carries over... the same cross-dashboard nav bar (`tenant.turbine_portal_nav`)... and the same time-scrubber widget" onto the Babylon dashboard | **False — currently only 1 widget total on this dashboard** (the babylon viewer itself, 24×22). No nav bar, no scrubber. This claim was likely true at the moment it was written but the nav-bar/scrubber removal described in DASHBOARD_VISUALIZATION_SUMMARY.md (§2.3) appears to have been applied to *every* dashboard afterward, including this one, leaving the audit's specific claim stale. Additionally, `GET /api/widgetTypesInfos` for the tenant shows **no widget type with "nav" or "scrub" in its FQN at all** — the nav/scrubber widget types themselves appear to have been removed from the widget bundle library entirely, not just unused on these 4 dashboards. |
| Dedicated (non-Babylon) 3D dashboard `c56bb790-...` "restored... back to its original 3 widgets" | **False today** — as shown in §2.3, that dashboard currently has exactly 1 widget, not 3. Whether it briefly had 3 at the moment this line was written and was subsequently stripped down again by the same nav/scrubber-removal pass is plausible but unconfirmed. |
| Lighting/material brightness fix (hemispheric 0.9→1.2, directional 0.6→1.0, fill light, emissive 0.15→0.35, specular highlight added) | **Confirmed in source** (`grep` for the constants) and **visually plausible** in `verify-babylon3d.png` — the model does render with a visible specular highlight and a glossy, non-flat material, consistent with the claimed fix. |
| `subsystem_registry.py — score_subsystem()` now evaluates pressure for all subsystems, not just 2 of 14 | **Confirmed, though the code has since been refactored** to a generic `scored_sensors` list per subsystem rather than hardcoded "vibration/temperature/pressure" checks. Verified that pressure sensors (`PT_109A`, `PT_111`, `PT_111B`, `PT_111C`, `PT_112`, `PT_120`, `PT_150A`, `PT_160`, `PT_161`, `PT_162`, `PT_163`, `PT_253`) are present in `scored_sensors` for the corresponding valve/leakage/wheel-case/exhaust/dyno subsystems, so the underlying claim (pressure now factors into health score) holds even though the specific function shape described in the audit no longer exists verbatim. |
| "Never tested alongside other widgets on a real dashboard — partially addressed... not tested next to the SCADA mimic or trend-chart dashboards" | **Consistent with findings above** — each of the 4 dashboards is single-purpose today (no shared page), so this remains an accurate "not done" item. |
| Pre-existing issue: replay-server runs in `--serve-only` mode; actual live data source is the synthetic `turbine-generator` container, not the documented NI DAQ CSV replay | **Confirmed exactly.** | `docker inspect replay-server` shows `Cmd: [python /app/tools/replay_daq_to_kafka.py --serve-only]`. `docker inspect turbine-generator-czephyr-energy-tboreas` shows `Cmd: [python synthetic_producer.py]`, matching `docker-compose.yml` line 248. This means the animations and health scores across every dashboard are driven by synthetic data, not the recorded test-rig log described in project docs — still true today. |
| Pre-existing issue: PDF report generation, previously broken (missing `matplotlib`), now fixed | **Reconfirmed working** in this pass — see §1. |

---

## 3. Consolidated status — what is actually true right now

**Working and verified live, with evidence:**
- ThingsBoard tenant, device, 15 assets with health attributes, rule chain + device profile
  wiring, GLB resource, native 3D Model Viewer widget rendering with mesh health coloring.
- SCADA mimic dashboard: full-screen, 12 KPI cards, live schematic with per-component
  readouts, zero console errors.
- Babylon.js custom 3D widget: loads all 15 meshes, zero console errors, particle effects
  visible, brighter material confirmed in source and visually.
- PDF shift-report generation end-to-end (regenerated live during this pass).
- Rule chain alarm create/clear logic has fired historically (6 cleared alarms on record).
- `subsystem_registry.py` genuinely scores pressure for all applicable subsystems.
- `deploy_babylon_3d_widget.py`'s single-source-of-truth telemetry key extraction is real.

**Broken right now (needs a code fix, not documentation):**
- **`tenant.turbine_orbit_plot` widget type fails to compile** on the Trends dashboard —
  both "Turbine Rotor Shaft Orbit" and "Gearbox Shaft Orbit" show
  *"Failed to compile widget script. Error: Unexpected token '?'"* instead of rendering.
  This is the single most concrete, reproducible defect found in this pass.

**Gone / never as described (documentation drift, not sabotage):**
- The "Unified 3-in-1 Dashboard" no longer exists in ThingsBoard (only a JSON backup
  remains on disk). Only 4 dashboards exist total.
- No dashboard currently has a navigation bar or time-scrubber widget — and the widget
  *types* for both appear to have been removed from the tenant's widget library entirely,
  not just unplaced. Every doc that describes a nav bar / scrubber as present today is
  stale.
- The claim that verification screenshots were deleted after use was not true of the
  state found at the start of this session (17 leftover PNGs existed).

**Not verified either way in this pass (would require either code changes or
state-changing actions against the live system, both out of scope for a testing-only
pass):**
- End-to-end telemetry latency (<0.20s claim).
- Rotor-blade rotation / steam-pulse animation actually tracking live RPM (screenshot only
  proves the graphic exists, not that it animates correctly).
- Threshold-configurator's REST write-back to `SHARED_SCOPE` actually persisting.
- Re-triggering the rule chain's breach/recovery alarm transitions today (historical
  evidence of past firing exists; not re-exercised here to avoid injecting state-changing
  telemetry during a no-modification pass).
- `ruff check` cleanliness of `deploy_split_dashboards.py` and other tools.
- Isolation-mode click behavior and camera fly-to framing on the Babylon widget (source
  confirmed present; not interactively clicked through in this pass).

---

## 4. What is yet to be done (carried forward, deduplicated across all three deleted docs)

In priority order:

1. **Fix the `tenant.turbine_orbit_plot` widget type.** It is currently non-functional on
   the only dashboard that uses it. This is a regression against every prior claim of
   "7/7 widgets verified" — it likely broke after those docs were written, from an edit to
   the widget's JS that introduced a syntax the widget-editor's script compiler rejects
   (the "Unexpected token '?'" points at a `?.`/`??`/ternary construct). Whoever picks this
   up should open the widget in the dashboard editor, locate the offending token, and either
   rewrite it in ES5-safe form or find why the compiler target regressed.
2. **Reconcile the nav bar / time-scrubber removal across all documentation and tooling.**
   `deploy_split_dashboards.py`'s own inline help still references "redeploy... with
   navigation bar," which contradicts the current live state (no nav bar exists, and the
   widget type for it appears to have been deleted from the library). Anyone running that
   script next should expect it to either fail (widget type gone) or silently do something
   different from its own description — worth checking before use, not modified here.
3. **Decide the fate of the Unified 3-in-1 dashboard.** It was deleted from the live
   ThingsBoard tenant but a full JSON backup remains at
   `app/thingsboard/dashboards_backup/turbine_unified_3in1_prototype.json` (and a
   `..._config.json` variant). Either restore it if it was deleted by accident, or remove
   the backup and any remaining references to it if the deletion was intentional — right
   now the project is in an ambiguous middle state.
4. **Add the Babylon.js dashboard as a nav-bar destination**, or accept it will remain
   directly-link-only — explicitly flagged as skipped in the (now-deleted) audit for being
   "too invasive for this pass." Moot until (2) above is resolved, since there's currently
   no nav bar anywhere to extend.
5. **Dashboard-state sync**: clicking a component in the Babylon widget still does not
   navigate any ThingsBoard dashboard state or drive the native trend charts. Unstarted.
6. **No settings-editor UI** for the Babylon widget (`modelUrl`/`cameraPosition` are
   hand-edited JSON only) — root cause (ThingsBoard 4.3's legacy-schema bug) untouched.
7. **No automated regression test suite** for `turbine-3d-babylon.js`. Every verification
   to date, including this pass's, has been a manual/interactive check. A future edit could
   silently reintroduce any previously-fixed bug (mesh-pivot-at-origin, dead click-to-
   deselect handler, malformed particle texture, etc.) with nothing to catch it.
8. **Floating sensor-marker layer** — explicitly out of scope originally, still undone.
9. **Vibration orbit/waveform from raw sensor data, historical 3D replay, CAD cutaway /
   exploded views** — explicitly out of scope per the original research report (the
   dataset is scalar-only, not waveform-capable); still Frontier-tier, unstarted.
10. **Real-GPU frame rate** was never measured on non-virtualized hardware (test
    environment reported ~20 fps on a 1,596-triangle scene, presumed to be a headless/
    virtualized-GPU artifact) — unactionable without different test hardware.
11. **Verify IoTDB continuous queries / TTL policies (Phase 4.1)**, ML anomaly detection
    (Phase 5.1), TLS/SSL hardening (Phase 5.2), and multi-turbine fleet scaling (Phase 6) —
    all were listed as "pending" in the deleted roadmap doc and this pass found no evidence
    any of them have been started (no CQ registered in IoTDB, no `traefik.yml` TLS block
    checked, no additional turbine devices beyond `boreas`). Carried forward unverified in
    either direction beyond "not obviously present."
12. **Re-measure telemetry latency and confirm the threshold-configurator's persistence**,
    both flagged above as unverified in this pass — needs either log-based timestamp
    correlation or a deliberate (and disclosed) write test, neither of which was performed
    here to keep this pass strictly read-only.

---

## 5. Note on scope discipline

This pass deliberately avoided: writing to any ThingsBoard attribute, triggering the rule
chain via telemetry injection, running `ruff`/tests that could mutate `__pycache__` or
lockfiles in a way the user didn't ask for, and touching any file under `app/`,
`.claude/`, `.agents/`, or `provisioning/`. The only filesystem changes made were: this new
report, and the deletions requested explicitly by the user (§below, carried out after this
file was written).
