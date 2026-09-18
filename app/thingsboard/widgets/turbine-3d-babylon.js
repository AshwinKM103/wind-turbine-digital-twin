/**
 * Babylon.js 3D turbine digital-twin widget for ThingsBoard.
 * Renders GLB model with telemetry-driven shaft rotation, particle flow,
 * actuator motion, health-score mesh coloring, and component isolation mode.
 */

// Template (HTML) packaged into descriptor.templateHtml
const TEMPLATE_HTML = `
<div class="t3d-root" id="t3d-root">
  <canvas class="t3d-canvas" id="t3d-canvas" touch-action="none"></canvas>
  <div class="t3d-overlay t3d-loading" id="t3d-loading">
    <div class="t3d-spinner"></div>
    <div class="t3d-loading-text">Loading turbine model&hellip;</div>
  </div>
  <div class="t3d-overlay t3d-error" id="t3d-error" hidden>
    <div class="t3d-error-text" id="t3d-error-text">Model failed to load.</div>
  </div>
  <div class="t3d-hud" id="t3d-hud" hidden>
    <button class="t3d-hud-close" id="t3d-hud-close" aria-label="Close">&times;</button>
    <div class="t3d-hud-title" id="t3d-hud-title"></div>
    <div class="t3d-hud-mesh" id="t3d-hud-mesh"></div>
    <div class="t3d-hud-row"><span>Health score</span><span id="t3d-hud-score"></span></div>
    <div class="t3d-hud-row"><span>Active alerts</span><span id="t3d-hud-alerts"></span></div>
    <div class="t3d-hud-divider" id="t3d-hud-sensor-divider" hidden></div>
    <div class="t3d-hud-sensor-title" id="t3d-hud-sensor-title" hidden></div>
    <div class="t3d-hud-row" id="t3d-hud-live-row" hidden><span>Live value</span><span id="t3d-hud-live"></span></div>
    <div class="t3d-hud-limits" id="t3d-hud-limits" hidden>
      <div class="t3d-hud-limit-track" id="t3d-hud-limit-track">
        <div class="t3d-hud-limit-fill" id="t3d-hud-limit-fill"></div>
        <div class="t3d-hud-limit-marker t3d-hud-limit-warn" id="t3d-hud-limit-warn-marker"></div>
        <div class="t3d-hud-limit-marker t3d-hud-limit-alarm" id="t3d-hud-limit-alarm-marker"></div>
      </div>
      <div class="t3d-hud-row t3d-hud-row-small">
        <span>Warn <b id="t3d-hud-warn-val"></b></span>
        <span>Alarm <b id="t3d-hud-alarm-val"></b></span>
        <span>Critical <b id="t3d-hud-critical-val"></b></span>
      </div>
    </div>
  </div>
  <div class="t3d-hover-tip" id="t3d-hover-tip" hidden></div>
  <div class="t3d-status-labels" id="t3d-status-labels"></div>
  <div class="t3d-sensor-markers" id="t3d-sensor-markers"></div>

  <!-- Top toolbar actions -->
  <div class="t3d-top-actions">
    <button class="t3d-icon-btn" id="t3d-btn-settings" type="button" title="Widget Settings (Model URL & Camera Presets)">⚙️ Settings</button>
    <button class="t3d-icon-btn" id="t3d-btn-aux" type="button" title="Auxiliary / Unlocated Channels (17)">📋 Auxiliary (17)</button>
  </div>

  <!-- Floating Sensor Detail Drawer -->
  <div class="t3d-sensor-drawer" id="t3d-sensor-drawer" hidden>
    <button class="t3d-hud-close" id="t3d-sensor-close" aria-label="Close">&times;</button>
    <div class="t3d-sensor-badge-row">
      <span class="t3d-sensor-status-tag" id="t3d-sensor-status-tag">NORMAL</span>
      <span class="t3d-sensor-tier" id="t3d-sensor-tier">PRIMARY</span>
    </div>
    <div class="t3d-sensor-title" id="t3d-sensor-id"></div>
    <div class="t3d-sensor-sub" id="t3d-sensor-name"></div>
    <div class="t3d-sensor-mesh" id="t3d-sensor-mesh"></div>
    <div class="t3d-sensor-reading-box">
      <span class="t3d-sensor-val" id="t3d-sensor-val">--</span>
      <span class="t3d-sensor-unit" id="t3d-sensor-unit"></span>
    </div>
    <div class="t3d-hud-divider"></div>
    <div class="t3d-hud-limits" id="t3d-sensor-limits">
      <div class="t3d-hud-limit-track">
        <div class="t3d-hud-limit-fill" id="t3d-sensor-limit-fill"></div>
      </div>
      <div class="t3d-hud-row t3d-hud-row-small">
        <span>Warn: <b id="t3d-sensor-warn-val"></b></span>
        <span>Alarm: <b id="t3d-sensor-alarm-val"></b></span>
        <span>Crit: <b id="t3d-sensor-crit-val"></b></span>
      </div>
    </div>
  </div>

  <!-- Auxiliary & Unlocated Instrumentation Drawer -->
  <div class="t3d-aux-drawer" id="t3d-aux-drawer" hidden>
    <div class="t3d-aux-header">
      <span class="t3d-aux-title">📋 Auxiliary Instrumentation</span>
      <button class="t3d-hud-close" id="t3d-aux-close" aria-label="Close">&times;</button>
    </div>
    <div class="t3d-aux-note">
      ⚠️ 17 channels without verified 3D CAD or P&amp;ID locations per research report. Displayed as auxiliary list to prevent false engineering placement.
    </div>
    <div class="t3d-aux-list" id="t3d-aux-list"></div>
  </div>

  <!-- In-widget Minimal Settings Editor Modal -->
  <div class="t3d-modal" id="t3d-settings-modal" hidden>
    <div class="t3d-modal-backdrop" id="t3d-settings-backdrop"></div>
    <div class="t3d-modal-card">
      <div class="t3d-modal-header">
        <span class="t3d-modal-title">⚙️ 3D Digital Twin Settings</span>
        <button class="t3d-modal-close" id="t3d-settings-close" type="button">&times;</button>
      </div>
      <div class="t3d-modal-body">
        <div class="t3d-form-group">
          <label class="t3d-form-label" for="t3d-set-model-url">Model GLB Resource URL</label>
          <input type="text" id="t3d-set-model-url" class="t3d-form-input" placeholder="/api/resource/general/tenant/turbine_rig_prototype.glb">
        </div>
        <div class="t3d-form-section">Camera Orbit Position</div>
        <div class="t3d-form-row">
          <div class="t3d-form-group">
            <label class="t3d-form-label" for="t3d-set-cam-alpha">Alpha (rad)</label>
            <input type="number" step="0.05" id="t3d-set-cam-alpha" class="t3d-form-input">
          </div>
          <div class="t3d-form-group">
            <label class="t3d-form-label" for="t3d-set-cam-beta">Beta (rad)</label>
            <input type="number" step="0.05" id="t3d-set-cam-beta" class="t3d-form-input">
          </div>
          <div class="t3d-form-group">
            <label class="t3d-form-label" for="t3d-set-cam-radius">Radius</label>
            <input type="number" step="0.5" id="t3d-set-cam-radius" class="t3d-form-input">
          </div>
        </div>
        <div class="t3d-form-section">Camera Target Focal Center (X, Y, Z)</div>
        <div class="t3d-form-row">
          <div class="t3d-form-group">
            <label class="t3d-form-label" for="t3d-set-cam-tx">Target X</label>
            <input type="number" step="0.1" id="t3d-set-cam-tx" class="t3d-form-input">
          </div>
          <div class="t3d-form-group">
            <label class="t3d-form-label" for="t3d-set-cam-ty">Target Y</label>
            <input type="number" step="0.1" id="t3d-set-cam-ty" class="t3d-form-input">
          </div>
          <div class="t3d-form-group">
            <label class="t3d-form-label" for="t3d-set-cam-tz">Target Z</label>
            <input type="number" step="0.1" id="t3d-set-cam-tz" class="t3d-form-input">
          </div>
        </div>
        <div class="t3d-form-actions-inline">
          <button type="button" class="t3d-btn-sec" id="t3d-btn-capture-cam">📷 Capture Current View</button>
        </div>
      </div>
      <div class="t3d-modal-footer">
        <button type="button" class="t3d-btn-sec" id="t3d-btn-settings-cancel">Cancel</button>
        <button type="button" class="t3d-btn-pri" id="t3d-btn-settings-save">Save & Apply</button>
      </div>
    </div>
  </div>
</div>
`;

// Style (CSS) packaged into descriptor.templateCss
const TEMPLATE_CSS = `
.t3d-root { position: relative; width: 100%; height: 100%; background: #0b1120; overflow: hidden; }
.t3d-canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; outline: none; }

/* Status tags floating above WARNING/ALARM components. */
.t3d-status-labels { position: absolute; inset: 0; pointer-events: none; z-index: 5; }
.t3d-status-tag {
  position: absolute; transform: translate(-50%, -100%);
  font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 4px;
  color: #fff; white-space: nowrap; pointer-events: none;
  font-family: Roboto, Arial, sans-serif; letter-spacing: 0.02em;
}
.t3d-status-tag.t3d-status-warning { background: rgba(245,158,11,.85); }
.t3d-status-tag.t3d-status-alarm { background: rgba(239,68,68,.85); }

.t3d-overlay {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px;
  color: rgba(255,255,255,0.87); font-family: Roboto, Arial, sans-serif;
  pointer-events: none; background: rgba(11,17,32,0.85);
}
/* Placed after .t3d-overlay to ensure [hidden] overrides flex display. */
.t3d-overlay[hidden], .t3d-hud[hidden] { display: none; }
.t3d-spinner {
  width: 28px; height: 28px; border-radius: 50%;
  border: 3px solid rgba(255,255,255,0.15); border-top-color: #38bdf8;
  animation: t3d-spin 0.9s linear infinite;
}
@keyframes t3d-spin { to { transform: rotate(360deg); } }
.t3d-loading-text, .t3d-error-text { font-size: 12px; opacity: 0.8; }
.t3d-error { background: rgba(30,10,10,0.85); }
.t3d-error-text { color: #fca5a5; }

.t3d-hud {
  position: absolute; top: 12px; right: 12px; min-width: 230px; max-width: 260px;
  background: #0f172a; border: 1px solid #334155; border-radius: 8px;
  padding: 10px 12px; color: #f8fafc; font-family: Roboto, Arial, sans-serif;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}
.t3d-hud-title { font-size: 13px; font-weight: 700; color: #38bdf8; padding-right: 16px; }
.t3d-hud-mesh { font-size: 11px; color: #94a3b8; margin-top: 2px; margin-bottom: 6px; }
.t3d-hud-row { display: flex; justify-content: space-between; font-size: 12px; margin-top: 3px; }
.t3d-hud-row-small { font-size: 10px; color: #94a3b8; }
.t3d-hud-row-small b { color: #e2e8f0; font-weight: 600; }
.t3d-hud-close {
  position: absolute; top: 6px; right: 8px; background: transparent; border: none;
  color: #94a3b8; font-size: 14px; cursor: pointer; line-height: 1;
}
.t3d-hud-close:hover { color: #f8fafc; }
.t3d-hud-divider { height: 1px; background: #334155; margin: 8px 0 6px; }
.t3d-hud-sensor-title { font-size: 11px; font-weight: 600; color: #cbd5e1; margin-bottom: 4px; }
.t3d-hud-limits { margin-top: 6px; }
.t3d-hud-limit-track {
  position: relative; height: 6px; border-radius: 3px; margin: 6px 0 4px;
  background: linear-gradient(to right, #10b981 0%, #10b981 55%, #f59e0b 55%, #f59e0b 78%, #ef4444 78%, #ef4444 100%);
}
.t3d-hud-limit-fill {
  position: absolute; top: -3px; width: 2px; height: 12px; background: #f8fafc;
  border-radius: 1px; left: 0%;
}
.t3d-hud-limit-marker { display: none; }

/* Transient hover tooltip positioned via pointer coordinates. */
.t3d-hover-tip {
  position: absolute; pointer-events: none; z-index: 5;
  background: rgba(15,23,42,0.92); border: 1px solid #334155; border-radius: 6px;
  padding: 5px 9px; font-size: 11px; color: #f8fafc; font-family: Roboto, Arial, sans-serif;
  white-space: nowrap; transform: translate(12px, -50%);
}
.t3d-hover-tip[hidden] { display: none; }

/* Settings toolbar and modal dialog */
.t3d-top-actions {
  position: absolute; top: 12px; left: 12px; display: flex; gap: 8px; z-index: 10;
}
.t3d-icon-btn {
  background: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 6px;
  color: #94a3b8; font-size: 11px; font-weight: 600; padding: 5px 10px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 5px; transition: all 0.15s;
}
.t3d-icon-btn:hover { background: #1e293b; color: #38bdf8; border-color: #38bdf8; }
.t3d-icon-btn.t3d-active { background: #0284c7; color: #fff; border-color: #38bdf8; }
.t3d-modal {
  position: absolute; inset: 0; z-index: 30; display: flex; align-items: center; justify-content: center;
}
.t3d-modal[hidden] { display: none; }
.t3d-modal-backdrop {
  position: absolute; inset: 0; background: rgba(0, 0, 0, 0.65); backdrop-filter: blur(2px);
}
.t3d-modal-card {
  position: relative; z-index: 31; background: #0f172a; border: 1px solid #334155;
  border-radius: 10px; width: 440px; max-width: 90%; box-shadow: 0 16px 36px rgba(0,0,0,0.6);
  color: #f8fafc; font-family: Roboto, Arial, sans-serif; overflow: hidden;
}
.t3d-modal-header {
  display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;
  border-bottom: 1px solid #1e293b; background: #090d16;
}
.t3d-modal-title { font-size: 13px; font-weight: 700; color: #38bdf8; }
.t3d-modal-close {
  background: transparent; border: none; color: #94a3b8; font-size: 18px; cursor: pointer; line-height: 1;
}
.t3d-modal-close:hover { color: #f8fafc; }
.t3d-modal-body { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.t3d-form-group { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.t3d-form-label { font-size: 11px; color: #94a3b8; font-weight: 500; }
.t3d-form-input {
  background: #1e293b; border: 1px solid #334155; border-radius: 5px; color: #f8fafc;
  padding: 6px 10px; font-size: 12px; font-family: monospace; outline: none;
}
.t3d-form-input:focus { border-color: #38bdf8; box-shadow: 0 0 6px rgba(56,189,248,0.25); }
.t3d-form-section { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b; margin-top: 4px; }
.t3d-form-row { display: flex; gap: 8px; }
.t3d-form-actions-inline { display: flex; justify-content: flex-end; margin-top: 4px; }
.t3d-modal-footer {
  display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding: 10px 16px;
  border-top: 1px solid #1e293b; background: #090d16;
}
.t3d-btn-sec {
  background: #1e293b; border: 1px solid #334155; color: #cbd5e1; padding: 5px 12px;
  border-radius: 5px; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.15s;
}
.t3d-btn-sec:hover { background: #334155; color: #fff; border-color: #475569; }
.t3d-btn-pri {
  background: #0284c7; border: 1px solid #38bdf8; color: #fff; padding: 5px 14px;
  border-radius: 5px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.15s;
}
.t3d-btn-pri:hover { background: #0369a1; }

/* Floating sensor marker pins */
.t3d-sensor-markers { position: absolute; inset: 0; pointer-events: none; z-index: 8; }
.t3d-sensor-pin {
  position: absolute; transform: translate(-50%, -50%);
  display: inline-flex; align-items: center; gap: 4px;
  background: rgba(15, 23, 42, 0.92); border: 1px solid #334155; border-radius: 12px;
  padding: 2px 7px; color: #f8fafc; font-family: Roboto, Arial, sans-serif;
  font-size: 10px; font-weight: 600; cursor: pointer; pointer-events: auto;
  box-shadow: 0 2px 8px rgba(0,0,0,0.5); transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
  user-select: none;
}
.t3d-sensor-pin:hover {
  transform: translate(-50%, -50%) scale(1.15);
  border-color: #38bdf8; box-shadow: 0 0 10px rgba(56,189,248,0.5); z-index: 15;
}
.t3d-sensor-pin-dot { width: 6px; height: 6px; border-radius: 50%; }
.t3d-pin-normal .t3d-sensor-pin-dot { background: #10b981; }
.t3d-pin-normal { border-color: #10b981; }
.t3d-pin-warning .t3d-sensor-pin-dot { background: #f59e0b; }
.t3d-pin-warning { border-color: #f59e0b; background: rgba(30, 25, 15, 0.95); }
.t3d-pin-alarm .t3d-sensor-pin-dot { background: #ef4444; }
.t3d-pin-alarm { border-color: #ef4444; background: rgba(35, 15, 15, 0.95); }

/* Sensor Detail Drawer */
.t3d-sensor-drawer {
  position: absolute; bottom: 16px; left: 16px; width: 260px;
  background: #0f172a; border: 1px solid #38bdf8; border-radius: 8px;
  padding: 12px; color: #f8fafc; font-family: Roboto, Arial, sans-serif;
  box-shadow: 0 8px 28px rgba(0,0,0,0.6); z-index: 25;
}
.t3d-sensor-drawer[hidden] { display: none; }
.t3d-sensor-badge-row { display: flex; gap: 6px; margin-bottom: 6px; }
.t3d-sensor-status-tag {
  font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 4px;
  background: #10b981; color: #fff; text-transform: uppercase;
}
.t3d-sensor-status-tag.status-warning { background: #f59e0b; }
.t3d-sensor-status-tag.status-alarm { background: #ef4444; }
.t3d-sensor-tier {
  font-size: 9px; font-weight: 600; padding: 1px 5px; border-radius: 4px;
  background: #334155; color: #94a3b8;
}
.t3d-sensor-title { font-size: 14px; font-weight: 700; color: #38bdf8; }
.t3d-sensor-sub { font-size: 11px; color: #cbd5e1; margin-top: 2px; }
.t3d-sensor-mesh { font-size: 10px; color: #94a3b8; margin-top: 2px; font-family: monospace; }
.t3d-sensor-reading-box {
  display: flex; align-items: baseline; gap: 6px; margin-top: 8px;
}
.t3d-sensor-val { font-size: 22px; font-weight: 700; color: #fff; font-family: monospace; }
.t3d-sensor-unit { font-size: 12px; color: #94a3b8; }

/* Auxiliary Drawer */
.t3d-aux-drawer {
  position: absolute; top: 48px; left: 12px; bottom: 16px; width: 320px;
  background: #0f172a; border: 1px solid #334155; border-radius: 8px;
  padding: 12px; color: #f8fafc; font-family: Roboto, Arial, sans-serif;
  box-shadow: 0 12px 32px rgba(0,0,0,0.6); z-index: 22; display: flex; flex-direction: column;
}
.t3d-aux-drawer[hidden] { display: none; }
.t3d-aux-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.t3d-aux-title { font-size: 12px; font-weight: 700; color: #38bdf8; }
.t3d-aux-note {
  font-size: 10px; color: #f59e0b; background: rgba(245,158,11,0.1);
  border: 1px solid rgba(245,158,11,0.25); border-radius: 4px; padding: 6px 8px;
  line-height: 1.35; margin-bottom: 10px;
}
.t3d-aux-list { overflow-y: auto; display: flex; flex-direction: column; gap: 6px; flex: 1; padding-right: 4px; }
.t3d-aux-item {
  background: #1e293b; border: 1px solid #334155; border-radius: 6px;
  padding: 7px 10px; display: flex; align-items: center; justify-content: space-between;
  cursor: pointer; transition: all 0.15s;
}
.t3d-aux-item:hover { background: #243248; border-color: #38bdf8; }
.t3d-aux-item-id { font-size: 11px; font-weight: 600; color: #38bdf8; font-family: monospace; }
.t3d-aux-item-name { font-size: 10px; color: #94a3b8; margin-top: 1px; }
.t3d-aux-item-reading { text-align: right; }
.t3d-aux-item-val { font-size: 12px; font-weight: 700; color: #f8fafc; font-family: monospace; }
.t3d-aux-item-unit { font-size: 9px; color: #94a3b8; margin-left: 2px; }
`;

// Controller (JS) packaged into descriptor.controllerScript
// CONTROLLER_SCRIPT_START

// Confirmed Sensor Markers mapped outside the GLB per research report.
var T3D_SENSOR_MARKERS = [
  // Inlet Steam Subsystem (inlet)
  { sensorId: "PT_109A", sourceKey: "PT_109A", displayName: "Main Steam Pressure", units: "bar", system: "inlet", componentNode: "SteamAdmission.001", offset: { x: -0.3, y: 0.6, z: 0.2 }, displayTier: "primary", warningLimit: 35.0, alarmLimit: 38.0, criticalLimit: 41.0 },
  { sensorId: "TT_109A", sourceKey: "TT_109A", displayName: "Main Steam Temperature", units: "°C", system: "inlet", componentNode: "SteamAdmission.001", offset: { x: 0.3, y: 0.6, z: 0.2 }, displayTier: "primary", warningLimit: 300.0, alarmLimit: 350.0, criticalLimit: 400.0 },
  { sensorId: "FT_110A", sourceKey: "FT_110A", displayName: "Main Steam Mass Flow", units: "TPH", system: "inlet", componentNode: "SteamAdmission.001", offset: { x: 0.0, y: 0.9, z: 0.0 }, displayTier: "primary", warningLimit: 25.0, alarmLimit: 30.0, criticalLimit: 35.0 },
  { sensorId: "PT_111B", sourceKey: "PT_111B", displayName: "Emergency Stop Valve (ESV) Pressure", units: "bar", system: "inlet", componentNode: "SteamAdmission.002", offset: { x: 0.0, y: 0.5, z: 0.2 }, displayTier: "secondary", warningLimit: 35.0, alarmLimit: 37.0, criticalLimit: 39.0 },
  { sensorId: "PT_111", sourceKey: "PT_111", displayName: "Throttle Valve 1 (TV1) Pressure", units: "bar", system: "inlet", componentNode: "SteamAdmission.003", offset: { x: -0.25, y: 0.5, z: 0.15 }, displayTier: "secondary", warningLimit: 10.0, alarmLimit: 13.0, criticalLimit: 16.0 },
  { sensorId: "TT_111", sourceKey: "TT_111", displayName: "Throttle Valve 1 (TV1) Temperature", units: "°C", system: "inlet", componentNode: "SteamAdmission.003", offset: { x: 0.25, y: 0.5, z: 0.15 }, displayTier: "secondary", warningLimit: 300.0, alarmLimit: 350.0, criticalLimit: 400.0 },
  { sensorId: "PT_112", sourceKey: "PT_112", displayName: "Throttle Valve 2 (TV2) Pressure", units: "bar", system: "inlet", componentNode: "SteamAdmission.004", offset: { x: -0.25, y: 0.5, z: 0.15 }, displayTier: "secondary", warningLimit: 3.0, alarmLimit: 4.0, criticalLimit: 5.0 },
  { sensorId: "TT_112", sourceKey: "TT_112", displayName: "Throttle Valve 2 (TV2) Temperature", units: "°C", system: "inlet", componentNode: "SteamAdmission.004", offset: { x: 0.25, y: 0.5, z: 0.15 }, displayTier: "secondary", warningLimit: 300.0, alarmLimit: 350.0, criticalLimit: 400.0 },

  // Turbine Subsystem (turbine)
  { sensorId: "PT_120", sourceKey: "PT_120", displayName: "Wheel Case Pressure", units: "bar", system: "turbine", componentNode: "Turbine.002", offset: { x: 0.0, y: 0.5, z: 0.2 }, displayTier: "secondary", warningLimit: 3.0, alarmLimit: 4.0, criticalLimit: 5.0 },
  { sensorId: "TT_120_R", sourceKey: "TT_120_R", displayName: "Wheel Case Temperature", units: "°C", system: "turbine", componentNode: "Turbine.002", offset: { x: 0.0, y: 0.5, z: -0.2 }, displayTier: "secondary", warningLimit: 300.0, alarmLimit: 350.0, criticalLimit: 400.0 },
  { sensorId: "PT_111C", sourceKey: "PT_111C", displayName: "Intermediate GBC Pressure", units: "bar", system: "turbine", componentNode: "Turbine.003", offset: { x: 0.0, y: 0.4, z: 0.2 }, displayTier: "secondary", warningLimit: 0.9, alarmLimit: 1.1, criticalLimit: 1.3 },
  { sensorId: "TT_111C", sourceKey: "TT_111C", displayName: "Intermediate GBC Temperature", units: "°C", system: "turbine", componentNode: "Turbine.003", offset: { x: 0.0, y: 0.4, z: -0.2 }, displayTier: "secondary", warningLimit: 300.0, alarmLimit: 350.0, criticalLimit: 400.0 },
  { sensorId: "ZT_600", sourceKey: "ZT_600", displayName: "Turbine Axial Top Vibration", units: "mils", system: "turbine", componentNode: "Turbine.001", offset: { x: -0.5, y: 0.6, z: 0.0 }, displayTier: "primary", warningLimit: 3.0, alarmLimit: 4.5, criticalLimit: 6.0 },
  { sensorId: "ZT_601", sourceKey: "ZT_601", displayName: "Turbine Axial Bottom Vibration", units: "mils", system: "turbine", componentNode: "Turbine.001", offset: { x: -0.5, y: -0.5, z: 0.0 }, displayTier: "primary", warningLimit: 3.0, alarmLimit: 4.5, criticalLimit: 6.0 },
  { sensorId: "XT_600", sourceKey: "XT_600", displayName: "Turbine Radial Station 1 X", units: "mils", system: "turbine", componentNode: "Turbine.001", offset: { x: -0.2, y: 0.45, z: 0.35 }, displayTier: "primary", warningLimit: 4.5, alarmLimit: 6.0, criticalLimit: 7.5 },
  { sensorId: "XT_601", sourceKey: "XT_601", displayName: "Turbine Radial Station 1 Y", units: "mils", system: "turbine", componentNode: "Turbine.001", offset: { x: -0.2, y: 0.45, z: -0.35 }, displayTier: "primary", warningLimit: 4.5, alarmLimit: 6.0, criticalLimit: 7.5 },
  { sensorId: "XT_602", sourceKey: "XT_602", displayName: "Turbine Radial Station 2 X", units: "mils", system: "turbine", componentNode: "Turbine.001", offset: { x: 0.2, y: 0.45, z: 0.35 }, displayTier: "primary", warningLimit: 4.5, alarmLimit: 6.0, criticalLimit: 7.5 },
  { sensorId: "XT_603", sourceKey: "XT_603", displayName: "Turbine Radial Station 2 Y", units: "mils", system: "turbine", componentNode: "Turbine.001", offset: { x: 0.2, y: 0.45, z: -0.35 }, displayTier: "primary", warningLimit: 4.5, alarmLimit: 6.0, criticalLimit: 7.5 },
  { sensorId: "PYRO_T", sourceKey: "PYRO_T", displayName: "Turbine Rotor Pyrometer", units: "°C", system: "turbine", componentNode: "Turbine.001", offset: { x: 0.0, y: 0.7, z: 0.0 }, displayTier: "primary", warningLimit: 33.0, alarmLimit: 41.0, criticalLimit: 49.0 },

  // Gearbox Subsystem (gearbox)
  { sensorId: "XT_604", sourceKey: "XT_604", displayName: "Gearbox Radial Station 1 X", units: "mils", system: "gearbox", componentNode: "Gearbox.001", offset: { x: -0.3, y: 0.4, z: 0.35 }, displayTier: "primary", warningLimit: 4.0, alarmLimit: 5.5, criticalLimit: 7.0 },
  { sensorId: "XT_605", sourceKey: "XT_605", displayName: "Gearbox Radial Station 1 Y", units: "mils", system: "gearbox", componentNode: "Gearbox.001", offset: { x: -0.3, y: 0.4, z: -0.35 }, displayTier: "primary", warningLimit: 4.0, alarmLimit: 5.5, criticalLimit: 7.0 },
  { sensorId: "XT_606", sourceKey: "XT_606", displayName: "Gearbox Radial Station 2 X", units: "mils", system: "gearbox", componentNode: "Gearbox.001", offset: { x: 0.3, y: 0.4, z: 0.35 }, displayTier: "primary", warningLimit: 4.0, alarmLimit: 5.5, criticalLimit: 7.0 },
  { sensorId: "XT_607", sourceKey: "XT_607", displayName: "Gearbox Radial Station 2 Y", units: "mils", system: "gearbox", componentNode: "Gearbox.001", offset: { x: 0.3, y: 0.4, z: -0.35 }, displayTier: "primary", warningLimit: 4.0, alarmLimit: 5.5, criticalLimit: 7.0 },
  { sensorId: "PYRO_GB", sourceKey: "PYRO_GB", displayName: "Gearbox Pyrometer", units: "°C", system: "gearbox", componentNode: "Gearbox.001", offset: { x: 0.0, y: 0.55, z: 0.0 }, displayTier: "primary", warningLimit: 40.0, alarmLimit: 50.0, criticalLimit: 60.0 },
  { sensorId: "GB_TRQ", sourceKey: "GB_TRQ", displayName: "Gearbox Shaft Torque", units: "kN·m", system: "gearbox", componentNode: "Gearbox.001", offset: { x: 0.0, y: -0.35, z: 0.3 }, displayTier: "primary", warningLimit: 8.0, alarmLimit: 10.0, criticalLimit: 12.0 },

  // Dynamometer Subsystem (dyno)
  { sensorId: "PT_253", sourceKey: "PT_253", displayName: "Dyno Inlet Pressure", units: "bar", system: "dyno", componentNode: "Dyno.001", offset: { x: 0.0, y: 0.5, z: 0.2 }, displayTier: "primary", warningLimit: 26.0, alarmLimit: 29.0, criticalLimit: 32.0 },

  // Exhaust Subsystem (exhaust)
  { sensorId: "PT_150A", sourceKey: "PT_150A", displayName: "Exhaust Pressure A", units: "bar", system: "exhaust", componentNode: "Exhaust.001", offset: { x: -0.2, y: 0.3, z: 0.15 }, displayTier: "auxiliary", warningLimit: 0.20, alarmLimit: 0.25, criticalLimit: 0.30 },
  { sensorId: "TT_150A", sourceKey: "TT_150A", displayName: "Exhaust Temp A", units: "°C", system: "exhaust", componentNode: "Exhaust.001", offset: { x: 0.2, y: 0.3, z: 0.15 }, displayTier: "auxiliary", warningLimit: 300.0, alarmLimit: 350.0, criticalLimit: 400.0 },

  // Gland Leakage Subsystem (leakage)
  { sensorId: "PT_162", sourceKey: "PT_162", displayName: "Leakage 1 Pressure", units: "bar", system: "leakage", componentNode: "Leakage.001", offset: { x: -0.2, y: 0.3, z: 0.1 }, displayTier: "auxiliary", warningLimit: 2.0, alarmLimit: 3.0, criticalLimit: 4.0 },
  { sensorId: "TT_162", sourceKey: "TT_162", displayName: "Leakage 1 Temp", units: "°C", system: "leakage", componentNode: "Leakage.001", offset: { x: 0.2, y: 0.3, z: 0.1 }, displayTier: "auxiliary", warningLimit: 250.0, alarmLimit: 300.0, criticalLimit: 350.0 },
  { sensorId: "FT_162", sourceKey: "FT_162", displayName: "Leakage 1 Mass Flow", units: "TPH", system: "leakage", componentNode: "Leakage.001", offset: { x: 0.0, y: 0.5, z: 0.0 }, displayTier: "auxiliary", warningLimit: 0.8, alarmLimit: 1.5, criticalLimit: 2.2 },
  { sensorId: "PT_161", sourceKey: "PT_161", displayName: "Leakage 2 Pressure", units: "bar", system: "leakage", componentNode: "Leakage.002", offset: { x: 0.0, y: 0.3, z: 0.1 }, displayTier: "auxiliary", warningLimit: 2.0, alarmLimit: 3.0, criticalLimit: 4.0 },
  { sensorId: "TT_161", sourceKey: "TT_161", displayName: "Leakage 2 Temp", units: "°C", system: "leakage", componentNode: "Leakage.002", offset: { x: 0.0, y: 0.3, z: -0.1 }, displayTier: "auxiliary", warningLimit: 250.0, alarmLimit: 300.0, criticalLimit: 350.0 },
  { sensorId: "PT_160", sourceKey: "PT_160", displayName: "Leakage 3 Upstream Press", units: "bar", system: "leakage", componentNode: "Leakage.003", offset: { x: 0.0, y: 0.3, z: 0.1 }, displayTier: "auxiliary", warningLimit: 2.0, alarmLimit: 3.0, criticalLimit: 4.0 },
  { sensorId: "TT_160", sourceKey: "TT_160", displayName: "Leakage 3 Upstream Temp", units: "°C", system: "leakage", componentNode: "Leakage.003", offset: { x: 0.0, y: 0.3, z: -0.1 }, displayTier: "auxiliary", warningLimit: 250.0, alarmLimit: 300.0, criticalLimit: 350.0 },
  { sensorId: "PT_163", sourceKey: "PT_163", displayName: "Leakage 3 Downstream Press", units: "bar", system: "leakage", componentNode: "Leakage.004", offset: { x: 0.0, y: 0.3, z: 0.1 }, displayTier: "auxiliary", warningLimit: 2.0, alarmLimit: 3.0, criticalLimit: 4.0 },
  { sensorId: "TT_163", sourceKey: "TT_163", displayName: "Leakage 3 Downstream Temp", units: "°C", system: "leakage", componentNode: "Leakage.004", offset: { x: 0.0, y: 0.3, z: -0.1 }, displayTier: "auxiliary", warningLimit: 250.0, alarmLimit: 300.0, criticalLimit: 350.0 }
];

// Unlocated Channels routed to Auxiliary Panel per Research Report Section 3.
var T3D_UNLOCATED_CHANNELS = [
  { sensorId: "PT_110A", sourceKey: "PT_110A", displayName: "Inlet Pressure Branch A", units: "bar", warningLimit: 35.0, alarmLimit: 38.0, criticalLimit: 41.0 },
  { sensorId: "PT_110B", sourceKey: "PT_110B", displayName: "Inlet Pressure Branch B", units: "bar", warningLimit: 35.0, alarmLimit: 38.0, criticalLimit: 41.0 },
  { sensorId: "PT_153", sourceKey: "PT_153", displayName: "Lube Oil Pressure Supply", units: "bar", warningLimit: 2.5, alarmLimit: 1.8, criticalLimit: 1.2 },
  { sensorId: "PT_201", sourceKey: "PT_201", displayName: "Seal Gas Supply Pressure", units: "bar", warningLimit: 5.0, alarmLimit: 4.0, criticalLimit: 3.0 },
  { sensorId: "TT_110A", sourceKey: "TT_110A", displayName: "Inlet Temperature Branch A", units: "°C", warningLimit: 300.0, alarmLimit: 350.0, criticalLimit: 400.0 },
  { sensorId: "TT_110B", sourceKey: "TT_110B", displayName: "Inlet Temperature Branch B", units: "°C", warningLimit: 300.0, alarmLimit: 350.0, criticalLimit: 400.0 },
  { sensorId: "DYNO_WATER_O_L", sourceKey: "DYNO_WATER_O_L", displayName: "Dyno Cooling Water Outlet Temp", units: "°C", warningLimit: 60.0, alarmLimit: 75.0, criticalLimit: 90.0 },
  { sensorId: "RTD_219A", sourceKey: "RTD_219A", displayName: "Aux Bearing RTD 219A", units: "°C", warningLimit: 85.0, alarmLimit: 95.0, criticalLimit: 105.0 },
  { sensorId: "RTD_219B", sourceKey: "RTD_219B", displayName: "Aux Bearing RTD 219B", units: "°C", warningLimit: 85.0, alarmLimit: 95.0, criticalLimit: 105.0 },
  { sensorId: "RTD_220", sourceKey: "RTD_220", displayName: "Aux Thrust Bearing RTD 220", units: "°C", warningLimit: 85.0, alarmLimit: 95.0, criticalLimit: 105.0 },
  { sensorId: "RTD_221", sourceKey: "RTD_221", displayName: "Aux Thrust Bearing RTD 221", units: "°C", warningLimit: 85.0, alarmLimit: 95.0, criticalLimit: 105.0 },
  { sensorId: "RTD_200", sourceKey: "RTD_200", displayName: "Aux Stator RTD Slot 1", units: "°C", warningLimit: 90.0, alarmLimit: 105.0, criticalLimit: 120.0 },
  { sensorId: "RTD_201", sourceKey: "RTD_201", displayName: "Aux Stator RTD Slot 2", units: "°C", warningLimit: 90.0, alarmLimit: 105.0, criticalLimit: 120.0 },
  { sensorId: "RTD_202", sourceKey: "RTD_202", displayName: "Aux Stator RTD Slot 3", units: "°C", warningLimit: 90.0, alarmLimit: 105.0, criticalLimit: 120.0 },
  { sensorId: "RTD_203", sourceKey: "RTD_203", displayName: "Aux Stator RTD Slot 4", units: "°C", warningLimit: 90.0, alarmLimit: 105.0, criticalLimit: 120.0 },
  { sensorId: "RTD_204", sourceKey: "RTD_204", displayName: "Aux Stator RTD Slot 5", units: "°C", warningLimit: 90.0, alarmLimit: 105.0, criticalLimit: 120.0 },
  { sensorId: "RTD_205", sourceKey: "RTD_205", displayName: "Aux Stator RTD Slot 6", units: "°C", warningLimit: 90.0, alarmLimit: 105.0, criticalLimit: 120.0 }
];

var T3D_ALL_SENSORS = {};
for (var _si = 0; _si < T3D_SENSOR_MARKERS.length; _si++) {
  T3D_ALL_SENSORS[T3D_SENSOR_MARKERS[_si].sensorId] = T3D_SENSOR_MARKERS[_si];
}
for (var _ui = 0; _ui < T3D_UNLOCATED_CHANNELS.length; _ui++) {
  T3D_ALL_SENSORS[T3D_UNLOCATED_CHANNELS[_ui].sensorId] = T3D_UNLOCATED_CHANNELS[_ui];
}


// Health-score color thresholds matching subsystem_registry.py.
var T3D_NORMAL_SCORE_THRESHOLD = 90;
var T3D_ALARM_SCORE_THRESHOLD = 60;

function t3dScoreColor(score) {
  var s = typeof score === "number" ? Math.max(0, Math.min(100, score)) : 100;
  if (s >= T3D_NORMAL_SCORE_THRESHOLD) return "#10b981"; // NORMAL - emerald
  if (s >= T3D_ALARM_SCORE_THRESHOLD) return "#f59e0b"; // WARNING - amber
  return "#ef4444"; // ALARM - crimson
}

function t3dGetJwt() {
  try {
    return window.localStorage.getItem("jwt_token") || "";
  } catch (e) {
    return "";
  }
}

// Authenticated fetch for tenant-private GLB, returning a blob URL for Babylon.
function t3dLoadModelBlobUrl(modelUrl) {
  var jwt = t3dGetJwt();
  var headers = jwt ? { "X-Authorization": "Bearer " + jwt } : {};
  return fetch(modelUrl, { headers: headers }).then(function (resp) {
    if (!resp.ok) {
      throw new Error("GLB fetch failed: HTTP " + resp.status);
    }
    return resp.blob();
  }).then(function (blob) {
    return URL.createObjectURL(blob);
  });
}

// Component groups for camera presets and isolation mode.
var T3D_GROUPS = {
  inlet: ["SteamAdmission.001", "SteamAdmission.002", "SteamAdmission.003", "SteamAdmission.004"],
  turbine: ["Turbine.001", "Turbine.002", "Turbine.003"],
  gearbox: ["Gearbox.001"],
  dyno: ["Dyno.001"],
  exhaust: ["Exhaust.001"],
  leakage: ["Leakage.001", "Leakage.002", "Leakage.003", "Leakage.004"],
};

function t3dGroupForMesh(meshName) {
  var keys = Object.keys(T3D_GROUPS);
  for (var i = 0; i < keys.length; i++) {
    if (T3D_GROUPS[keys[i]].indexOf(meshName) !== -1) {
      return keys[i];
    }
  }
  return null;
}

// Flow deadbands and speed caps matching process logic.
var T3D_INLET_FLOW_DEADBAND = 0.5; // TPH, FT_110A
var T3D_LEAKAGE_FLOW_DEADBAND = 0.05; // TPH, FT_162
var T3D_MAX_SHAFT_ANGULAR_VELOCITY = 6; // rad/s cap
var T3D_RATED_RPM = 14000;

// Mount an idempotent fixed-position button to trigger PDF test report export.
function t3dMountPdfExportButton() {
  if (document.getElementById("tb-pdf-export-btn")) {
    return;
  }
  var REPORT_API_BASE = (window.REPORT_API_BASE || (window.location.protocol + "//" + (window.location.hostname || "localhost") + ":8085"));

  var style = document.createElement("style");
  style.id = "tb-pdf-export-btn-style";
  style.textContent =
    "#tb-pdf-export-btn { position: fixed; bottom: 16px; right: 16px; z-index: 9999; " +
    "display: flex; align-items: center; gap: 6px; background: #0f172a; " +
    "border: 1px solid #334155; border-radius: 20px; padding: 8px 14px; " +
    "color: #38bdf8; font-family: Roboto, Arial, sans-serif; font-size: 12px; " +
    "font-weight: 600; cursor: pointer; user-select: none; " +
    "box-shadow: 0 4px 16px rgba(0,0,0,0.45); transition: background 0.15s, color 0.15s, border-color 0.15s; }" +
    "#tb-pdf-export-btn:hover { background: #16213a; }" +
    "#tb-pdf-export-btn[data-state=\"loading\"] { color: #94a3b8; cursor: wait; pointer-events: none; }" +
    "#tb-pdf-export-btn[data-state=\"success\"] { color: #10b981; border-color: #10b981; }" +
    "#tb-pdf-export-btn[data-state=\"error\"] { color: #ef4444; border-color: #ef4444; }" +
    "#tb-pdf-export-btn .tb-pdf-icon { font-size: 15px; line-height: 1; }" +
    "#tb-pdf-export-btn .tb-pdf-spinner { width: 11px; height: 11px; border-radius: 50%; " +
    "border: 2px solid rgba(148,163,184,0.3); border-top-color: #94a3b8; " +
    "animation: tb-pdf-spin 0.8s linear infinite; display: inline-block; }" +
    "@keyframes tb-pdf-spin { to { transform: rotate(360deg); } }";
  document.head.appendChild(style);

  var btn = document.createElement("button");
  btn.id = "tb-pdf-export-btn";
  btn.type = "button";
  btn.setAttribute("data-state", "idle");
  btn.title = "Generate and download shift test summary report";
  btn.innerHTML =
    '<span class="tb-pdf-icon">📄</span><span id="tb-pdf-export-label">Export PDF</span>';
  document.body.appendChild(btn);

  var labelEl = btn.querySelector("#tb-pdf-export-label");
  var resetTimer = null;

  function setState(state, label) {
    btn.setAttribute("data-state", state);
    labelEl.textContent = label;
  }

  btn.addEventListener("click", function () {
    if (btn.getAttribute("data-state") === "loading") {
      return;
    }
    clearTimeout(resetTimer);
    setState("loading", "Generating…");

    fetch(REPORT_API_BASE + "/api/reports/generate", { method: "POST" })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("HTTP " + resp.status);
        }
        return resp.json();
      })
      .then(function (data) {
        if (data.status !== "success") {
          throw new Error(data.stderr || "Report generation failed");
        }
        setState("success", "Downloaded");
        var a = document.createElement("a");
        a.href = REPORT_API_BASE + "/api/reports/latest";
        a.download = data.filename || "shift_test_summary.pdf";
        document.body.appendChild(a);
        a.click();
        a.remove();
        resetTimer = setTimeout(function () {
          setState("idle", "Export PDF");
        }, 2500);
      })
      .catch(function (err) {
        setState("error", "Failed");
        btn.title = "Report generation failed: " + err.message;
        resetTimer = setTimeout(function () {
          setState("idle", "Export PDF");
          btn.title = "Generate and download shift test summary report";
        }, 3500);
      });
  });
}

self.onInit = function () {
  // Hide and remove ThingsBoard footer globally
  (function hideThingsboardFooter() {
    if (!document.getElementById('tb-hide-powered-by')) {
      var s = document.createElement('style');
      s.id = 'tb-hide-powered-by';
      s.textContent = '.tb-powered-by-footer, section[data-html2canvas-ignore].tb-powered-by-footer, section.tb-powered-by-footer, a[href*="thingsboard.io"] { display: none !important; visibility: hidden !important; height: 0 !important; width: 0 !important; opacity: 0 !important; pointer-events: none !important; }';
      document.head.appendChild(s);
    }
    var f = document.querySelector('.tb-powered-by-footer');
    if (f) { f.style.display = 'none'; f.remove(); }
    if (!window.__tbFooterObserverSet) {
      window.__tbFooterObserverSet = true;
      var obs = new MutationObserver(function() {
        var el = document.querySelector('.tb-powered-by-footer');
        if (el) { el.style.display = 'none'; el.remove(); }
      });
      obs.observe(document.documentElement, { childList: true, subtree: true });
    }
  })();

  t3dMountPdfExportButton();

  var settings = self.ctx.settings || {};

  self.ctx.container = self.ctx.$container ? self.ctx.$container[0] : null;
  if (!self.ctx.container) {
    return;
  }

  self.ctx.t3dEls = {
    canvas: self.ctx.container.querySelector("#t3d-canvas"),
    loading: self.ctx.container.querySelector("#t3d-loading"),
    error: self.ctx.container.querySelector("#t3d-error"),
    errorText: self.ctx.container.querySelector("#t3d-error-text"),
    hud: self.ctx.container.querySelector("#t3d-hud"),
    hudTitle: self.ctx.container.querySelector("#t3d-hud-title"),
    hudMesh: self.ctx.container.querySelector("#t3d-hud-mesh"),
    hudScore: self.ctx.container.querySelector("#t3d-hud-score"),
    hudClose: self.ctx.container.querySelector("#t3d-hud-close"),
    hudAlerts: self.ctx.container.querySelector("#t3d-hud-alerts"),
    hudSensorDivider: self.ctx.container.querySelector("#t3d-hud-sensor-divider"),
    hudSensorTitle: self.ctx.container.querySelector("#t3d-hud-sensor-title"),
    hudLiveRow: self.ctx.container.querySelector("#t3d-hud-live-row"),
    hudLive: self.ctx.container.querySelector("#t3d-hud-live"),
    hudLimits: self.ctx.container.querySelector("#t3d-hud-limits"),
    hudLimitFill: self.ctx.container.querySelector("#t3d-hud-limit-fill"),
    hudWarnVal: self.ctx.container.querySelector("#t3d-hud-warn-val"),
    hudAlarmVal: self.ctx.container.querySelector("#t3d-hud-alarm-val"),
    hudCriticalVal: self.ctx.container.querySelector("#t3d-hud-critical-val"),
    hoverTip: self.ctx.container.querySelector("#t3d-hover-tip"),
    statusLabels: self.ctx.container.querySelector("#t3d-status-labels"),
  };

  self.ctx.t3dModelUrl = settings.modelUrl || "/api/resource/general/tenant/turbine_rig_prototype.glb";
  self.ctx.t3dCameraPos = settings.cameraPosition || { alpha: -1.2, beta: 1.1, radius: 9 };
  self.ctx.t3dOverviewCameraPos = self.ctx.t3dCameraPos;
  self.ctx.t3dMeshEntities = {}; // meshId -> { node, entityData }
  self.ctx.t3dDisposed = false;
  self.ctx.t3dRenderActive = false;

  // Animation and telemetry state.
  self.ctx.t3dTelemetry = {}; // TURBINE_SPEED_RPM, GB_TRQ, FT_110A, FT_162, ACT_POS_FB
  self.ctx.t3dShaftAngle = 0;
  self.ctx.t3dGearboxAngle = 0;
  self.ctx.t3dActuatorAngle = { "SteamAdmission.002": 0 }; // ESV, current animated angle
  self.ctx.t3dSelectedGroup = null;
  self.ctx.t3dPinnedMeshName = null;
  self.ctx.t3dParticleSystems = {}; // group -> BABYLON.ParticleSystem

  if (typeof BABYLON === "undefined") {
    t3dShowError(self.ctx, "Babylon.js failed to load (check widget resources).");
    return;
  }

  var canvas = self.ctx.t3dEls.canvas;
  self.ctx.t3dEngine = new BABYLON.Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true });
  self.ctx.t3dScene = new BABYLON.Scene(self.ctx.t3dEngine);
  self.ctx.t3dScene.clearColor = new BABYLON.Color4(0.043, 0.067, 0.125, 1);

  var camPos = self.ctx.t3dCameraPos;
  self.ctx.t3dCamera = new BABYLON.ArcRotateCamera(
    "t3dCamera", camPos.alpha, camPos.beta, camPos.radius,
    BABYLON.Vector3.Zero(), self.ctx.t3dScene
  );
  self.ctx.t3dCamera.attachControl(canvas, true);
  self.ctx.t3dCamera.lowerRadiusLimit = 2;
  self.ctx.t3dCamera.upperRadiusLimit = 30;
  self.ctx.t3dCamera.wheelPrecision = 40;

  // Three-point lighting rig for high-contrast visibility.
  new BABYLON.HemisphericLight("t3dHemi", new BABYLON.Vector3(0, 1, 0), self.ctx.t3dScene).intensity = 1.2;
  var dir = new BABYLON.DirectionalLight("t3dDir", new BABYLON.Vector3(-0.5, -1, -0.3), self.ctx.t3dScene);
  dir.intensity = 1.0;
  var fill = new BABYLON.DirectionalLight("t3dFill", new BABYLON.Vector3(0.6, -0.2, 0.7), self.ctx.t3dScene);
  fill.intensity = 0.4;
  fill.diffuse = new BABYLON.Color3(0.75, 0.85, 1);

  self.ctx.t3dUi = BABYLON.GUI.AdvancedDynamicTexture.CreateFullscreenUI("t3dUI", true, self.ctx.t3dScene);
  self.ctx.t3dHighlightLayer = new BABYLON.HighlightLayer("t3dHighlight", self.ctx.t3dScene);
  self.ctx.t3dHoveredMesh = null;

  t3dLoadModelBlobUrl(self.ctx.t3dModelUrl).then(function (blobUrl) {
    if (self.ctx.t3dDisposed) {
      URL.revokeObjectURL(blobUrl);
      return;
    }
    return BABYLON.SceneLoader.ImportMeshAsync("", blobUrl, "", self.ctx.t3dScene, null, ".glb").then(function (result) {
      URL.revokeObjectURL(blobUrl);
      if (self.ctx.t3dDisposed) {
        return;
      }
      t3dIndexMeshesByName(self.ctx, result.meshes);
      t3dHideOverlay(self.ctx.t3dEls.loading);
      t3dStartRenderLoop(self.ctx);
      t3dApplyPendingColors(self.ctx);
      t3dSetupParticleSystems(self.ctx);
      t3dRegisterAnimationLoop(self.ctx);
      // eslint-disable-next-line no-console
      console.log("[turbine-3d-babylon] loaded", result.meshes.length, "meshes:",
        result.meshes.map(function (m) { return m.name; }));
    });
  }).catch(function (err) {
    // eslint-disable-next-line no-console
    console.error("[turbine-3d-babylon] load failed", err);
    t3dShowError(self.ctx, "Model load failed: " + (err && err.message ? err.message : err));
  });

  if (self.ctx.t3dEls.hudClose) {
    self.ctx.t3dEls.hudClose.addEventListener("click", function () {
      t3dHideOverlay(self.ctx.t3dEls.hud);
      self.ctx.t3dPinnedMeshName = null;
      t3dSelectGroup(self.ctx, null);
      t3dSyncDashboardState(self.ctx, null, null, null);
    });
  }

  // POINTERTAP handles mesh selection and empty-space clicks (deselection).
  self.ctx.t3dScene.onPointerObservable.add(function (pointerInfo) {
    if (pointerInfo.type !== BABYLON.PointerEventTypes.POINTERTAP) {
      return;
    }
    var pick = pointerInfo.pickInfo;
    if (!pick || !pick.hit || !pick.pickedMesh) {
      // Clicked empty space: exit isolation mode and return to the overview.
      t3dSelectGroup(self.ctx, null);
      t3dSyncDashboardState(self.ctx, null, null, null);
      return;
    }
    t3dShowHudForMesh(self.ctx, pick.pickedMesh);
    var group = t3dGroupForMesh(pick.pickedMesh.name);
    if (group) {
      t3dSelectGroup(self.ctx, group);
    }
    var activeGroup = self.ctx.t3dSelectedGroup;
    var entry = self.ctx.t3dMeshEntities[pick.pickedMesh.name];
    t3dSyncDashboardState(
      self.ctx,
      activeGroup,
      activeGroup ? pick.pickedMesh : null,
      activeGroup && entry ? entry.entityData : null
    );
  });

  // Hover highlight and tooltip updates.
  self.ctx.t3dScene.onPointerObservable.add(function (pointerInfo) {
    if (pointerInfo.type !== BABYLON.PointerEventTypes.POINTERMOVE) {
      return;
    }
    var pick = self.ctx.t3dScene.pick(self.ctx.t3dScene.pointerX, self.ctx.t3dScene.pointerY);
    var mesh = pick && pick.hit ? pick.pickedMesh : null;

    if (mesh === self.ctx.t3dHoveredMesh) {
      if (mesh && self.ctx.t3dEls.hoverTip) {
        self.ctx.t3dEls.hoverTip.style.left = self.ctx.t3dScene.pointerX + "px";
        self.ctx.t3dEls.hoverTip.style.top = self.ctx.t3dScene.pointerY + "px";
      }
      return;
    }

    if (self.ctx.t3dHoveredMesh) {
      self.ctx.t3dHighlightLayer.removeMesh(self.ctx.t3dHoveredMesh);
    }
    self.ctx.t3dHoveredMesh = mesh;

    if (!mesh) {
      t3dHideOverlay(self.ctx.t3dEls.hoverTip);
      return;
    }

    self.ctx.t3dHighlightLayer.addMesh(mesh, BABYLON.Color3.FromHexString("#38bdf8"));
    var entry = self.ctx.t3dMeshEntities[mesh.name];
    var label = (entry && entry.entityData && entry.entityData.name) || mesh.name;
    var score = entry && entry.entityData && typeof entry.entityData.healthScore === "number"
      ? entry.entityData.healthScore.toFixed(1) : "--";
    if (self.ctx.t3dEls.hoverTip) {
      self.ctx.t3dEls.hoverTip.textContent = label + " — Health " + score;
      self.ctx.t3dEls.hoverTip.style.left = self.ctx.t3dScene.pointerX + "px";
      self.ctx.t3dEls.hoverTip.style.top = self.ctx.t3dScene.pointerY + "px";
      self.ctx.t3dEls.hoverTip.hidden = false;
    }
  });

  t3dInitSettingsEditor(self.ctx);
  t3dInitSensors(self.ctx);
};



function t3dInitSensors(ctx) {
  var root = ctx.container;
  if (!root) return;

  ctx.t3dMarkerEls = {};
  ctx.t3dSelectedSensor = null;

  var markersHost = root.querySelector("#t3d-sensor-markers");
  if (markersHost) {
    for (var i = 0; i < T3D_SENSOR_MARKERS.length; i++) {
      var m = T3D_SENSOR_MARKERS[i];
      var pin = document.createElement("div");
      pin.className = "t3d-sensor-pin t3d-pin-normal";
      pin.id = "t3d-pin-" + m.sensorId;
      pin.style.display = "none";
      pin.innerHTML = '<span class="t3d-sensor-pin-dot"></span><span class="t3d-pin-id">' + m.sensorId + '</span><span class="t3d-pin-val">--</span>';

      (function (sensorConfig) {
        pin.addEventListener("click", function (e) {
          e.stopPropagation();
          t3dOpenSensorDrawer(ctx, sensorConfig);
        });
        pin.addEventListener("pointerenter", function () {
          var val = ctx.t3dTelemetry[sensorConfig.sourceKey];
          var tip = ctx.t3dEls && ctx.t3dEls.hoverTip;
          if (tip) {
            tip.textContent = sensorConfig.sensorId + ": " + sensorConfig.displayName + " (" + (typeof val === "number" ? val.toFixed(2) : "--") + " " + sensorConfig.units + ")";
            tip.hidden = false;
          }
        });
        pin.addEventListener("pointerleave", function () {
          var tip = ctx.t3dEls && ctx.t3dEls.hoverTip;
          if (tip) tip.hidden = true;
        });
      })(m);

      markersHost.appendChild(pin);
      ctx.t3dMarkerEls[m.sensorId] = pin;
    }
  }

  // Bind Sensor Drawer Close
  var sensorDrawer = root.querySelector("#t3d-sensor-drawer");
  var sensorClose = root.querySelector("#t3d-sensor-close");
  if (sensorClose && sensorDrawer) {
    sensorClose.addEventListener("click", function (e) {
      e.stopPropagation();
      sensorDrawer.hidden = true;
      ctx.t3dSelectedSensor = null;
    });
  }

  // Bind Auxiliary Drawer Toggle & Close
  var btnAux = root.querySelector("#t3d-btn-aux");
  var auxDrawer = root.querySelector("#t3d-aux-drawer");
  var auxClose = root.querySelector("#t3d-aux-close");
  if (btnAux && auxDrawer) {
    btnAux.addEventListener("click", function () {
      auxDrawer.hidden = !auxDrawer.hidden;
      if (!auxDrawer.hidden) {
        t3dPopulateAuxiliaryList(ctx);
      }
    });
  }
  if (auxClose && auxDrawer) {
    auxClose.addEventListener("click", function () {
      auxDrawer.hidden = true;
    });
  }
}

function t3dOpenSensorDrawer(ctx, sensor) {
  var root = ctx.container;
  if (!root) return;
  var drawer = root.querySelector("#t3d-sensor-drawer");
  if (!drawer) return;

  ctx.t3dSelectedSensor = sensor.sensorId;

  var idEl = root.querySelector("#t3d-sensor-id");
  var nameEl = root.querySelector("#t3d-sensor-name");
  var meshEl = root.querySelector("#t3d-sensor-mesh");
  var valEl = root.querySelector("#t3d-sensor-val");
  var unitEl = root.querySelector("#t3d-sensor-unit");
  var statusEl = root.querySelector("#t3d-sensor-status-tag");
  var tierEl = root.querySelector("#t3d-sensor-tier");
  var warnEl = root.querySelector("#t3d-sensor-warn-val");
  var alarmEl = root.querySelector("#t3d-sensor-alarm-val");
  var critEl = root.querySelector("#t3d-sensor-crit-val");
  var fillEl = root.querySelector("#t3d-sensor-limit-fill");

  if (idEl) idEl.textContent = sensor.sensorId;
  if (nameEl) nameEl.textContent = sensor.displayName;
  if (meshEl) meshEl.textContent = sensor.componentNode ? "Node: " + sensor.componentNode : "Unlocated (Auxiliary)";
  if (unitEl) unitEl.textContent = sensor.units || "";
  if (tierEl) tierEl.textContent = (sensor.displayTier || "AUX").toUpperCase();

  var val = ctx.t3dTelemetry[sensor.sourceKey];
  var numVal = typeof val === "number" ? val : parseFloat(val);
  var isNum = !isNaN(numVal);

  if (valEl) valEl.textContent = isNum ? numVal.toFixed(2) : "--";

  var warn = sensor.warningLimit;
  var alarm = sensor.alarmLimit;
  var crit = sensor.criticalLimit;

  if (warnEl) warnEl.textContent = typeof warn === "number" ? warn.toFixed(2) : "--";
  if (alarmEl) alarmEl.textContent = typeof alarm === "number" ? alarm.toFixed(2) : "--";
  if (critEl) critEl.textContent = typeof crit === "number" ? crit.toFixed(2) : "--";

  // Status calculation
  var status = "NORMAL";
  var statusClass = "";
  if (isNum && typeof alarm === "number" && numVal >= alarm) {
    status = "ALARM";
    statusClass = "status-alarm";
  } else if (isNum && typeof warn === "number" && numVal >= warn) {
    status = "WARNING";
    statusClass = "status-warning";
  }

  if (statusEl) {
    statusEl.textContent = status;
    statusEl.className = "t3d-sensor-status-tag " + statusClass;
  }

  if (fillEl && isNum && typeof crit === "number" && crit > 0) {
    var pct = Math.max(0, Math.min(100, (numVal / crit) * 100));
    fillEl.style.left = pct + "%";
  }

  drawer.hidden = false;

  // Broadcast sensor selection event and sync state
  if (ctx.stateController && typeof ctx.stateController.updateState === "function") {
    try {
      var curParams = ctx.stateController.getStateParams() || {};
      var nextParams = Object.assign({}, curParams, {
        selectedSensor: sensor.sensorId,
        selectedSensorName: sensor.displayName,
      });
      ctx.stateController.updateState(undefined, nextParams, false);
    } catch (e) {
      console.warn("[turbine-3d-babylon] stateController sensor update error:", e);
    }
  }

  window.dispatchEvent(new CustomEvent("tb-sensor-select", {
    detail: { sensorId: sensor.sensorId, displayName: sensor.displayName, value: numVal }
  }));
}

function t3dPopulateAuxiliaryList(ctx) {
  var root = ctx.container;
  if (!root) return;
  var listEl = root.querySelector("#t3d-aux-list");
  if (!listEl) return;

  listEl.innerHTML = "";
  for (var i = 0; i < T3D_UNLOCATED_CHANNELS.length; i++) {
    var u = T3D_UNLOCATED_CHANNELS[i];
    var val = ctx.t3dTelemetry[u.sourceKey];
    var isNum = typeof val === "number";

    var item = document.createElement("div");
    item.className = "t3d-aux-item";
    item.innerHTML =
      '<div>' +
        '<div class="t3d-aux-item-id">' + u.sensorId + '</div>' +
        '<div class="t3d-aux-item-name">' + u.displayName + '</div>' +
      '</div>' +
      '<div class="t3d-aux-item-reading">' +
        '<span class="t3d-aux-item-val">' + (isNum ? val.toFixed(2) : "--") + '</span>' +
        '<span class="t3d-aux-item-unit">' + u.units + '</span>' +
      '</div>';

    (function (sensor) {
      item.addEventListener("click", function () {
        t3dOpenSensorDrawer(ctx, sensor);
      });
    })(u);

    listEl.appendChild(item);
  }
}

function t3dUpdateSensorMarkers(ctx) {
  if (!ctx.t3dMarkerEls || !ctx.t3dScene || !ctx.t3dCamera || !ctx.t3dEngine) {
    return;
  }
  var selectedGroup = ctx.t3dSelectedGroup;
  var engine = ctx.t3dEngine;
  var viewport = ctx.t3dCamera.viewport.toGlobal(engine.getRenderWidth(), engine.getRenderHeight());

  for (var i = 0; i < T3D_SENSOR_MARKERS.length; i++) {
    var m = T3D_SENSOR_MARKERS[i];
    var pinEl = ctx.t3dMarkerEls[m.sensorId];
    if (!pinEl) continue;

    // Only render markers for the currently isolated group
    if (!selectedGroup || m.system !== selectedGroup) {
      pinEl.style.display = "none";
      continue;
    }

    var meshEntry = ctx.t3dMeshEntities[m.componentNode];
    if (!meshEntry || !meshEntry.node) {
      pinEl.style.display = "none";
      continue;
    }

    var meshCenter = t3dMeshWorldCenter(meshEntry.node);
    var markerWorld = meshCenter.add(new BABYLON.Vector3(m.offset.x, m.offset.y, m.offset.z));

    var screen = BABYLON.Vector3.Project(
      markerWorld,
      BABYLON.Matrix.Identity(),
      ctx.t3dScene.getTransformMatrix(),
      viewport
    );

    if (screen.z < 0 || screen.z > 1) {
      pinEl.style.display = "none";
      continue;
    }

    pinEl.style.display = "inline-flex";
    pinEl.style.left = screen.x + "px";
    pinEl.style.top = screen.y + "px";

    // Update live value & alert styling
    var val = ctx.t3dTelemetry[m.sourceKey];
    var numVal = typeof val === "number" ? val : parseFloat(val);
    var valEl = pinEl.querySelector(".t3d-pin-val");
    if (valEl) {
      valEl.textContent = !isNaN(numVal) ? numVal.toFixed(1) + " " + m.units : "--";
    }

    var statusClass = "t3d-pin-normal";
    if (!isNaN(numVal) && typeof m.alarmLimit === "number" && numVal >= m.alarmLimit) {
      statusClass = "t3d-pin-alarm";
    } else if (!isNaN(numVal) && typeof m.warningLimit === "number" && numVal >= m.warningLimit) {
      statusClass = "t3d-pin-warning";
    }
    pinEl.className = "t3d-sensor-pin " + statusClass;
  }
}


// Computes mesh world center from bounding box for targeting and emission.
function t3dMeshWorldCenter(mesh) {
  mesh.computeWorldMatrix(true);
  return mesh.getBoundingInfo().boundingBox.centerWorld;
}

// Telemetry-driven meshes re-pivoted to bounding centers for in-place rotation.
var T3D_ROTATED_MESH_NAMES = ["Turbine.001", "Gearbox.001", "SteamAdmission.002"];

function t3dIndexMeshesByName(ctx, meshes) {
  for (var i = 0; i < meshes.length; i++) {
    var mesh = meshes[i];
    if (!mesh.name || mesh.name === "__root__") {
      continue;
    }
    ctx.t3dMeshEntities[mesh.name] = ctx.t3dMeshEntities[mesh.name] || { node: null, entityData: null };
    ctx.t3dMeshEntities[mesh.name].node = mesh;

    if (T3D_ROTATED_MESH_NAMES.indexOf(mesh.name) !== -1) {
      mesh.computeWorldMatrix(true);
      var localCenter = mesh.getBoundingInfo().boundingBox.center;
      mesh.setPivotPoint(localCenter, BABYLON.Space.LOCAL);
    }
  }
}

function t3dShowError(ctx, message) {
  t3dHideOverlay(ctx.t3dEls.loading);
  if (ctx.t3dEls.errorText) {
    ctx.t3dEls.errorText.textContent = message;
  }
  if (ctx.t3dEls.error) {
    ctx.t3dEls.error.hidden = false;
  }
}

function t3dHideOverlay(el) {
  if (el) {
    el.hidden = true;
  }
}

function t3dStartRenderLoop(ctx) {
  if (ctx.t3dRenderActive || !ctx.t3dEngine || !ctx.t3dScene) {
    return;
  }
  ctx.t3dRenderActive = true;
  ctx.t3dEngine.runRenderLoop(function () {
    // Pause rendering when container is hidden to conserve GPU.
    if (!ctx.container || ctx.container.offsetWidth === 0 || ctx.container.offsetHeight === 0) {
      return;
    }
    if (ctx.t3dScene && ctx.t3dScene.activeCamera) {
      ctx.t3dScene.render();
    }
  });
}

// Displays HUD diagnostics with component health and primary sensor limits.
function t3dShowHudForMesh(ctx, mesh) {
  var entry = ctx.t3dMeshEntities[mesh.name];
  var hud = ctx.t3dEls.hud;
  if (!hud) {
    return;
  }
  var data = entry && entry.entityData;
  var label = (data && data.name) || mesh.name;
  var score = data ? data.healthScore : undefined;
  var alerts = data ? data.activeAlertsCount : undefined;

  if (ctx.t3dEls.hudTitle) ctx.t3dEls.hudTitle.textContent = label;
  if (ctx.t3dEls.hudMesh) ctx.t3dEls.hudMesh.textContent = "Mesh: " + mesh.name;
  if (ctx.t3dEls.hudScore) {
    ctx.t3dEls.hudScore.textContent = typeof score === "number" ? score.toFixed(1) : "--";
  }
  if (ctx.t3dEls.hudAlerts) {
    ctx.t3dEls.hudAlerts.textContent = typeof alerts === "number" ? String(alerts) : "--";
  }

  var sensorKey = data && data.limitSensor;
  var warn = data && typeof data.warningLimit === "number" ? data.warningLimit : null;
  var alarm = data && typeof data.alarmLimit === "number" ? data.alarmLimit : null;
  var critical = data && typeof data.criticalLimit === "number" ? data.criticalLimit : null;
  var hasLimits = sensorKey && warn !== null && alarm !== null && critical !== null;

  if (ctx.t3dEls.hudSensorDivider) ctx.t3dEls.hudSensorDivider.hidden = !hasLimits;
  if (ctx.t3dEls.hudSensorTitle) {
    ctx.t3dEls.hudSensorTitle.hidden = !hasLimits;
    ctx.t3dEls.hudSensorTitle.textContent = hasLimits ? "Primary sensor: " + sensorKey : "";
  }
  if (ctx.t3dEls.hudLiveRow) ctx.t3dEls.hudLiveRow.hidden = !hasLimits;
  if (ctx.t3dEls.hudLimits) ctx.t3dEls.hudLimits.hidden = !hasLimits;

  if (hasLimits) {
    var liveValue = ctx.t3dTelemetry[sensorKey];
    if (ctx.t3dEls.hudLive) {
      ctx.t3dEls.hudLive.textContent = typeof liveValue === "number" ? liveValue.toFixed(2) : "--";
    }
    if (ctx.t3dEls.hudWarnVal) ctx.t3dEls.hudWarnVal.textContent = warn.toFixed(2);
    if (ctx.t3dEls.hudAlarmVal) ctx.t3dEls.hudAlarmVal.textContent = alarm.toFixed(2);
    if (ctx.t3dEls.hudCriticalVal) ctx.t3dEls.hudCriticalVal.textContent = critical.toFixed(2);
    if (ctx.t3dEls.hudLimitFill && typeof liveValue === "number") {
      var pct = Math.max(0, Math.min(100, (liveValue / critical) * 100));
      ctx.t3dEls.hudLimitFill.style.left = pct + "%";
    }
  }

  hud.hidden = false;
  ctx.t3dPinnedMeshName = mesh.name;
}

// Refreshes currently pinned HUD with incoming telemetry values.
function t3dRefreshPinnedHud(ctx) {
  var name = ctx.t3dPinnedMeshName;
  if (!name || !ctx.t3dMeshEntities[name] || !ctx.t3dMeshEntities[name].node) {
    return;
  }
  if (ctx.t3dEls.hud && ctx.t3dEls.hud.hidden) {
    return; // closed by the user since it was pinned
  }
  t3dShowHudForMesh(ctx, ctx.t3dMeshEntities[name].node);
}

// Telemetry keys driving animations and subsystem limit monitors.
var T3D_DEVICE_TELEMETRY_KEYS = [
  "TURBINE_SPEED_RPM", "GB_TRQ", "FT_110A", "FT_162", "ACT_POS_FB",
  "PT_109A", "TT_109A", "PT_111B", "PT_111", "TT_111", "PT_112", "TT_112",
  "PT_120", "TT_120_R", "PT_111C", "TT_111C", "ZT_600", "ZT_601",
  "XT_600", "XT_601", "XT_602", "XT_603", "PYRO_T",
  "XT_604", "XT_605", "XT_606", "XT_607", "PYRO_GB",
  "PT_253", "PT_150A", "TT_150A",
  "PT_162", "TT_162", "PT_161", "TT_161", "PT_160", "TT_160", "PT_163", "TT_163",
  "PT_110A", "PT_110B", "PT_153", "PT_201", "TT_110A", "TT_110B", "DYNO_WATER_O_L",
  "RTD_219A", "RTD_219B", "RTD_220", "RTD_221", "RTD_200", "RTD_201", "RTD_202", "RTD_203", "RTD_204", "RTD_205"
];

self.onDataUpdated = function () {
  if (!self.ctx || !Array.isArray(self.ctx.data)) {
    return;
  }

  var byEntity = {};
  for (var i = 0; i < self.ctx.data.length; i++) {
    var series = self.ctx.data[i];
    if (!series || !series.dataKey || !Array.isArray(series.data) || series.data.length === 0) {
      continue;
    }
    var keyName = series.dataKey.name;
    var latest = series.data[series.data.length - 1];
    var value = latest ? latest[1] : undefined;

    if (T3D_DEVICE_TELEMETRY_KEYS.indexOf(keyName) !== -1) {
      self.ctx.t3dTelemetry[keyName] = typeof value === "number" ? value : parseFloat(value);
      continue;
    }

    if (!series.datasource) {
      continue;
    }
    var entityName = series.datasource.entityName || series.datasource.name || series.datasource.entityLabel;
    if (!entityName) {
      continue;
    }
    byEntity[entityName] = byEntity[entityName] || {};
    byEntity[entityName][keyName] = value;
    byEntity[entityName].name = entityName;
  }

  self.ctx.t3dPendingEntityData = byEntity;
  t3dApplyPendingColors(self.ctx);
  t3dRefreshPinnedHud(self.ctx);
  if (self.ctx.t3dSelectedSensor && T3D_ALL_SENSORS[self.ctx.t3dSelectedSensor]) {
    t3dOpenSensorDrawer(self.ctx, T3D_ALL_SENSORS[self.ctx.t3dSelectedSensor]);
  }
};

function t3dApplyPendingColors(ctx) {
  var byEntity = ctx.t3dPendingEntityData;
  if (!byEntity || !ctx.t3dMeshEntities) {
    return;
  }
  var names = Object.keys(byEntity);
  for (var i = 0; i < names.length; i++) {
    var entityData = byEntity[names[i]];
    var meshId = entityData.meshId;
    if (!meshId || !ctx.t3dMeshEntities[meshId] || !ctx.t3dMeshEntities[meshId].node) {
      continue;
    }
    ctx.t3dMeshEntities[meshId].entityData = entityData;
    t3dColorMesh(ctx, ctx.t3dMeshEntities[meshId].node, entityData.healthScore);
  }
}

function t3dColorMesh(ctx, mesh, healthScore) {
  if (!mesh.material) {
    mesh.material = new BABYLON.StandardMaterial(mesh.name + "_mat", ctx.t3dScene);
  }
  var hex = t3dScoreColor(healthScore);
  var color = BABYLON.Color3.FromHexString(hex);
  mesh.material.diffuseColor = color;
  mesh.material.emissiveColor = color.scale(0.35);
  // Tight specular highlights for metallic finish.
  mesh.material.specularColor = color.scale(0.9);
  mesh.material.specularPower = 48;
  // Cached base emissive for alarm pulsing.
  mesh._t3dBaseEmissive = color;
  mesh._t3dHealthScore = typeof healthScore === "number" ? healthScore : 100;
}

// Applies emissive pulse to components currently in alarm state.
function t3dApplyAlarmPulse(ctx, elapsedSeconds) {
  var names = Object.keys(ctx.t3dMeshEntities);
  for (var i = 0; i < names.length; i++) {
    var node = ctx.t3dMeshEntities[names[i]].node;
    if (!node || !node.material || !node._t3dBaseEmissive) {
      continue;
    }
    if (node._t3dHealthScore >= T3D_ALARM_SCORE_THRESHOLD) {
      continue;
    }
    var pulse = 0.15 + 0.2 * Math.abs(Math.sin(elapsedSeconds * 3));
    node.material.emissiveColor = node._t3dBaseEmissive.scale(pulse);
  }
}

// Short badge text for a status tag (e.g. "Emergency Stop Valve (ESV)" -> "ESV").
function t3dShortTag(name) {
  var paren = name && name.match(/\(([^)]+)\)/);
  if (paren) {
    return paren[1];
  }
  var short = (name || "").replace(/\s*\(.*?\)\s*/g, "").trim();
  return short.slice(0, 4).toUpperCase();
}

// Project status tags above flagged meshes in WARNING/ALARM state into screen space.
function t3dUpdateStatusLabels(ctx) {
  var host = ctx.t3dEls && ctx.t3dEls.statusLabels;
  if (!host || !ctx.t3dMeshEntities || !ctx.t3dScene || !ctx.t3dCamera) {
    return;
  }
  ctx.t3dStatusLabelEls = ctx.t3dStatusLabelEls || {};
  var engine = ctx.t3dEngine;
  var viewport = ctx.t3dCamera.viewport.toGlobal(engine.getRenderWidth(), engine.getRenderHeight());
  var seen = {};

  var meshIds = Object.keys(ctx.t3dMeshEntities);
  for (var i = 0; i < meshIds.length; i++) {
    var meshId = meshIds[i];
    var entry = ctx.t3dMeshEntities[meshId];
    var node = entry && entry.node;
    var data = entry && entry.entityData;
    var status = data && data.healthStatus;
    if (!node || (status !== "WARNING" && status !== "ALARM")) {
      continue;
    }
    seen[meshId] = true;

    var el = ctx.t3dStatusLabelEls[meshId];
    if (!el) {
      el = document.createElement("div");
      el.className = "t3d-status-tag";
      host.appendChild(el);
      ctx.t3dStatusLabelEls[meshId] = el;
    }
    el.className = "t3d-status-tag " + (status === "ALARM" ? "t3d-status-alarm" : "t3d-status-warning");
    el.textContent = t3dShortTag(data.name || meshId);

    var world = node.getAbsolutePosition();
    var screen = BABYLON.Vector3.Project(
      world,
      BABYLON.Matrix.Identity(),
      ctx.t3dScene.getTransformMatrix(),
      viewport
    );
    el.style.display = screen.z < 0 || screen.z > 1 ? "none" : "block";
    el.style.left = screen.x + "px";
    el.style.top = (screen.y - 14) + "px";
  }

  var existingIds = Object.keys(ctx.t3dStatusLabelEls);
  for (var j = 0; j < existingIds.length; j++) {
    var id = existingIds[j];
    if (!seen[id]) {
      ctx.t3dStatusLabelEls[id].remove();
      delete ctx.t3dStatusLabelEls[id];
    }
  }
}

// Procedural radial gradient texture for particle flow.
function t3dMakeDotTexture(scene) {
  var size = 32;
  var dt = new BABYLON.DynamicTexture("t3dParticleDot", size, scene, false);
  var ctx2d = dt.getContext();
  var gradient = ctx2d.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx2d.fillStyle = gradient;
  ctx2d.fillRect(0, 0, size, size);
  dt.update();
  dt.hasAlpha = true;
  return dt;
}

function t3dMakeFlowParticleSystem(ctx, name, fromMeshName, toMeshName, color) {
  var fromEntry = ctx.t3dMeshEntities[fromMeshName];
  var toEntry = ctx.t3dMeshEntities[toMeshName];
  if (!fromEntry || !fromEntry.node || !toEntry || !toEntry.node) {
    return null;
  }
  var ps = new BABYLON.ParticleSystem(name, 200, ctx.t3dScene);
  ps.particleTexture = t3dMakeDotTexture(ctx.t3dScene);
  ps.blendMode = BABYLON.ParticleSystem.BLENDMODE_ADD;
  var fromPos = t3dMeshWorldCenter(fromEntry.node);
  var toPos = t3dMeshWorldCenter(toEntry.node);
  ps.emitter = fromPos.clone();
  var direction = toPos.subtract(fromPos);
  var length = direction.length() || 1;
  direction = direction.normalize();
  ps.direction1 = direction.scale(0.9);
  ps.direction2 = direction.scale(1.1);
  ps.minEmitBox = new BABYLON.Vector3(-0.05, -0.05, -0.05);
  ps.maxEmitBox = new BABYLON.Vector3(0.05, 0.05, 0.05);
  ps.color1 = color.toColor4(0.9);
  ps.color2 = color.toColor4(0.4);
  ps.colorDead = color.toColor4(0);
  ps.minSize = 0.04;
  ps.maxSize = 0.12;
  ps.minLifeTime = length / 2.2;
  ps.maxLifeTime = length / 1.6;
  ps.emitRate = 0; // driven live by t3dFlowRate
  ps.minEmitPower = length * 0.9;
  ps.maxEmitPower = length * 1.1;
  ps.updateSpeed = 0.02;
  ps.start();
  return ps;
}

function t3dSetupParticleSystems(ctx) {
  ctx.t3dParticleSystems.inlet = t3dMakeFlowParticleSystem(
    ctx, "t3dInletSteam", "SteamAdmission.001", "Turbine.001", new BABYLON.Color3(0.34, 0.83, 0.98)
  );
  ctx.t3dParticleSystems.leakage = t3dMakeFlowParticleSystem(
    ctx, "t3dLeakage", "Leakage.001", "Exhaust.001", new BABYLON.Color3(0.98, 0.73, 0.18)
  );
}

// Maps telemetry value above deadband to linear particle emit rate.
function t3dFlowRate(value, deadband, maxValueForFullRate, maxRate) {
  var v = typeof value === "number" ? value : 0;
  if (v <= deadband) {
    return 0;
  }
  var frac = Math.min(1, (v - deadband) / Math.max(0.0001, maxValueForFullRate - deadband));
  return frac * maxRate;
}

// Per-frame animation loop for shaft/gearbox rotation, actuator lerp, and flow.
function t3dRegisterAnimationLoop(ctx) {
  ctx.t3dElapsedSeconds = 0;
  ctx.t3dScene.onBeforeRenderObservable.add(function () {
    var dt = ctx.t3dEngine.getDeltaTime() / 1000;
    if (dt <= 0 || dt > 0.5) {
      return; // skip huge dt spikes (tab was backgrounded, etc.)
    }
    ctx.t3dElapsedSeconds += dt;
    t3dApplyAlarmPulse(ctx, ctx.t3dElapsedSeconds);
    t3dUpdateStatusLabels(ctx);
    t3dUpdateSensorMarkers(ctx);

    var speedRpm = ctx.t3dTelemetry.TURBINE_SPEED_RPM || 0;
    // Sqrt scaling maintains perceptual visibility across dynamic RPM range.
    var angularVelocity = Math.min(
      T3D_MAX_SHAFT_ANGULAR_VELOCITY,
      Math.sqrt(Math.max(0, speedRpm) / T3D_RATED_RPM) * T3D_MAX_SHAFT_ANGULAR_VELOCITY
    );
    ctx.t3dShaftAngle = (ctx.t3dShaftAngle + angularVelocity * dt) % (2 * Math.PI);
    ctx.t3dGearboxAngle = (ctx.t3dGearboxAngle + angularVelocity * 2.4 * dt) % (2 * Math.PI);

    var turbineEntry = ctx.t3dMeshEntities["Turbine.001"];
    if (turbineEntry && turbineEntry.node) {
      turbineEntry.node.rotation.y = ctx.t3dShaftAngle;
    }
    var gearboxEntry = ctx.t3dMeshEntities["Gearbox.001"];
    if (gearboxEntry && gearboxEntry.node) {
      // Symbolic coupled rotation for gearbox visualization.
      gearboxEntry.node.rotation.y = ctx.t3dGearboxAngle;
    }

    // Smooth lerp toward ACT_POS_FB target angle.
    var esvEntry = ctx.t3dMeshEntities["SteamAdmission.002"];
    if (esvEntry && esvEntry.node) {
      var actPos = ctx.t3dTelemetry.ACT_POS_FB;
      var targetAngle = typeof actPos === "number" ? (actPos / 100) * (Math.PI / 4) : 0;
      var current = ctx.t3dActuatorAngle["SteamAdmission.002"] || 0;
      var next = current + (targetAngle - current) * Math.min(1, dt * 3);
      ctx.t3dActuatorAngle["SteamAdmission.002"] = next;
      esvEntry.node.rotation.z = next;
    }

    if (ctx.t3dParticleSystems.inlet) {
      ctx.t3dParticleSystems.inlet.emitRate = t3dFlowRate(
        ctx.t3dTelemetry.FT_110A, T3D_INLET_FLOW_DEADBAND, 30, 150
      );
    }
    if (ctx.t3dParticleSystems.leakage) {
      ctx.t3dParticleSystems.leakage.emitRate = t3dFlowRate(
        ctx.t3dTelemetry.FT_162, T3D_LEAKAGE_FLOW_DEADBAND, 2, 60
      );
    }
  });
}

// Camera presets with smooth fly-to per component group and isolation mode.
function t3dGroupCenter(ctx, group) {
  var meshNames = T3D_GROUPS[group] || [];
  var sum = BABYLON.Vector3.Zero();
  var count = 0;
  for (var i = 0; i < meshNames.length; i++) {
    var entry = ctx.t3dMeshEntities[meshNames[i]];
    if (entry && entry.node) {
      sum = sum.add(t3dMeshWorldCenter(entry.node));
      count++;
    }
  }
  return count > 0 ? sum.scale(1 / count) : BABYLON.Vector3.Zero();
}

function t3dAnimateCameraTarget(ctx, targetVec3, radius) {
  var camera = ctx.t3dCamera;
  if (!camera) {
    return;
  }
  var frameRate = 30;
  var targetAnim = new BABYLON.Animation(
    "t3dCamTarget", "target", frameRate, BABYLON.Animation.ANIMATIONTYPE_VECTOR3,
    BABYLON.Animation.ANIMATIONLOOPMODE_CONSTANT
  );
  targetAnim.setKeys([{ frame: 0, value: camera.target.clone() }, { frame: frameRate, value: targetVec3 }]);

  var radiusAnim = new BABYLON.Animation(
    "t3dCamRadius", "radius", frameRate, BABYLON.Animation.ANIMATIONTYPE_FLOAT,
    BABYLON.Animation.ANIMATIONLOOPMODE_CONSTANT
  );
  radiusAnim.setKeys([{ frame: 0, value: camera.radius }, { frame: frameRate, value: radius }]);

  ctx.t3dScene.beginDirectAnimation(camera, [targetAnim, radiusAnim], 0, frameRate, false, 1.4);
}

// Computes maximum bounding radius of mesh group for camera framing.
function t3dGroupExtent(ctx, group, center) {
  var meshNames = T3D_GROUPS[group] || [];
  var maxReach = 0;
  for (var i = 0; i < meshNames.length; i++) {
    var entry = ctx.t3dMeshEntities[meshNames[i]];
    if (!entry || !entry.node) {
      continue;
    }
    var info = entry.node.getBoundingInfo();
    var reach = BABYLON.Vector3.Distance(center, info.boundingBox.centerWorld) + info.boundingSphere.radiusWorld;
    maxReach = Math.max(maxReach, reach);
  }
  return maxReach;
}

function t3dSelectGroup(ctx, group) {
  if (ctx.t3dSelectedGroup === group) {
    group = null; // clicking the already-selected group deselects it
  }
  ctx.t3dSelectedGroup = group;
  if (!group && ctx.container) {
    var _sd = ctx.container.querySelector("#t3d-sensor-drawer");
    if (_sd) _sd.hidden = true;
    ctx.t3dSelectedSensor = null;
  }

  var allMeshNames = Object.keys(ctx.t3dMeshEntities);
  for (var i = 0; i < allMeshNames.length; i++) {
    var entry = ctx.t3dMeshEntities[allMeshNames[i]];
    if (!entry || !entry.node) {
      continue;
    }
    var meshGroup = t3dGroupForMesh(allMeshNames[i]);
    // Ungrouped meshes remain visible during isolation mode.
    var inSelected = !group || !meshGroup || meshGroup === group;
    entry.node.visibility = inSelected ? 1 : 0.12;
  }

  if (group) {
    var center = t3dGroupCenter(ctx, group);
    var minRadius = ctx.t3dCamera ? ctx.t3dCamera.lowerRadiusLimit : 2;
    var maxRadius = ctx.t3dCamera ? ctx.t3dCamera.upperRadiusLimit : 30;
    var extent = t3dGroupExtent(ctx, group, center);
    var radius = extent > 0 ? Math.max(minRadius, Math.min(maxRadius, extent * 2.5)) : 4.5;
    t3dAnimateCameraTarget(ctx, center, radius);
  } else {
    var overview = ctx.t3dOverviewCameraPos;
    t3dAnimateCameraTarget(ctx, BABYLON.Vector3.Zero(), overview.radius || 9);
  }
}

function t3dSyncDashboardState(ctx, group, mesh, entityData) {
  var componentName = (entityData && entityData.name) || (group ? group.name : (mesh ? mesh.name : null));
  var entityId = entityData && entityData.id ? entityData.id : null;
  var meshId = mesh ? mesh.name : null;

  // 1. Update ThingsBoard stateController state parameter for drill-down sync
  if (ctx.stateController && typeof ctx.stateController.updateState === "function") {
    try {
      var curParams = (typeof ctx.stateController.getStateParams === "function")
        ? (ctx.stateController.getStateParams() || {}) : {};
      var nextParams = Object.assign({}, curParams, {
        selectedComponent: componentName || null,
        selectedMesh: meshId || null,
        selectedGroup: group ? group.name : null,
      });
      ctx.stateController.updateState(undefined, nextParams, false);
    } catch (err) {
      console.warn("[turbine-3d-babylon] stateController updateState error:", err);
    }
  }

  // 2. Trigger configured widget action descriptors if defined
  if (ctx.actionsApi) {
    try {
      var actionDescriptors = [];
      if (typeof ctx.actionsApi.getActionDescriptors === "function") {
        actionDescriptors = ctx.actionsApi.getActionDescriptors("componentClick") ||
                            ctx.actionsApi.getActionDescriptors("meshClick") ||
                            ctx.actionsApi.getActionDescriptors("elementClick") || [];
      }
      if (actionDescriptors && actionDescriptors.length > 0) {
        actionDescriptors.forEach(function (desc) {
          if (typeof ctx.actionsApi.handleWidgetAction === "function") {
            ctx.actionsApi.handleWidgetAction(
              null,
              desc,
              entityId,
              componentName,
              { selectedComponent: componentName, meshId: meshId, group: group ? group.name : null },
              componentName
            );
          }
        });
      }
    } catch (err) {
      console.warn("[turbine-3d-babylon] actionsApi execution error:", err);
    }
  }

  // 3. Broadcast cross-widget DOM event so sibling widgets can synchronize
  window.dispatchEvent(new CustomEvent("tb-component-select", {
    detail: {
      component: componentName || null,
      meshId: meshId || null,
      group: group ? group.name : null,
    }
  }));
}

function t3dReloadModel(ctx, modelUrl) {
  t3dShowOverlay(ctx.t3dEls.loading);
  t3dLoadModelBlobUrl(modelUrl).then(function (blobUrl) {
    if (ctx.t3dDisposed) {
      URL.revokeObjectURL(blobUrl);
      return;
    }
    var meshKeys = Object.keys(ctx.t3dMeshEntities || {});
    for (var i = 0; i < meshKeys.length; i++) {
      var entry = ctx.t3dMeshEntities[meshKeys[i]];
      if (entry && entry.node) {
        entry.node.dispose();
      }
    }
    ctx.t3dMeshEntities = {};

    return BABYLON.SceneLoader.ImportMeshAsync("", blobUrl, "", ctx.t3dScene, null, ".glb").then(function (result) {
      URL.revokeObjectURL(blobUrl);
      if (ctx.t3dDisposed) return;
      t3dIndexMeshesByName(ctx, result.meshes);
      t3dHideOverlay(ctx.t3dEls.loading);
      t3dApplyPendingColors(ctx);
      t3dSetupParticleSystems(ctx);
      console.log("[turbine-3d-babylon] reloaded", result.meshes.length, "meshes from", modelUrl);
    });
  }).catch(function (err) {
    console.error("[turbine-3d-babylon] reload failed", err);
    t3dShowError(ctx, "Reload failed: " + (err && err.message ? err.message : err));
  });
}

function t3dInitSettingsEditor(ctx) {
  var root = ctx.container;
  if (!root) return;

  var btnSettings = root.querySelector("#t3d-btn-settings");
  var modal = root.querySelector("#t3d-settings-modal");
  var btnClose = root.querySelector("#t3d-settings-close");
  var btnCancel = root.querySelector("#t3d-btn-settings-cancel");
  var btnSave = root.querySelector("#t3d-btn-settings-save");
  var btnCapture = root.querySelector("#t3d-btn-capture-cam");
  var backdrop = root.querySelector("#t3d-settings-backdrop");

  var inputModelUrl = root.querySelector("#t3d-set-model-url");
  var inputAlpha = root.querySelector("#t3d-set-cam-alpha");
  var inputBeta = root.querySelector("#t3d-set-cam-beta");
  var inputRadius = root.querySelector("#t3d-set-cam-radius");
  var inputTx = root.querySelector("#t3d-set-cam-tx");
  var inputTy = root.querySelector("#t3d-set-cam-ty");
  var inputTz = root.querySelector("#t3d-set-cam-tz");

  function openSettings() {
    if (!modal) return;
    var s = ctx.settings || {};
    var cp = s.cameraPosition || ctx.t3dCameraPos || { alpha: -1.2, beta: 1.1, radius: 9 };
    var target = (ctx.t3dCamera && ctx.t3dCamera.target) || BABYLON.Vector3.Zero();

    if (inputModelUrl) inputModelUrl.value = s.modelUrl || ctx.t3dModelUrl || "";
    if (inputAlpha) inputAlpha.value = (typeof cp.alpha === "number" ? cp.alpha : -1.2).toFixed(3);
    if (inputBeta) inputBeta.value = (typeof cp.beta === "number" ? cp.beta : 1.1).toFixed(3);
    if (inputRadius) inputRadius.value = (typeof cp.radius === "number" ? cp.radius : 9).toFixed(2);
    if (inputTx) inputTx.value = (target.x || 0).toFixed(2);
    if (inputTy) inputTy.value = (target.y || 0).toFixed(2);
    if (inputTz) inputTz.value = (target.z || 0).toFixed(2);

    modal.hidden = false;
  }

  function closeSettings() {
    if (modal) modal.hidden = true;
  }

  function captureCurrentCamera() {
    if (!ctx.t3dCamera) return;
    if (inputAlpha) inputAlpha.value = ctx.t3dCamera.alpha.toFixed(3);
    if (inputBeta) inputBeta.value = ctx.t3dCamera.beta.toFixed(3);
    if (inputRadius) inputRadius.value = ctx.t3dCamera.radius.toFixed(2);
    var tgt = ctx.t3dCamera.target;
    if (inputTx) inputTx.value = (tgt.x || 0).toFixed(2);
    if (inputTy) inputTy.value = (tgt.y || 0).toFixed(2);
    if (inputTz) inputTz.value = (tgt.z || 0).toFixed(2);
  }

  function saveSettings() {
    var newModelUrl = (inputModelUrl ? inputModelUrl.value.trim() : "") || ctx.t3dModelUrl;
    var alpha = parseFloat(inputAlpha ? inputAlpha.value : "-1.2") || -1.2;
    var beta = parseFloat(inputBeta ? inputBeta.value : "1.1") || 1.1;
    var radius = parseFloat(inputRadius ? inputRadius.value : "9") || 9;
    var tx = parseFloat(inputTx ? inputTx.value : "0") || 0;
    var ty = parseFloat(inputTy ? inputTy.value : "0") || 0;
    var tz = parseFloat(inputTz ? inputTz.value : "0") || 0;

    var newCamPos = { alpha: alpha, beta: beta, radius: radius };

    // 1. Apply to active camera immediately
    if (ctx.t3dCamera) {
      ctx.t3dCamera.alpha = alpha;
      ctx.t3dCamera.beta = beta;
      ctx.t3dCamera.radius = radius;
      ctx.t3dCamera.setTarget(new BABYLON.Vector3(tx, ty, tz));
    }

    // 2. Persist in widget context settings
    ctx.settings = ctx.settings || {};
    ctx.settings.modelUrl = newModelUrl;
    ctx.settings.cameraPosition = newCamPos;
    if (ctx.widgetConfig) {
      ctx.widgetConfig.settings = ctx.settings;
    }
    ctx.t3dCameraPos = newCamPos;
    ctx.t3dOverviewCameraPos = newCamPos;

    // 3. If modelUrl changed, reload the model
    if (newModelUrl !== ctx.t3dModelUrl) {
      ctx.t3dModelUrl = newModelUrl;
      t3dReloadModel(ctx, newModelUrl);
    }

    closeSettings();
  }

  if (btnSettings) btnSettings.addEventListener("click", openSettings);
  if (btnClose) btnClose.addEventListener("click", closeSettings);
  if (btnCancel) btnCancel.addEventListener("click", closeSettings);
  if (backdrop) backdrop.addEventListener("click", closeSettings);
  if (btnCapture) btnCapture.addEventListener("click", captureCurrentCamera);
  if (btnSave) btnSave.addEventListener("click", saveSettings);
}

self.onResize = function () {
  if (self.ctx.t3dEngine) {
    self.ctx.t3dEngine.resize();
  }
};

self.onDestroy = function () {
  self.ctx.t3dDisposed = true;
  self.ctx.t3dRenderActive = false;

  if (self.ctx.t3dEngine) {
    self.ctx.t3dEngine.stopRenderLoop();
  }
  var labelIds = Object.keys(self.ctx.t3dStatusLabelEls || {});
  for (var li = 0; li < labelIds.length; li++) {
    self.ctx.t3dStatusLabelEls[labelIds[li]].remove();
  }
  self.ctx.t3dStatusLabelEls = {};
  var particleGroups = Object.keys(self.ctx.t3dParticleSystems || {});
  for (var i = 0; i < particleGroups.length; i++) {
    var ps = self.ctx.t3dParticleSystems[particleGroups[i]];
    if (ps) {
      ps.stop();
      ps.dispose();
    }
  }
  self.ctx.t3dParticleSystems = null;
  if (self.ctx.t3dUi) {
    self.ctx.t3dUi.dispose();
    self.ctx.t3dUi = null;
  }
  if (self.ctx.t3dScene) {
    self.ctx.t3dScene.dispose();
    self.ctx.t3dScene = null;
  }
  if (self.ctx.t3dEngine) {
    self.ctx.t3dEngine.dispose();
    self.ctx.t3dEngine = null;
  }
  self.ctx.t3dMeshEntities = null;
  self.ctx.t3dCamera = null;
  self.ctx.t3dHighlightLayer = null; // disposed by t3dScene.dispose() above
  self.ctx.t3dHoveredMesh = null;
  self.ctx.container = null;
};

// CONTROLLER_SCRIPT_END
