# Implementation Plan — Dashboard/Widget Follow-ups

**Date:** 2026-09-15
**Source:** Consolidates `VERIFICATION_REPORT_2026-09-15.md` items 1-12, `override.md`,
and `Turbine Digital-Twin Dashboard Research Report.pdf`, filtered through decisions made
2026-09-15. Each item below states current-state (checked directly against the repo),
the decision, and concrete steps. No code has been changed as part of writing this plan.

---

## 1. Fix `tenant.turbine_orbit_plot` widget

**Current state:** The widget's source in `app/tools/deploy_dashboard_enhancements.py`
(lines 926-1080, `orbit_js`) contains no `?.` optional-chaining or malformed token — the
only conditional is a plain ternary (`isGb ? 'XT_604' : 'XT_600'`), which is ES5-safe. The
source looks already fixed. **But** the verification report tested the *live* widget in
ThingsBoard, not this file, so the fix may not be deployed yet.

**Steps:**
1. Run `python3 app/tools/deploy_dashboard_enhancements.py` (or whatever subset flag
   redeploys just `turbine_orbit_plot`) against the live tenant.
2. Open the Trends dashboard in a browser, confirm both "Turbine Rotor Shaft Orbit" and
   "Gearbox Shaft Orbit" render without the "Unexpected token '?'" error.
3. Screenshot as `verify-orbit-fixed.png` for the record.

**Done when:** both orbit widgets render live with no console/compile errors.

---

## 2 & 4. Remove nav-bar/scrubber code paths (closed as "won't build")

**Decision:** no nav bar, no scrubber, ever. Not just "leave unused" — remove the code
that could reintroduce them.

**Current state:**
- `app/tools/deploy_split_dashboards.py` contains `build_portal_nav_widget_type()`
  (full widget-type builder for `tenant.turbine_portal_nav`) and wiring that would
  redeploy a nav bar referencing "Unified 3-in-1" if ever run.
- `orbit_js` in `deploy_dashboard_enhancements.py` still has a dead listener:
  `window.addEventListener('tb-time-scrub', self.ctx.scrubOrbitHandler)` — a leftover
  hook for a scrubber that no longer exists.

**Steps:**
1. Delete `build_portal_nav_widget_type()` and all calls/references to it in
   `deploy_split_dashboards.py`. If the script's only remaining purpose was
   nav-bar deployment, delete the script; if it also does other dashboard work, strip
   just the nav parts and update its docstring/CLI help.
2. Remove the `tb-time-scrub` listener and `scrubOrbitHandler` from `orbit_js` in
   `deploy_dashboard_enhancements.py` (both the `onInit` registration and the
   `onDestroy` cleanup).
3. Grep afterward for `portal_nav`, `scrubber`, `tb-time-scrub` across `app/` to confirm
   no references remain outside deletion.

**Done when:** no script in the repo can redeploy a nav bar or scrubber widget type.

---

## 3. Unified 3-in-1 dashboard backup (already resolved)

**Current state:** confirmed — `app/thingsboard/dashboards_backup/` does not exist, and
no `unified_3in1` file exists anywhere in the working tree or git history. The backup
referenced in the verification report is already gone.

**Action:** none. Close this item.

---

## 5. Babylon widget → dashboard-state sync

**Current state:** In `turbine-3d-babylon.js`, the `POINTERTAP` handler already does
local-only behavior: `t3dShowHudForMesh()` for the HUD and `t3dSelectGroup()` for
isolation/fade. Neither calls into ThingsBoard's `stateController`/`actionsApi` — nothing
external reacts to a click today. This confirms the report's "unstarted" status.

**Steps (build against the checked current state above):**
1. In the `POINTERTAP` handler (around the `t3dSelectGroup(self.ctx, group)` call),
   add a call to the widget's configured action source (e.g.
   `self.ctx.actionsApi.getActionDescriptors('componentClick')` pattern, per TB's
   widget-action model) so a click can navigate dashboard state, matching how
   `override.md`'s "mesh-click actions into ThingsBoard drill-down states" describes
   the native 3D Model Viewer working.
2. Wire the click to set a state parameter (e.g. `selectedComponent`) via
   `self.ctx.stateController.updateState(...)`, so other widgets on the same dashboard
   state (e.g. a future per-component sensor panel) can read the current selection.
3. Add a manual test: click each of the 14 component groups, confirm the state
   parameter updates (visible via TB's state URL param or a debug widget).

**Done when:** clicking a mesh changes dashboard state, verified interactively (per your
"check state first" — the above already reflects that check).

---

## 6. Babylon widget settings-editor UI (minimal version)

**Current state:** `modelUrl`/`cameraPosition` are hand-edited JSON in the widget's
advanced-settings tab. Root cause per the old audit: ThingsBoard 4.3's legacy JSON-schema
settings editor has a compatibility bug with custom widgets.

**Decision:** build a minimal version — a few fields, not a full schema-driven form.

**Steps:**
1. Confirm the exact TB 4.3 bug (reproduce it: try adding a standard `settingsSchema` to
   the widget type and see how it fails in the editor — this determines the workaround
   shape).
2. Likely workaround: bypass TB's schema renderer and inject a small custom HTML form
   inside the widget's own `templateHtml`/`controllerScript` (self-contained settings UI
   rendered in edit mode) for just `modelUrl` and `cameraPosition` (x/y/z + target).
3. Persist via `self.ctx.settings` write-back through TB's widget config update API.
4. Manual test: change `modelUrl` via the new UI, confirm it takes effect without
   touching raw JSON.

**Done when:** modelUrl and camera position are editable through a form, not raw JSON.

---

## 7. Automated regression tests for `turbine-3d-babylon.js`, as a CI/CD pipeline

**Current state:** confirmed — there is no test tooling for this repo at all (no
`package.json`, no JS test runner, no `.github/workflows` at the project root; the only
workflows found are inside the vendored `thingsboard/` and `iotdb/` submodule checkouts).
This is a from-scratch setup, not a gap-fill.

**Steps:**
1. Add a minimal `package.json` (or extend an existing one if `app/thingsboard/widgets`
   already has JS tooling — confirm none exists first) with a headless test runner.
   Given the widget is DOM+Babylon.js-driven, Playwright (already used for manual
   verification per `verify-*.png` and the `playwright` MCP server available in this
   session) is the natural fit over jsdom-based unit tests.
2. Write regression tests covering the specific previously-fixed bugs named in the old
   audit doc, since those are exactly what could silently regress:
   - mesh-pivot-at-origin correctness
   - click-to-deselect handler (clicking empty space calls `t3dSelectGroup(ctx, null)`)
   - particle-texture validity (no console errors on `t3dSetupParticleSystems`)
   - isolation-mode fade exempts ungrouped meshes (`t3dGroupForMesh` per-mesh check)
   - camera fly-to radius scaling (`t3dGroupExtent`)
3. Each test: load the widget in a real (headless) browser against a fixture GLB +
   fixture telemetry, assert on rendered state / console errors, not implementation
   internals.
4. Add `.github/workflows/babylon-widget-tests.yml` (project root, not inside a vendored
   submodule) running these on push/PR, per this project's own testing rules (mirror
   source structure, no skip/todo tests, timeout to catch hangs).

**Done when:** a CI workflow runs Playwright tests against the widget on every push, and
at least the 5 previously-fixed bugs above have a regression test each.

---

## 8. Floating per-sensor marker layer

**Current state:** confirmed — no per-sensor marker code exists in
`turbine-3d-babylon.js`. Only per-*component* (14 subsystems) coloring/click exists
today; nothing distinguishes individual sensors (e.g. `PT_109A` vs `TT_109A`, both on the
same inlet-pipe mesh).

**Decision:** build it, per the PDF's interaction spec.

**Steps (per PDF's confirmed sensor map and interaction model):**
1. Build a sensor-marker config object outside the GLB, per the PDF's recommended shape:
   `sensorId`, `sourceKey`, `displayName`, `units`, `system`, `componentNode`,
   `position3D`, `position2D`, `orientation`, `displayTier`, `warningLimit`,
   `alarmLimit`, `criticalLimit`. Seed it from the PDF's "Confirmed sensor map" table
   (process instrumentation + vibration placement, ~28 sensors) — do not invent
   positions for the PDF's "Unlocated channels" list (`PT_110A/B`, `PT_153`, `PT_201/253`,
   `RTD_219A/B`, `RTD_220/221`, `RTD_200-205`, `Dyno Water O/L`); route those to a
   separate "Auxiliary" panel instead, per the PDF's explicit warning against fabricating
   engineering placement.
2. Instantiate one repeated marker mesh/HTML-GUI-label per sensor (per PDF performance
   rule: "instantiate repeated markers instead of creating unique meshes").
3. Hover: enlarge marker, highlight leader line to its component, show ID/value/unit/
   quality/timestamp; sparkline only if history is already loaded (don't fetch on hover).
4. Click: lock selection, open a sensor detail drawer (current value, limits, recent
   trend, min/max, related sensors, latest alarms) — this is also where item 5's
   dashboard-state hook can attach a `sensor` state.
5. Only render markers relevant to the currently isolated component group (ties into the
   existing `t3dSelectGroup`), to avoid 28 permanent labels cluttering the full-rig view —
   matches both `override.md`'s "keep labels concise" and the PDF's "contextual labels
   that appear only at relevant zoom levels."

**Done when:** hovering/clicking a sensor marker on an isolated component shows live
value+metadata, and unlocated sensors are visibly separated into an auxiliary group
rather than guessed onto the model.

---

## 9. Frontier items — placeholders (all three)

**Current state / why full versions are blocked:**
- True vibration orbit needs synchronized dual-channel high-rate waveform data plus a
  tachometer/keyphasor reference; the pipeline only produces scalar 1 Hz RMS values.
- True historical 3D replay needs sub-minute timestamp resolution; the PDF's own review
  of the source CSV found ~3,589 samples compressed into ~1 hour of minute-precision
  timestamps, and confirmed no fix has been applied.
- CAD cutaway/exploded views need actually-authored alternate 3D geometry — a modeling
  task, not a data or code problem.

**Placeholder steps (approved — all three):**
1. **Orbit plot honesty label:** add a persistent badge/tooltip to `turbine_orbit_plot`
   (e.g. "Illustrative — RMS-derived, not phase-resolved") so it can't be read as a real
   shaft orbit. Trivial CSS/HTML change to the existing widget.
2. **Non-3D-synced history replay:** add a simple time-range scrub over already-ingested
   IoTDB history feeding the *existing* native trend charts only (no 3D-state sync, no
   new timestamp-precision work). Reuses the replay-server's existing
   `record_idx`/status API rather than building a new replay controller. Clearly label
   this view "Historical" vs. "Live" per the PDF's explicit requirement.
3. **One hand-authored exploded-view GLB variant:** manually offset 2-3 meshes (e.g.
   `Gearbox.001`, `Dyno.001`) along an axis in the GLB source, export as a second model
   state, and add a toggle button that swaps `modelUrl`/camera preset between normal and
   exploded. Not a true clipping-plane cutaway — an alternate static model.

**Done when:** all three are visibly present and clearly labeled as illustrative, without
claiming capabilities the underlying data/assets don't support.

---

## 10. Real-GPU frame rate measurement

**Current state:** confirmed — two NVIDIA RTX 4090 GPUs are available on this machine.
The prior ~20 fps figure was measured on a virtualized/headless GPU context.

**Steps:**
1. Open the Babylon dashboard in a real (non-headless) Chromium/Firefox session on this
   machine, with GPU acceleration confirmed on (check `chrome://gpu` or equivalent).
2. Use Babylon's built-in FPS counter (`scene.getEngine().getFps()`) or the browser's
   performance overlay; record steady-state FPS over ~30s with the full 15-mesh scene +
   particles running.
3. Record the number and hardware (RTX 4090, non-virtualized) in the verification report
   or a follow-up note — this replaces the "unactionable without different hardware"
   status.

**Done when:** a real FPS number is recorded on non-virtualized hardware.

---

## 11 & 12. On hold (per your instruction — no action)

- IoTDB continuous queries/TTL (Phase 4.1), ML anomaly detection (Phase 5.1), TLS/SSL
  hardening (Phase 5.2), multi-turbine fleet scaling (Phase 6).
- Telemetry-latency re-measurement, threshold-configurator `SHARED_SCOPE` persistence
  confirmation.

No steps taken; carried forward as explicitly deferred.

---

## Additional items surfaced only by the PDF (not in the original 12, for awareness)

Not scheduled yet — flagging so they aren't lost:

- **Timestamp resolution fix**: source CSV/IoTDB timestamps are minute-precision despite
  ~3,589 samples/hour — blocks any real historical replay (feeds directly into item 9's
  full version, if ever revisited).
- **Unit confirmation needed**: `GB_TRQ` (N·m in PDF vs kN·m in CSV) and vibration units
  (`mils` per PDF/CSV, but UI should keep the source label until instrumentation docs
  confirm) — both currently assumed, not verified against instrumentation documentation.
- **Alarm limits are inferred, not sourced** from approved test specifications — the PDF
  flags this as a correctness risk, not just a nice-to-have.
- **No dyno-power channel** exists in the CSV despite the schematic implying one; do not
  fabricate a calculated power value without confirming gearbox ratio and measurement
  location.
- **Auxiliary/unassigned sensor panel** (`PT_110A/B`, `PT_153`, `PT_201/253`, `RTD_219A/B`,
  `RTD_220/221`, `RTD_200-205`, `Dyno Water O/L`) — referenced above in item 8's plan as
  where these should land, but the panel itself doesn't exist yet as a dashboard state.

---

## Summary checklist for handoff

| # | Item | Action | Blocked on |
|---|---|---|---|
| 1 | Orbit widget | Redeploy + verify live | none |
| 2/4 | Nav/scrubber | Delete builder code | none |
| 3 | Unified 3-in-1 backup | Closed, already gone | — |
| 5 | Babylon state sync | Implement `actionsApi`/`stateController` hook | none |
| 6 | Settings-editor UI | Build minimal custom form | reproduce TB 4.3 bug first |
| 7 | Regression tests + CI | New Playwright suite + GH Action | none |
| 8 | Sensor-marker layer | Implement per PDF spec | none |
| 9 | Frontier placeholders | 3 lightweight versions | none |
| 10 | GPU frame rate | Measure on RTX 4090 | none |
| 11 | Phase 4-6 items | On hold | user hold |
| 12 | Latency/persistence | On hold | user hold |
