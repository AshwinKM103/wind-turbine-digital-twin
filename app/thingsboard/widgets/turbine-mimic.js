/**
 * @fileoverview ThingsBoard CE custom widget controller and templates for 2D process mimic schematic.
 * Renders SVG hotspot components, dynamic health state chips, and real-time telemetry KPI badges.
 *
 * @module turbine-mimic
 * @see {@link app/tools/package_widget_type.py} for compilation into widget-type JSON.
 */


// Template (HTML) packaged into descriptor.templateHtml
const TEMPLATE_HTML = `
<div class="turbine-mimic" id="tm-root">
  <div class="tm-toolbar">
    <span class="tm-title" id="tm-title">Turbine</span>
    <span class="tm-state-chip state-healthy" id="tm-state-chip">
      <span class="tm-state-dot"></span>
      <span class="tm-state-text" id="tm-state-text">Healthy</span>
    </span>
  </div>

  <div class="tm-diagram-wrap">
    <!-- Production schematic inlined from app/visualization/turbine-schematic.svg -->
    <svg id="tm-svg-root" viewBox="0 0 960 540" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="svg-title svg-desc">
      <title id="svg-title">Wind Turbine Digital Twin — Live Schematic</title>
      <desc id="svg-desc">
        Steam-turbine driven digital twin schematic (Phase 1 MVP). Twelve headline KPI
        values (text elements with id="val-*") are always visible. Component groups
        carry id="hotspot-*", a data-key/data-sensors attribute set for click binding,
        and a state-* CSS class swapped at runtime by the Thingsboard widget
        (HEALTHY/WARNING/ALARM/DOWN). No datakey VALUES are hardcoded here — only
        attribute names/ids that the widget phase binds to live IoTDB telemetry.
      </desc>

      <style>
        :root {
          --header-bg: #17212e;
          --header-fg: #f5f7fa;
          --pipe: #37474f;
          --shaft: #263238;
          --box-stroke: #90a4ae;
          --box-fill: #ffffff;
          --label: #263238;
          --sublabel: #607d8b;
          --unit: #78909c;
          --dashed: #90a4ae;
        }

        #tm-svg-root { width: 100%; height: auto; display: block; background: #eef2f5; }

        #tm-svg-root text { font-family: "Segoe UI", Arial, Helvetica, sans-serif; fill: var(--label); }

        .title-text { fill: var(--header-fg); font-size: 20px; font-weight: 600; }
        .subtitle-text { fill: var(--header-fg); font-size: 11px; opacity: 0.75; }

        .legend-text { fill: var(--header-fg); font-size: 10px; }

        .component-box {
          fill: var(--box-fill);
          stroke: var(--box-stroke);
          stroke-width: 1.5;
          rx: 8;
        }

        .comp-label {
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.4px;
          fill: var(--label);
        }

        .row-tag {
          font-size: 10px;
          font-weight: 700;
          fill: var(--sublabel);
        }

        .kpi-value {
          font-size: 16px;
          font-weight: 700;
          fill: #10233e;
        }

        .kpi-unit {
          font-size: 10px;
          font-weight: 400;
          fill: var(--unit);
        }

        .aux-list {
          font-size: 8.5px;
          font-style: italic;
          fill: var(--sublabel);
        }

        .pipe { stroke: var(--pipe); stroke-width: 3; fill: none; }
        .shaft { stroke: var(--shaft); stroke-width: 5; fill: none; stroke-linecap: round; }
        .connector { stroke: var(--dashed); stroke-width: 1.5; fill: none; stroke-dasharray: 5 4; }

        .valve-glyph { fill: #ab47bc; stroke: #6a1b9a; stroke-width: 1; }

        .hotspot { cursor: pointer; transition: fill 0.25s ease, stroke 0.25s ease; }

        /* --- State colour classes (swapped at runtime by the Thingsboard widget) --- */
        .state-healthy { fill: #e6f4ea; stroke: #2e7d32; }
        .state-warning { fill: #fff8e1; stroke: #f9a825; }
        .state-alarm   { fill: #fdecea; stroke: #c62828; }
        .state-down    { fill: #eceff1; stroke: #607d8b; stroke-dasharray: 4 3; }

        .status-dot { stroke: #ffffff; stroke-width: 1; }
        .status-dot.state-healthy { fill: #2e7d32; }
        .status-dot.state-warning { fill: #f9a825; }
        .status-dot.state-alarm   { fill: #c62828; }
        .status-dot.state-down    { fill: #607d8b; }

        .rotor-hub { fill: #b0bec5; stroke: #455a64; stroke-width: 1.5; }
        .rotor-blade { fill: #78909c; stroke: #37474f; stroke-width: 0.75; }

        .footnote { font-size: 9px; fill: #90a4ae; }

        /* --- Mobile: bump legibility, hide non-essential chrome, thicken touch targets --- */
        @media (max-width: 600px) {
          .comp-label { font-size: 14px; }
          .kpi-value { font-size: 19px; }
          .kpi-unit { font-size: 12px; }
          .row-tag { font-size: 12px; }
          .aux-list { display: none; }
          .footnote { display: none; }
          .hotspot { stroke-width: 2.5; }
          .subtitle-text { display: none; }
        }
      </style>

      <!-- ============================== HEADER ============================== -->
      <rect x="0" y="0" width="960" height="50" fill="var(--header-bg)"></rect>
      <text class="title-text" x="20" y="24">Turbine Digital Twin — Live Schematic</text>
      <text class="subtitle-text" x="20" y="40">Steam turbine · gearbox · dynamometer — 1 Hz live telemetry</text>

      <!-- State legend (always visible, colour + label, not colour alone) -->
      <g id="legend" transform="translate(560,10)">
        <rect x="0" y="4" width="11" height="11" class="state-healthy" stroke-width="1"></rect>
        <text class="legend-text" x="15" y="13">Healthy</text>
        <rect x="80" y="4" width="11" height="11" class="state-warning" stroke-width="1"></rect>
        <text class="legend-text" x="95" y="13">Warning</text>
        <rect x="165" y="4" width="11" height="11" class="state-alarm" stroke-width="1"></rect>
        <text class="legend-text" x="180" y="13">Alarm</text>
        <rect x="245" y="4" width="11" height="11" class="state-down" stroke-width="1"></rect>
        <text class="legend-text" x="260" y="13">Down / Stale</text>
      </g>

      <!-- ============================== PIPING / SHAFT ============================== -->
      <line class="pipe" x1="190" y1="100" x2="270" y2="100"></line>
      <line class="pipe" x1="380" y1="100" x2="400" y2="100"></line>
      <line class="pipe" x1="510" y1="100" x2="520" y2="103"></line>
      <line class="shaft" x1="690" y1="175" x2="730" y2="175"></line>
      <line class="shaft" x1="860" y1="175" x2="875" y2="175"></line>

      <!-- Valve glyph (Emergency Stop Valve, decorative — not a bound hotspot) -->
      <g id="esv-valve" transform="translate(225,100)">
        <path class="valve-glyph" d="M -9,-8 L 0,0 L -9,8 Z"></path>
        <path class="valve-glyph" d="M 9,-8 L 0,0 L 9,8 Z"></path>
      </g>

      <!-- Connector drops from lower-band components up into the main flow -->
      <line class="connector" x1="275" y1="300" x2="275" y2="150"></line>
      <line class="connector" x1="525" y1="390" x2="525" y2="260"></line>
      <line class="connector" x1="655" y1="390" x2="655" y2="228"></line>
      <line class="connector" x1="800" y1="300" x2="800" y2="220"></line>

      <!-- ============================== INLET STEAM ============================== -->
      <g id="hotspot-inlet-steam" class="hotspot state-healthy" data-key="PT_109A"
         data-sensors="PT_109A,PT_110A,PT_110B,TT_109A,FT_110A,PT_111B">
        <rect class="component-box state-healthy" x="20" y="70" width="170" height="110"></rect>
        <text class="comp-label" x="105" y="86" text-anchor="middle">INLET STEAM</text>

        <text class="row-tag" x="30" y="106">P</text>
        <text id="val-inlet-pressure" class="kpi-value" data-key="PT_109A" data-unit="bar"
              x="178" y="108" text-anchor="end">--</text>
        <text class="kpi-unit" x="182" y="108">bar</text>

        <text class="row-tag" x="30" y="126">T</text>
        <text class="aux-list" x="45" y="126">TT_109A (aux)</text>

        <text class="row-tag" x="30" y="146">M</text>
        <text id="val-inlet-flow" class="kpi-value" data-key="FT_110A" data-unit="TPH"
              x="178" y="148" text-anchor="end">--</text>
        <text class="kpi-unit" x="182" y="148">TPH</text>

        <text class="aux-list" x="30" y="170">also: PT_110A, PT_110B, PT_111B</text>
      </g>

      <!-- ============================== TV1 ============================== -->
      <g id="hotspot-tv1" class="hotspot state-healthy" data-key="PT_111" data-sensors="PT_111,TT_111">
        <rect class="component-box state-healthy" x="270" y="60" width="110" height="90"></rect>
        <text class="comp-label" x="325" y="76" text-anchor="middle">TV1</text>

        <text class="row-tag" x="278" y="98">P</text>
        <text class="aux-list" x="295" y="98">PT_111 (aux)</text>

        <text class="row-tag" x="278" y="120">T</text>
        <text class="aux-list" x="295" y="120">TT_111 (aux)</text>
      </g>

      <!-- ============================== TV2 ============================== -->
      <g id="hotspot-tv2" class="hotspot state-healthy" data-key="PT_112" data-sensors="PT_112,TT_112">
        <rect class="component-box state-healthy" x="400" y="60" width="110" height="90"></rect>
        <text class="comp-label" x="455" y="76" text-anchor="middle">TV2</text>
        <text class="row-tag" x="408" y="98">P</text>
        <text class="aux-list" x="425" y="98">PT_112 (aux)</text>
        <text class="row-tag" x="408" y="120">T</text>
        <text class="aux-list" x="425" y="120">TT_112 (aux)</text>
      </g>

      <!-- ============================== TURBINE ROTOR ============================== -->
      <g id="hotspot-rotor" class="hotspot state-healthy"
         data-key="TURBINE_SPEED_RPM" data-sensors="TURBINE_SPEED_RPM,PYRO_T,PT_111C,TT_111C,TT_111C_R">
        <polygon class="component-box state-healthy" points="520,90 520,260 690,215 690,135"></polygon>
        <text class="comp-label" x="605" y="270" text-anchor="middle">TURBINE</text>

        <!-- Rotor element: rotation origin (605,175). Widget sets
             transform="rotate(<deg> 605 175)" each tick from TURBINE_SPEED_RPM. -->
        <g id="rotor-blades" data-key="TURBINE_SPEED_RPM" data-unit="RPM"
           transform="rotate(0 605 175)">
          <rect class="rotor-blade" x="601" y="122" width="8" height="106" rx="3"></rect>
          <rect class="rotor-blade" x="601" y="122" width="8" height="106" rx="3" transform="rotate(60 605 175)"></rect>
          <rect class="rotor-blade" x="601" y="122" width="8" height="106" rx="3" transform="rotate(120 605 175)"></rect>
          <circle class="rotor-hub" cx="605" cy="175" r="16"></circle>
        </g>

        <text class="row-tag" x="540" y="72" text-anchor="middle">SPEED</text>
        <text id="val-turbine-speed" class="kpi-value" data-key="TURBINE_SPEED_RPM" data-unit="RPM"
              x="540" y="55" text-anchor="middle">--</text>
        <text class="kpi-unit" x="540" y="86" text-anchor="middle">RPM</text>
      </g>

      <!-- ============================== TURBOVISORY VIBRATION BAND ============================== -->
      <g id="hotspot-vibration" class="hotspot state-healthy"
         data-key="ZT_600"
         data-sensors="ZT_600,ZT_601,XT_600,XT_601,XT_602,XT_603,XT_604,XT_605,XT_606,XT_607">
        <rect class="component-box state-healthy" x="460" y="298" width="250" height="50"></rect>
        <text class="comp-label" x="585" y="311" text-anchor="middle" font-size="10">VIBRATION MONITORING</text>

        <text id="val-vib-gb-x" class="kpi-value" data-key="XT_600" data-unit="mm/s"
              x="470" y="336" font-size="11">--</text>
        <text class="kpi-unit" x="470" y="345" font-size="7">XT_600 mm/s</text>

        <text id="val-vib-gb-y" class="kpi-value" data-key="XT_601" data-unit="mm/s"
              x="518" y="336" font-size="11">--</text>
        <text class="kpi-unit" x="518" y="345" font-size="7">XT_601 mm/s</text>

        <text id="val-vib-rotor-x" class="kpi-value" data-key="XT_604" data-unit="mm/s"
              x="566" y="336" font-size="11">--</text>
        <text class="kpi-unit" x="566" y="345" font-size="7">XT_604 mm/s</text>

        <text id="val-vib-rotor-y" class="kpi-value" data-key="XT_605" data-unit="mm/s"
              x="614" y="336" font-size="11">--</text>
        <text class="kpi-unit" x="614" y="345" font-size="7">XT_605 mm/s</text>

        <text id="val-vib-gb-z1" class="kpi-value" data-key="ZT_600" data-unit="mm/s"
              x="662" y="336" font-size="11">--</text>
        <text class="kpi-unit" x="662" y="345" font-size="7">ZT_600 mm/s</text>
      </g>

      <!-- ============================== GEARBOX ============================== -->
      <g id="hotspot-gearbox" class="hotspot state-healthy"
         data-key="GB_TRQ" data-sensors="GB_TRQ,PYRO_GB,TT_109A,TT_110A,TT_110B,XT_604,XT_605,XT_606,XT_607">
        <rect class="component-box state-healthy" x="730" y="70" width="130" height="150"></rect>
        <text class="comp-label" x="795" y="88" text-anchor="middle">GEARBOX (GB)</text>

        <text class="row-tag" x="740" y="112">TRQ</text>
        <text id="val-gb-torque" class="kpi-value" data-key="GB_TRQ" data-unit="kN.m"
              x="852" y="114" text-anchor="end">--</text>
        <text class="kpi-unit" x="855" y="114">kN.m</text>

        <text class="row-tag" x="740" y="136">T1</text>
        <text id="val-pyro-t" class="kpi-value" data-key="PYRO_T" data-unit="degC"
              x="852" y="138" text-anchor="end">--</text>
        <text class="kpi-unit" x="855" y="138">°C</text>

        <text class="row-tag" x="740" y="160">T2</text>
        <text id="val-pyro-gb" class="kpi-value" data-key="PYRO_GB" data-unit="degC"
              x="852" y="162" text-anchor="end">--</text>
        <text class="kpi-unit" x="855" y="162">°C</text>

        <text class="aux-list" x="740" y="182">PYRO_T / PYRO_GB pyrometers</text>
      </g>

      <!-- ============================== DYNAMOMETER / GENERATOR ============================== -->
      <g id="hotspot-dyno" class="hotspot state-healthy"
         data-key="DYNO_WATER_O_L" data-sensors="DYNO_WATER_O_L,PT_253,RTD_219A,RTD_219B,RTD_220,RTD_221">
        <rect class="component-box state-healthy" x="875" y="115" width="75" height="120" rx="8"></rect>
        <text class="comp-label" x="912" y="133" text-anchor="middle" font-size="11">DYNO</text>
        <text class="aux-list" x="885" y="152">Water O/L</text>
        <text class="aux-list" x="885" y="165">RTD 219/220/221</text>
      </g>

      <!-- ============================== ACTUATOR / PITCH CONTROL ============================== -->
      <g id="hotspot-actuator" class="hotspot state-healthy"
         data-key="ACT_POS_FB" data-sensors="ACT_POS_FB,HP_DEMAND,PT_150A,PT_150B,TT_150A,TT_150B">
        <rect class="component-box state-healthy" x="190" y="300" width="150" height="65"></rect>
        <text class="comp-label" x="265" y="316" text-anchor="middle">ACTUATOR</text>
        <text class="row-tag" x="198" y="340">POS</text>
        <text class="aux-list" x="222" y="340">ACT_POS_FB (aux)</text>
        <text class="aux-list" x="198" y="358">HP_DEMAND (aux)</text>
      </g>

      <!-- ============================== WHEEL CASE ============================== -->
      <g id="hotspot-wheelcase" class="hotspot state-healthy"
         data-key="PT_120" data-sensors="PT_120,TT_120,TT_120_R,PT_111C,TT_111C,TT_111C_R">
        <rect class="component-box state-healthy" x="460" y="390" width="130" height="65"></rect>
        <text class="comp-label" x="525" y="406" text-anchor="middle">WHEEL CASE</text>
        <text class="row-tag" x="468" y="430">P</text>
        <text class="aux-list" x="490" y="430">PT_120 (aux)</text>
        <text class="aux-list" x="468" y="448">TT_120 / TT_120_R (aux)</text>
      </g>

      <!-- ============================== INTER GBC ============================== -->
      <g id="hotspot-intergbc" class="hotspot state-healthy"
         data-key="PT_111C" data-sensors="PT_111C,TT_111C,TT_111C_R">
        <rect class="component-box state-healthy" x="600" y="390" width="110" height="65"></rect>
        <text class="comp-label" x="655" y="406" text-anchor="middle" font-size="11">INTER GBC</text>
        <text class="aux-list" x="608" y="428">PT_111C (aux)</text>
        <text class="aux-list" x="608" y="440">TT_111C / TT_111C_R</text>
      </g>

      <!-- ============================== EXHAUST / HYDRAULIC POWER UNIT ============================== -->
      <g id="hotspot-exhaust" class="hotspot state-healthy"
         data-key="PT_150A" data-sensors="PT_163,TT_163,PT_150A,PT_150B,TT_150A,TT_150B">
        <rect class="component-box state-healthy" x="730" y="300" width="150" height="155"></rect>
        <text class="comp-label" x="805" y="318" text-anchor="middle" font-size="11">EXHAUST / HYD</text>

        <text class="row-tag" x="738" y="342">HYD&#160;P</text>
        <text id="val-hydraulic-pressure" class="kpi-value" data-key="PT_150A" data-unit="kg/cm2"
              x="872" y="344" text-anchor="end">--</text>
        <text class="kpi-unit" x="875" y="344">kg/cm²</text>

        <text class="row-tag" x="738" y="366">LO&#160;RET&#160;P</text>
        <text class="aux-list" x="778" y="366">PT_163 (aux)</text>

        <text class="aux-list" x="738" y="390">TT_163 / PT_150B / TT_150A/B</text>
      </g>

      <!-- ============================== LEAKAGE LINES 1–3 ============================== -->
      <g id="hotspot-leakage1" class="hotspot state-healthy" data-key="PT_162" data-sensors="PT_162,TT_162,FT_162">
        <rect class="component-box state-healthy" x="20" y="300" width="150" height="48"></rect>
        <text class="comp-label" x="95" y="316" text-anchor="middle" font-size="11">LEAKAGE 1</text>
        <text class="aux-list" x="28" y="334">PT_162 / TT_162 / FT_162</text>
      </g>

      <g id="hotspot-leakage2" class="hotspot state-healthy" data-key="PT_161" data-sensors="PT_161,TT_161">
        <rect class="component-box state-healthy" x="20" y="355" width="150" height="48"></rect>
        <text class="comp-label" x="95" y="371" text-anchor="middle" font-size="11">LEAKAGE 2</text>
        <text class="aux-list" x="28" y="389">PT_161 / TT_161</text>
      </g>

      <g id="hotspot-leakage3" class="hotspot state-healthy" data-key="PT_160" data-sensors="PT_160,TT_160">
        <rect class="component-box state-healthy" x="20" y="410" width="150" height="45"></rect>
        <text class="comp-label" x="95" y="426" text-anchor="middle" font-size="11">LEAKAGE 3</text>
        <text class="aux-list" x="28" y="443">PT_160 / TT_160</text>
      </g>

      <!-- Status dots — colour-plus-position redundancy for each hotspot -->
      <circle class="status-dot state-healthy" cx="184" cy="76" r="4"></circle>
      <circle class="status-dot state-healthy" cx="374" cy="66" r="4"></circle>
      <circle class="status-dot state-healthy" cx="504" cy="66" r="4"></circle>
      <circle class="status-dot state-healthy" cx="684" cy="96" r="4"></circle>
      <circle class="status-dot state-healthy" cx="704" cy="304" r="4"></circle>
      <circle class="status-dot state-healthy" cx="854" cy="76" r="4"></circle>
      <circle class="status-dot state-healthy" cx="944" cy="121" r="4"></circle>
      <circle class="status-dot state-healthy" cx="334" cy="306" r="4"></circle>
      <circle class="status-dot state-healthy" cx="584" cy="396" r="4"></circle>
      <circle class="status-dot state-healthy" cx="704" cy="396" r="4"></circle>
      <circle class="status-dot state-healthy" cx="874" cy="306" r="4"></circle>
      <circle class="status-dot state-healthy" cx="164" cy="306" r="4"></circle>
      <circle class="status-dot state-healthy" cx="164" cy="361" r="4"></circle>
      <circle class="status-dot state-healthy" cx="164" cy="416" r="4"></circle>

      <!-- ============================== FOOTNOTE ============================== -->
      <text class="footnote" x="20" y="512">
        Units: kg/cm² pressure · °C temperature · TPH mass flow · kN.m torque · RPM speed · % position.
      </text>
      <text class="footnote" x="20" y="526">
        data-key attributes bind to live IoTDB tags; no tenant, customer, or datakey VALUES are hardcoded in this file.
      </text>
    </svg>

    <div id="tm-down-banner" class="tm-down-banner" hidden>
      <span class="tm-down-icon">&#9888;</span>
      <span id="tm-down-text">NO DATA — turbine reporting stale</span>
    </div>
  </div>

  <div id="tm-kpi-grid" class="tm-kpi-grid"></div>

  <!-- Shared hover popover for KPI tiles -->
  <div id="tm-tooltip" class="tm-tooltip" role="tooltip" aria-hidden="true" hidden>
    <div class="tm-tt-head">
      <span id="tm-tt-label" class="tm-tt-label"></span>
      <span id="tm-tt-status" class="tm-tt-status"></span>
    </div>
    <div class="tm-tt-reading">
      <span id="tm-tt-value" class="tm-tt-value"></span>
      <span id="tm-tt-unit" class="tm-tt-unit"></span>
      <span id="tm-tt-pct" class="tm-tt-pct"></span>
    </div>
    <div id="tm-tt-bands" class="tm-tt-bands"></div>
    <div id="tm-tt-age" class="tm-tt-age"></div>
    <div id="tm-tt-note" class="tm-tt-note"></div>
  </div>
</div>
`;

// Template (CSS) packaged into descriptor.templateCss
const TEMPLATE_CSS = `
.turbine-mimic {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 600px;
  box-sizing: border-box;
  font-family: Roboto, "Helvetica Neue", sans-serif;
  overflow: hidden;
  position: relative;
}

.tm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
}

.tm-title {
  font-size: 16px;
  font-weight: 600;
  color: #f8fafc;
}

.tm-state-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.tm-state-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

/* Status colours paired with icons and labels */
.state-healthy .tm-state-dot, .tm-state-chip.state-healthy .tm-state-dot { background: #2e7d32; }
.state-healthy, .tm-state-chip.state-healthy { background: rgba(46,125,50,0.12); color: #1b5e20; }

.state-warning .tm-state-dot, .tm-state-chip.state-warning .tm-state-dot { background: #f9a825; }
.state-warning, .tm-state-chip.state-warning { background: rgba(249,168,37,0.15); color: #8d6e00; }

.state-alarm .tm-state-dot, .tm-state-chip.state-alarm .tm-state-dot { background: #c62828; }
.state-alarm, .tm-state-chip.state-alarm { background: rgba(198,40,40,0.15); color: #b71c1c; }

.state-down .tm-state-dot, .tm-state-chip.state-down .tm-state-dot { background: #757575; }
.state-down, .tm-state-chip.state-down { background: rgba(117,117,117,0.15); color: #424242; }

.tm-diagram-wrap {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  /* Skip offscreen layout and paint for fleet view scalability */
  content-visibility: auto;
  contain-intrinsic-size: auto 320px;
}

#tm-svg-root {
  width: 100%;
  height: 100%;
  display: block;
}

/* Runtime state-colour modifiers toggled on hotspot elements */
.hotspot.tm-state-warning .component-box { fill: #fff8e1; stroke: #f9a825; stroke-width: 2.5; }
.hotspot.tm-state-alarm .component-box { fill: #fdecea; stroke: #c62828; stroke-width: 2.5; animation: tm-pulse 1.1s ease-in-out infinite; }
.hotspot.tm-state-down .component-box { fill: #eceff1; stroke: #607d8b; stroke-dasharray: 4 3; }

@keyframes tm-pulse {
  0%   { opacity: 1; }
  50%  { opacity: 0.55; }
  100% { opacity: 1; }
}

/* Rotor rotation transition */
#rotor-blades {
  transition: transform 0.95s linear;
}

.turbine-mimic.state-down #tm-svg-root {
  filter: grayscale(1);
}

.tm-down-banner {
  position: absolute;
  top: 8px;
  left: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: rgba(66,66,66,0.9);
  color: #fff;
  border-radius: 4px;
  font-size: 13px;
}
/* The banner is toggled via the "hidden" property in renderStaleness(). The
   "display: flex" above is an author rule and outranks the UA stylesheet's
   default [hidden] rule, so without this override the banner stays painted
   even when the widget has correctly decided the turbine is live. */
.tm-down-banner[hidden],
.tm-down-banner.hidden {
  display: none !important;
}

.tm-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 6px;
  padding: 8px 12px 12px;
  flex: 0 0 auto;
}

.tm-kpi-tile {
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 6px;
  padding: 6px 8px;
  background: #fff;
}

.tm-kpi-tile.tm-state-warning { border-color: #f9a825; background: rgba(249,168,37,0.08); }
.tm-kpi-tile.tm-state-alarm { border-color: #c62828; background: rgba(198,40,40,0.08); }
.tm-kpi-tile.tm-state-down { border-color: #9e9e9e; background: rgba(158,158,158,0.12); }

/* Alert pulse animations distinguishing warning and critical severity */
@keyframes tm-tile-pulse-warning {
  0%, 100% { box-shadow: 0 0 0 0 rgba(249,168,37,0.00); }
  50%      { box-shadow: 0 0 0 3px rgba(249,168,37,0.35); }
}

@keyframes tm-tile-pulse-alarm {
  0%, 100% { box-shadow: 0 0 0 0 rgba(198,40,40,0.00); }
  50%      { box-shadow: 0 0 0 4px rgba(198,40,40,0.55); }
}

.tm-kpi-tile.tm-state-warning { animation: tm-tile-pulse-warning 2.4s ease-in-out infinite; }
.tm-kpi-tile.tm-state-alarm { animation: tm-tile-pulse-alarm 1.4s ease-in-out infinite; }

/* Suppress animation for stale tiles */
.tm-kpi-tile.tm-state-down { animation: none; }

/* Respect reduced motion preference */
@media (prefers-reduced-motion: reduce) {
  .tm-kpi-tile.tm-state-warning,
  .tm-kpi-tile.tm-state-alarm,
  .hotspot.tm-state-alarm .component-box {
    animation: none;
  }
  .tm-kpi-tile.tm-state-warning { box-shadow: 0 0 0 2px rgba(249,168,37,0.45); }
  .tm-kpi-tile.tm-state-alarm { box-shadow: 0 0 0 3px rgba(198,40,40,0.60); }
}

/* Hover/focus tooltip styling */
.tm-kpi-tile {
  cursor: help;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.tm-kpi-tile:focus-visible {
  outline: 2px solid #1976d2;
  outline-offset: 1px;
}

.tm-tooltip {
  position: absolute;
  z-index: 20;
  min-width: 200px;
  max-width: 280px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(23,33,46,0.97);
  color: #f5f7fa;
  font-size: 12px;
  line-height: 1.45;
  box-shadow: 0 4px 14px rgba(0,0,0,0.35);
  pointer-events: none;
}

.tm-tt-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.tm-tt-label { font-weight: 600; }

.tm-tt-status {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
}

.tm-tt-status.tm-tt-ok { background: rgba(46,125,50,0.30); color: #a5d6a7; }
.tm-tt-status.tm-tt-warning { background: rgba(249,168,37,0.30); color: #ffe082; }
.tm-tt-status.tm-tt-critical { background: rgba(198,40,40,0.35); color: #ef9a9a; }
.tm-tt-status.tm-tt-stale { background: rgba(158,158,158,0.30); color: #e0e0e0; }
.tm-tt-status.tm-tt-none { background: rgba(120,144,156,0.30); color: #cfd8dc; }

.tm-tt-reading { margin-bottom: 5px; }
.tm-tt-value { font-size: 18px; font-weight: 600; }
.tm-tt-unit { font-size: 11px; opacity: 0.75; margin-left: 3px; }
.tm-tt-pct { font-size: 11px; opacity: 0.75; margin-left: 6px; }

.tm-tt-bands { margin-bottom: 4px; }

.tm-tt-band-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  opacity: 0.92;
}

.tm-tt-swatch {
  width: 9px;
  height: 9px;
  border-radius: 2px;
  flex: 0 0 auto;
}

.tm-tt-swatch.tm-tt-sw-ok { background: #66bb6a; }
.tm-tt-swatch.tm-tt-sw-warn { background: #f9a825; }
.tm-tt-swatch.tm-tt-sw-crit { background: #e53935; }

.tm-tt-age, .tm-tt-note { font-size: 11px; opacity: 0.7; }
.tm-tt-note { margin-top: 3px; font-style: italic; }

.tm-kpi-label {
  font-size: 11px;
  color: rgba(0,0,0,0.6);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tm-kpi-value {
  font-size: 18px;
  font-weight: 500;
  color: rgba(0,0,0,0.87);
}

.tm-kpi-unit {
  font-size: 11px;
  color: rgba(0,0,0,0.5);
  margin-left: 3px;
}

.tm-kpi-icon {
  font-size: 12px;
  margin-right: 4px;
}

/* Mobile: 960x540 desktop schematic collapses to a stacked 600px-min layout.
   Thingsboard mobile app renders the widget inside a narrow webview, so this
   media query is the practical trigger rather than a device check. */
@media (max-width: 700px) {
  .turbine-mimic { min-width: 320px; }
  .tm-diagram-wrap { min-height: 220px; }
  .tm-kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .tm-title { font-size: 14px; }
}
`;

// Controller (JS) ThingsBoard Widget Controller
/* eslint-disable no-unused-vars */
// CONTROLLER_SCRIPT_START

// Mount an idempotent fixed-position button to trigger PDF test report export.
function tmMountPdfExportButton() {
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
  tmMountPdfExportButton();

  var settings = self.ctx.settings || {};

  self.ctx.maxRpm = Number(settings.maxRpm) || 14000;
  self.ctx.staleThresholdSeconds = Number(settings.staleThresholdSeconds) || 120;
  // Merge user threshold overrides with defaults
  self.ctx.thresholds = mergeThresholds(DEFAULT_THRESHOLDS, settings.thresholds);
  self.ctx.kpiOrder = settings.kpiOrder || DEFAULT_KPI_ORDER;

  self.ctx.container = self.ctx.$container ? self.ctx.$container[0] : null;
  self.ctx.svgRoot = self.ctx.container ? self.ctx.container.querySelector('#tm-svg-root') : null;
  // Separate static casing hotspot from rotating blade element
  self.ctx.rotorHotspotEl = self.ctx.container ? self.ctx.container.querySelector('#hotspot-rotor') : null;
  self.ctx.rotorBladesEl = self.ctx.container ? self.ctx.container.querySelector('#rotor-blades') : null;
  self.ctx.kpiGridEl = self.ctx.container ? self.ctx.container.querySelector('#tm-kpi-grid') : null;
  self.ctx.downBannerEl = self.ctx.container ? self.ctx.container.querySelector('#tm-down-banner') : null;
  if (self.ctx.downBannerEl) {
    self.ctx.downBannerEl.hidden = true;
    self.ctx.downBannerEl.style.display = 'none';
  }
  self.ctx.downTextEl = self.ctx.container ? self.ctx.container.querySelector('#tm-down-text') : null;
  self.ctx.titleEl = self.ctx.container ? self.ctx.container.querySelector('#tm-title') : null;
  self.ctx.stateChipEl = self.ctx.container ? self.ctx.container.querySelector('#tm-state-chip') : null;
  self.ctx.stateTextEl = self.ctx.container ? self.ctx.container.querySelector('#tm-state-text') : null;

  if (self.ctx.titleEl) {
    self.ctx.titleEl.textContent = settings.title || (self.ctx.widgetTitle || 'Turbine');
  }
  if (self.ctx.downTextEl) {
    self.ctx.downTextEl.textContent =
      'NO DATA — turbine reporting stale (>' + self.ctx.staleThresholdSeconds + 's)';
  }

  // Shared tooltip popover reused across KPI tiles
  self.ctx.tooltipEl = self.ctx.container ? self.ctx.container.querySelector('#tm-tooltip') : null;
  self.ctx.tooltipEls = self.ctx.container ? {
    label:  self.ctx.container.querySelector('#tm-tt-label'),
    status: self.ctx.container.querySelector('#tm-tt-status'),
    value:  self.ctx.container.querySelector('#tm-tt-value'),
    unit:   self.ctx.container.querySelector('#tm-tt-unit'),
    pct:    self.ctx.container.querySelector('#tm-tt-pct'),
    bands:  self.ctx.container.querySelector('#tm-tt-bands'),
    age:    self.ctx.container.querySelector('#tm-tt-age'),
    note:   self.ctx.container.querySelector('#tm-tt-note')
  } : {};
  // Active tooltip key, or null when hidden
  self.ctx.activeTooltipKey = null;

  self.ctx.cumulativeRotorDeg = 0;
  self.ctx.isStale = false;
  self.ctx.overallState = 'healthy';
  self.ctx.overallStateLabel = 'Healthy';

  self.ctx.kpiTileEls = {};
  // Cache rendered values to skip redundant DOM writes
  self.ctx.kpiRendered = {};
  self.ctx.latestByKey = {};
  // Memoized threshold bands keyed by dataKey and operating state
  self.ctx.bandCache = {};
  self.ctx.perf = { ticks: 0, tileWrites: 0, tileSkips: 0, lastTickMs: 0 };
  if (self.ctx.container) {
    self.ctx.container.__tmPerf = self.ctx.perf;
  }
};

self.onDataUpdated = function () {
  var tickStart = Date.now();
  var latest = readLatestValues(self.ctx);
  var nowMs = tickStart;

  // Select active threshold bands based on reported operating state
  var stateSample = latest.state;
  var newState =
    stateSample && stateSample.value ? String(stateSample.value) : DEFAULT_STATE;
  if (newState !== self.ctx.operatingState) {
    self.ctx.bandCache = {};
    self.ctx.operatingState = newState;
  }

  self.ctx.latestByKey = latest;
  self.ctx.subsystemHealthByMeshId = readSubsystemHealthByMeshId(latest);

  renderStaleness(self.ctx, latest, nowMs);
  renderRotor(self.ctx, latest);
  renderKpiGrid(self.ctx, latest, nowMs);
  renderOverallState(self.ctx, latest);

  if (self.ctx.activeTooltipKey) {
    updateTooltipContent(self.ctx, self.ctx.activeTooltipKey, nowMs);
  }

  self.ctx.perf.ticks += 1;
  self.ctx.perf.lastTickMs = Date.now() - tickStart;

  if (self.ctx.detectChanges) {
    self.ctx.detectChanges();
  }
};

self.onResize = function () {
};

self.onDestroy = function () {
  // Detach tile event listeners on teardown
  var keys = Object.keys(self.ctx.kpiTileEls || {});
  for (var i = 0; i < keys.length; i++) {
    var tile = self.ctx.kpiTileEls[keys[i]];
    if (tile && tile._tmHandlers && tile.removeEventListener) {
      tile.removeEventListener('mouseenter', tile._tmHandlers.enter);
      tile.removeEventListener('mouseleave', tile._tmHandlers.leave);
      tile.removeEventListener('focus', tile._tmHandlers.enter);
      tile.removeEventListener('blur', tile._tmHandlers.leave);
      tile._tmHandlers = null;
    }
  }

  self.ctx.container = null;
  self.ctx.svgRoot = null;
  self.ctx.rotorHotspotEl = null;
  self.ctx.rotorBladesEl = null;
  self.ctx.kpiGridEl = null;
  self.ctx.downBannerEl = null;
  self.ctx.tooltipEl = null;
  self.ctx.tooltipEls = {};
  self.ctx.activeTooltipKey = null;
  self.ctx.kpiTileEls = {};
  self.ctx.kpiRendered = {};
  self.ctx.latestByKey = {};
  self.ctx.bandCache = {};
};

self.typeParameters = function () {
  return {
    maxDatasources: 1,
    maxDataKeys: -1, // any number of dataKeys — the widget renders whatever the dashboard binds
    singleEntity: true,
    hasDataPageLink: false,
    defaultDataKeysFunction: function () {
      return DEFAULT_KPI_ORDER.map(function (key) {
        return { name: key, label: key, type: 'timeseries' };
      });
    }
  };
};

// -----------------------------------------------------------------------
// Helpers (still inside controllerScript — Thingsboard evaluates the whole
// descriptor.controllerScript string in one scope, so top-level `function`
// and `const` declarations here are visible to self.onInit/onDataUpdated).
// -----------------------------------------------------------------------

// Default KPI display order
var DEFAULT_KPI_ORDER = [
  'TURBINE_SPEED_RPM', 'GB_TRQ', 'PYRO_T', 'PYRO_GB',
  'PT_109A', 'FT_110A', 'PT_150A',
  'XT_600', 'XT_601', 'XT_604', 'XT_605', 'ZT_600'
];

// Metadata for KPI tiles and matching schematic SVG text elements
var KPI_META = {
  TURBINE_SPEED_RPM: { label: 'Speed', unit: 'rpm', icon: '↻', valId: 'val-turbine-speed' },
  GB_TRQ:            { label: 'GB Torque', unit: 'kN·m', icon: '⚙', valId: 'val-gb-torque' },
  PYRO_T:            { label: 'Pyro Temp (Turbine)', unit: '°C', icon: '☀', valId: 'val-pyro-t' },
  PYRO_GB:           { label: 'Pyro Temp (Gearbox)', unit: '°C', icon: '☀', valId: 'val-pyro-gb' },
  PT_109A:           { label: 'Inlet Pressure A', unit: 'bar', icon: '●', valId: 'val-inlet-pressure' },
  FT_110A:           { label: 'Main Water Flow', unit: 'TPH', icon: '≈', valId: 'val-inlet-flow' },
  PT_150A:           { label: 'Hydraulic Pressure A', unit: 'kg/cm²', icon: '●', valId: 'val-hydraulic-pressure' },
  XT_600:            { label: 'GB Vibration X', unit: 'mm/s', icon: '⤳', valId: 'val-vib-gb-x' },
  XT_601:            { label: 'GB Vibration Y', unit: 'mm/s', icon: '⤳', valId: 'val-vib-gb-y' },
  XT_604:            { label: 'Rotor Vibration X', unit: 'mm/s', icon: '⤳', valId: 'val-vib-rotor-x' },
  XT_605:            { label: 'Rotor Vibration Y', unit: 'mm/s', icon: '⤳', valId: 'val-vib-rotor-y' },
  ZT_600:            { label: 'GB Vibration Z1', unit: 'mm/s', icon: '⤳', valId: 'val-vib-gb-z1' }
};

// State-aware thresholds (per operating state: IDLE, RAMP_UP, STEADY_STATE, RAMP_DOWN).
var DEFAULT_STATE = 'STEADY_STATE';

// Operating-state threshold bands calibrated to observed telemetry ranges.
var DEFAULT_THRESHOLDS = {
  TURBINE_SPEED_RPM: {
    IDLE:         { warningMin: -50, warningMax: 300, criticalMin: -100, criticalMax: 600 },
    RAMP_UP:      { warningMin: 1000, warningMax: 12000, criticalMin: 100, criticalMax: 14000 },
    STEADY_STATE: { warningMin: 10000, warningMax: 12100, criticalMin: 9000, criticalMax: 12800 },
    RAMP_DOWN:    { warningMin: 1000, warningMax: 11000, criticalMin: 100, criticalMax: 12500 }
  },
  GB_TRQ: {
    IDLE:         { warningMin: -0.3, warningMax: 0.3, criticalMin: -1.0, criticalMax: 1.0 },
    RAMP_UP:      { warningMin: 0.5, warningMax: 7.5, criticalMin: 0.0, criticalMax: 9.0 },
    STEADY_STATE: { warningMin: 0, warningMax: 0.3, criticalMin: 0, criticalMax: 0.4 },
    RAMP_DOWN:    { warningMin: 0.5, warningMax: 6.5, criticalMin: 0.0, criticalMax: 8.0 }
  },
  PT_109A: {
    IDLE:         { warningMin: 31.0, warningMax: 32.5, criticalMin: 30.5, criticalMax: 32.8 },
    RAMP_UP:      { warningMin: 31.5, warningMax: 33.5, criticalMin: 31.0, criticalMax: 34.0 },
    STEADY_STATE: { warningMin: 30.5, warningMax: 34.0, criticalMin: 29.5, criticalMax: 34.5 },
    RAMP_DOWN:    { warningMin: 31.0, warningMax: 33.2, criticalMin: 30.5, criticalMax: 33.5 }
  },
  XT_600: {
    IDLE:         { warningMin: 0.5, warningMax: 1.5, criticalMin: 0.0, criticalMax: 3.0 },
    RAMP_UP:      { warningMin: 1.0, warningMax: 6.0, criticalMin: 0.2, criticalMax: 8.0 },
    STEADY_STATE: { warningMin: 0, warningMax: 4.5, criticalMin: 0, criticalMax: 6.0 },
    RAMP_DOWN:    { warningMin: 1.0, warningMax: 5.0, criticalMin: 0.2, criticalMax: 7.0 }
  },
  XT_601: {
    IDLE:         { warningMin: 0.5, warningMax: 1.5, criticalMin: 0.0, criticalMax: 3.0 },
    RAMP_UP:      { warningMin: 1.0, warningMax: 6.0, criticalMin: 0.2, criticalMax: 8.0 },
    STEADY_STATE: { warningMin: 0, warningMax: 4.5, criticalMin: 0, criticalMax: 6.0 },
    RAMP_DOWN:    { warningMin: 1.0, warningMax: 5.0, criticalMin: 0.2, criticalMax: 7.0 }
  },

  // PYRO_T: provisional band derived from sensor profile
  PYRO_T: {
    IDLE:         { warningMin: 31.6, warningMax: 48.4, criticalMin: 23.2, criticalMax: 56.8 },
    RAMP_UP:      { warningMin: 31.6, warningMax: 328.4, criticalMin: 23.2, criticalMax: 336.8 },
    STEADY_STATE: { warningMin: 0, warningMax: 33.0, criticalMin: 0, criticalMax: 41.0 },
    RAMP_DOWN:    { warningMin: 31.6, warningMax: 328.4, criticalMin: 23.2, criticalMax: 336.8 }
  },
  // PYRO_GB: provisional band derived from sensor profile
  PYRO_GB: {
    IDLE:         { warningMin: 33.44, warningMax: 42.56, criticalMin: 28.88, criticalMax: 47.12 },
    RAMP_UP:      { warningMin: 33.44, warningMax: 194.56, criticalMin: 28.88, criticalMax: 199.12 },
    STEADY_STATE: { warningMin: 0, warningMax: 40.0, criticalMin: 0, criticalMax: 50.0 },
    RAMP_DOWN:    { warningMin: 33.44, warningMax: 194.56, criticalMin: 28.88, criticalMax: 199.12 }
  },
  // FT_110A: provisional band derived from sensor profile
  FT_110A: {
    IDLE:         { warningMin: 0, warningMax: 9.28, criticalMin: 0, criticalMax: 14.56 },
    RAMP_UP:      { warningMin: 0, warningMax: 31.28, criticalMin: 0, criticalMax: 36.56 },
    STEADY_STATE: { warningMin: 0, warningMax: 5.0, criticalMin: 0, criticalMax: 6.0 },
    RAMP_DOWN:    { warningMin: 0, warningMax: 31.28, criticalMin: 0, criticalMax: 36.56 }
  },
  // PT_150A: provisional band derived from sensor profile
  PT_150A: {
    IDLE:         { warningMin: 111.9, warningMax: 128.1, criticalMin: 103.8, criticalMax: 136.2 },
    RAMP_UP:      { warningMin: 111.9, warningMax: 173.1, criticalMin: 103.8, criticalMax: 181.2 },
    STEADY_STATE: { warningMin: 0, warningMax: 0.2, criticalMin: 0, criticalMax: 0.25 },
    RAMP_DOWN:    { warningMin: 111.9, warningMax: 173.1, criticalMin: 103.8, criticalMax: 181.2 }
  },
  // XT_604: provisional band derived from sensor profile
  XT_604: {
    IDLE:         { warningMin: 0, warningMax: 1.6, criticalMin: 0, criticalMax: 2.8 },
    RAMP_UP:      { warningMin: 0, warningMax: 3.6, criticalMin: 0, criticalMax: 4.8 },
    STEADY_STATE: { warningMin: 0, warningMax: 4.0, criticalMin: 0, criticalMax: 5.5 },
    RAMP_DOWN:    { warningMin: 0, warningMax: 3.6, criticalMin: 0, criticalMax: 4.8 }
  },
  // XT_605: provisional band derived from sensor profile
  XT_605: {
    IDLE:         { warningMin: 0, warningMax: 1.54, criticalMin: 0, criticalMax: 2.68 },
    RAMP_UP:      { warningMin: 0, warningMax: 3.44, criticalMin: 0, criticalMax: 4.58 },
    STEADY_STATE: { warningMin: 0, warningMax: 3.44, criticalMin: 0, criticalMax: 4.58 },
    RAMP_DOWN:    { warningMin: 0, warningMax: 3.44, criticalMin: 0, criticalMax: 4.58 }
  },
  // ZT_600: provisional band derived from sensor profile
  ZT_600: {
    IDLE:         { warningMin: 0, warningMax: 2.28, criticalMin: 0, criticalMax: 3.96 },
    RAMP_UP:      { warningMin: 0, warningMax: 5.08, criticalMin: 0, criticalMax: 6.76 },
    STEADY_STATE: { warningMin: -4, warningMax: 5.08, criticalMin: -10, criticalMax: 6.76 },
    RAMP_DOWN:    { warningMin: 0, warningMax: 5.08, criticalMin: 0, criticalMax: 6.76 }
  }
};

// Keys marked provisional pending engineering sign-off
var PROVISIONAL_THRESHOLD_KEYS = {
  PYRO_T: true, PYRO_GB: true, FT_110A: true, PT_150A: true,
  XT_604: true, XT_605: true, ZT_600: true
};

// Map KPI data keys to schematic SVG hotspot group IDs
var HOTSPOT_BY_KEY = {
  TURBINE_SPEED_RPM: 'hotspot-rotor',
  GB_TRQ: 'hotspot-gearbox',
  PYRO_T: 'hotspot-gearbox',
  PYRO_GB: 'hotspot-gearbox',
  PT_109A: 'hotspot-inlet-steam',
  FT_110A: 'hotspot-inlet-steam',
  PT_150A: 'hotspot-exhaust',
  XT_600: 'hotspot-vibration',
  XT_601: 'hotspot-vibration',
  XT_604: 'hotspot-vibration',
  XT_605: 'hotspot-vibration',
  ZT_600: 'hotspot-vibration'
};

// Hotspot to subsystem mesh mappings aligning 2D coloring with 3D model health states (worst state wins).
var HOTSPOT_MESH_IDS = {
  'hotspot-inlet-steam': ['SteamAdmission.001', 'SteamAdmission.002'],
  'hotspot-tv1':         ['SteamAdmission.003'],
  'hotspot-tv2':         ['SteamAdmission.004'],
  'hotspot-rotor':       ['Turbine.001'],
  'hotspot-vibration':   ['Turbine.001', 'Gearbox.001'],
  'hotspot-gearbox':     ['Gearbox.001'],
  'hotspot-dyno':        ['Dyno.001'],
  'hotspot-wheelcase':   ['Turbine.002'],
  'hotspot-intergbc':    ['Turbine.003'],
  'hotspot-exhaust':     ['Exhaust.001'],
  'hotspot-leakage1':    ['Leakage.001'],
  'hotspot-leakage2':    ['Leakage.002'],
  'hotspot-leakage3':    ['Leakage.003', 'Leakage.004']
};

// healthStatus string (as computed by subsystem_registry.py) -> this widget's own state vocabulary.
var HEALTH_STATUS_TO_STATE = { NORMAL: 'healthy', WARNING: 'warning', ALARM: 'alarm' };

// Build a meshId-to-state map from SUBSYS_* keys published on the turbine telemetry stream.
function readSubsystemHealthByMeshId(latest) {
  var out = {};
  for (var key in latest) {
    if (!Object.prototype.hasOwnProperty.call(latest, key) || key.indexOf('SUBSYS_') !== 0) {
      continue;
    }
    // Mesh IDs are always "<Group><NNN>" with no underscores in <Group>
    // (Gearbox.001, SteamAdmission.002, ...), so replacing the last
    // underscore with a dot is unambiguous.
    var meshId = key.slice('SUBSYS_'.length).replace(/_(\d\d\d)$/, '.$1');
    var sample = latest[key];
    var status = sample ? sample.value : null;
    if (status) {
      out[meshId] = HEALTH_STATUS_TO_STATE[status] || 'healthy';
    }
  }
  return out;
}

// Worst-of state across the meshIds mapped to one hotspot, or null if none
// of them have reported yet (falls back to the raw-band classification).
function subsystemStateForHotspot(healthByMeshId, hotspotId) {
  var meshIds = HOTSPOT_MESH_IDS[hotspotId];
  if (!meshIds || !healthByMeshId) {
    return null;
  }
  var worst = null;
  for (var i = 0; i < meshIds.length; i++) {
    var s = healthByMeshId[meshIds[i]];
    if (s && (!worst || severityRank(s) > severityRank(worst))) {
      worst = s;
    }
  }
  return worst;
}

// Extract latest sample for each data key from context
function readLatestValues(ctx) {
  var out = {};
  var rows = ctx.data || [];
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    if (!row || !row.dataKey || !row.data || !row.data.length) {
      continue;
    }
    var last = row.data[row.data.length - 1];
    // Handle both array format [ts, value] and object format {ts, value}
    var ts = Array.isArray(last) ? last[0] : last.ts;
    var value = Array.isArray(last) ? last[1] : last.value;
    out[row.dataKey.name] = { ts: ts, value: value };
  }
  return out;
}

// Merge dashboard threshold overrides onto defaults
function mergeThresholds(defaults, overrides) {
  var merged = {};
  var key;
  for (key in defaults) {
    if (Object.prototype.hasOwnProperty.call(defaults, key)) {
      merged[key] = defaults[key];
    }
  }
  if (overrides) {
    for (key in overrides) {
      if (Object.prototype.hasOwnProperty.call(overrides, key)) {
        merged[key] = overrides[key];
      }
    }
  }
  return merged;
}

// Resolve threshold band for a key given current operating state
function resolveBand(entry, state) {
  if (!entry) {
    return null;
  }
  if (entry.warningMin !== undefined || entry.warningMax !== undefined ||
      entry.criticalMin !== undefined || entry.criticalMax !== undefined) {
    return entry;  // flat/legacy
  }
  return entry[state] || entry[DEFAULT_STATE] || null;
}

// Memoized threshold band resolution
function bandFor(ctx, key) {
  if (!ctx || !ctx.bandCache) {
    return resolveBand((ctx && ctx.thresholds ? ctx.thresholds : {})[key], DEFAULT_STATE);
  }
  var state = ctx.operatingState || DEFAULT_STATE;
  var cacheKey = key + '|' + state;
  if (!Object.prototype.hasOwnProperty.call(ctx.bandCache, cacheKey)) {
    ctx.bandCache[cacheKey] = resolveBand(ctx.thresholds[key], state);
  }
  return ctx.bandCache[cacheKey];
}

function classifyBand(t, value) {
  if (!t || value === null || value === undefined || isNaN(value)) {
    return 'none';
  }
  if ((t.criticalMin !== undefined && value < t.criticalMin) ||
      (t.criticalMax !== undefined && value > t.criticalMax)) {
    return 'alarm';
  }
  if ((t.warningMin !== undefined && value < t.warningMin) ||
      (t.warningMax !== undefined && value > t.warningMax)) {
    return 'warning';
  }
  return 'healthy';
}

function renderStaleness(ctx, latest, nowMs) {
  var rpmSample = latest.TURBINE_SPEED_RPM;
  var newestTs = rpmSample ? rpmSample.ts : null;

  // Fall back to newest timestamp across all keys if RPM is missing
  if (newestTs === null) {
    for (var k in latest) {
      if (latest.hasOwnProperty(k) && (newestTs === null || latest[k].ts > newestTs)) {
        newestTs = latest[k].ts;
      }
    }
  }

  var staleMs = ctx.staleThresholdSeconds * 1000;
  ctx.isStale = newestTs === null || (nowMs - newestTs) > staleMs;

  if (ctx.container) {
    ctx.container.classList.toggle('state-down', ctx.isStale);
  }
  if (ctx.downBannerEl) {
    ctx.downBannerEl.hidden = !ctx.isStale;
    ctx.downBannerEl.style.display = ctx.isStale ? 'flex' : 'none';
  }
}

function renderRotor(ctx, latest) {
  if (!ctx.rotorBladesEl && !ctx.rotorHotspotEl) {
    return;
  }
  if (ctx.isStale) {
    // Freeze rotation while stale rather than spinning on cached data.
    return;
  }
  var rpmSample = latest.TURBINE_SPEED_RPM;
  var rpm = rpmSample ? Number(rpmSample.value) : 0;
  if (isNaN(rpm) || rpm < 0) {
    rpm = 0;
  }

  // Accumulate rotor rotation angle per tick based on current RPM.
  var deltaDeg = (rpm / ctx.maxRpm) * 360;
  ctx.cumulativeRotorDeg = (ctx.cumulativeRotorDeg + deltaDeg) % 360;

  // Rotate SVG rotor blades around hub center (605, 175).
  if (ctx.rotorBladesEl) {
    ctx.rotorBladesEl.setAttribute('transform', 'rotate(' + ctx.cumulativeRotorDeg + ' 605 175)');
  }

  var hotspotState = classifyBand(bandFor(ctx, 'TURBINE_SPEED_RPM'), rpm);
  if (ctx.rotorHotspotEl) {
    // See the matching override in renderKpiGrid(): prefer the 3D twin's
    // subsystem state so the rotor hotspot never disagrees with Turbine.001.
    var rotorSubsystemState = ctx.isStale
      ? null
      : subsystemStateForHotspot(ctx.subsystemHealthByMeshId, 'hotspot-rotor');
    applyHotspotState(ctx.rotorHotspotEl, rotorSubsystemState || hotspotState);
  }
}

function applyHotspotState(el, state) {
  el.classList.remove('tm-state-warning', 'tm-state-alarm', 'tm-state-down');
  if (state === 'warning' || state === 'alarm') {
    el.classList.add('tm-state-' + state);
  }
}

// Render KPI grid, updating DOM only when formatted values or states change.
function renderKpiGrid(ctx, latest, nowMs) {
  if (!ctx.kpiGridEl) {
    return;
  }
  var hotspotStates = {};

  ctx.kpiOrder.forEach(function (key) {
    var meta = KPI_META[key] || { label: key, unit: '', icon: '' };
    var sample = latest[key];
    var value = sample ? sample.value : null;
    var state = ctx.isStale ? 'down' : classifyBand(bandFor(ctx, key), value);

    var tile = ctx.kpiTileEls[key];
    if (!tile) {
      tile = document.createElement('div');
      tile.className = 'tm-kpi-tile';
      tile.innerHTML =
        '<div class="tm-kpi-label"><span class="tm-kpi-icon"></span><span class="tm-kpi-label-text"></span></div>' +
        '<div><span class="tm-kpi-value"></span><span class="tm-kpi-unit"></span></div>';
      tile.querySelector('.tm-kpi-icon').textContent = meta.icon;
      tile.querySelector('.tm-kpi-label-text').textContent = meta.label;
      tile.querySelector('.tm-kpi-unit').textContent = meta.unit;
      if (tile.setAttribute) {
        tile.setAttribute('data-key', key);
        tile.setAttribute('tabindex', '0');
        tile.setAttribute('aria-describedby', 'tm-tooltip');
      }
      ctx.kpiGridEl.appendChild(tile);
      ctx.kpiTileEls[key] = tile;
      bindTileInteractions(ctx, tile, key);
    }

    var displayValue = value === null || value === undefined ? '—' : formatValue(value);
    var previous = ctx.kpiRendered[key];

    // Dirty-check formatted display value and state
    if (!previous || previous.display !== displayValue || previous.state !== state) {
      tile.className =
        'tm-kpi-tile' + (state !== 'healthy' && state !== 'none' ? ' tm-state-' + state : '');
      tile.querySelector('.tm-kpi-value').textContent = displayValue;

      // Update schematic SVG value element if present
      if (meta.valId && ctx.container) {
        var valEl = ctx.container.querySelector('#' + meta.valId);
        if (valEl) {
          valEl.textContent = value === null || value === undefined ? '--' : formatValue(value);
        }
      }

      ctx.kpiRendered[key] = { display: displayValue, state: state };
      ctx.perf.tileWrites += 1;
    } else {
      ctx.perf.tileSkips += 1;
    }

    var hotspotId = HOTSPOT_BY_KEY[key];
    if (hotspotId) {
      var current = hotspotStates[hotspotId];
      if (!current || severityRank(state) > severityRank(current)) {
        hotspotStates[hotspotId] = state;
      }
    }
  });

  for (var hotspotId2 in hotspotStates) {
    if (hotspotStates.hasOwnProperty(hotspotId2)) {
      var el = ctx.container ? ctx.container.querySelector('#' + hotspotId2) : null;
      if (el && hotspotId2 !== 'hotspot-rotor') {
        // Prefer the 3D twin's subsystem healthStatus when it's available for
        // this hotspot, so the 2D and 3D views never show different colors
        // for the same component -- see HOTSPOT_MESH_IDS above.
        var subsystemState = ctx.isStale
          ? null
          : subsystemStateForHotspot(ctx.subsystemHealthByMeshId, hotspotId2);
        applyHotspotState(el, subsystemState || hotspotStates[hotspotId2]);
      }
    }
  }
}

// Shared hover and focus tooltip popover
var STATUS_LABELS = {
  healthy: { text: 'OK', cls: 'tm-tt-ok' },
  warning: { text: 'WARNING', cls: 'tm-tt-warning' },
  alarm:   { text: 'CRITICAL', cls: 'tm-tt-critical' },
  down:    { text: 'STALE', cls: 'tm-tt-stale' },
  none:    { text: 'NO BAND', cls: 'tm-tt-none' }
};

function bindTileInteractions(ctx, tile, key) {
  if (!tile.addEventListener) {
    return;
  }
  var enter = function () { showTooltip(ctx, key, tile); };
  var leave = function () { hideTooltip(ctx); };
  // Support keyboard accessibility alongside mouse events
  tile.addEventListener('mouseenter', enter);
  tile.addEventListener('mouseleave', leave);
  tile.addEventListener('focus', enter);
  tile.addEventListener('blur', leave);
  tile._tmHandlers = { enter: enter, leave: leave };
}

function showTooltip(ctx, key, tile) {
  if (!ctx.tooltipEl) {
    return;
  }
  ctx.activeTooltipKey = key;
  updateTooltipContent(ctx, key, Date.now());
  ctx.tooltipEl.hidden = false;
  if (ctx.tooltipEl.setAttribute) {
    ctx.tooltipEl.setAttribute('aria-hidden', 'false');
  }
  positionTooltip(ctx, tile);
}

function hideTooltip(ctx) {
  if (!ctx.tooltipEl) {
    return;
  }
  ctx.activeTooltipKey = null;
  ctx.tooltipEl.hidden = true;
  if (ctx.tooltipEl.setAttribute) {
    ctx.tooltipEl.setAttribute('aria-hidden', 'true');
  }
}

// Position tooltip relative to widget container boundaries
function positionTooltip(ctx, tile) {
  if (!ctx.tooltipEl || !tile || !tile.getBoundingClientRect || !ctx.container) {
    return;
  }
  var tileRect = tile.getBoundingClientRect();
  var hostRect = ctx.container.getBoundingClientRect();
  var ttRect = ctx.tooltipEl.getBoundingClientRect();

  var width = ttRect.width || 240;
  var height = ttRect.height || 120;

  // Flip below tile if space above is insufficient
  var top = tileRect.top - hostRect.top - height - 8;
  if (top < 0) {
    top = tileRect.bottom - hostRect.top + 8;
  }

  // Centre and clamp horizontally within widget
  var left = tileRect.left - hostRect.left + (tileRect.width / 2) - (width / 2);
  var maxLeft = hostRect.width - width - 4;
  if (left > maxLeft) { left = maxLeft; }
  if (left < 4) { left = 4; }

  ctx.tooltipEl.style.top = top + 'px';
  ctx.tooltipEl.style.left = left + 'px';
}

function updateTooltipContent(ctx, key, nowMs) {
  var els = ctx.tooltipEls || {};
  if (!els.label) {
    return;
  }
  var meta = KPI_META[key] || { label: key, unit: '' };
  var sample = (ctx.latestByKey || {})[key];
  var value = sample ? sample.value : null;
  var band = bandFor(ctx, key);
  var state = ctx.isStale ? 'down' : classifyBand(band, value);
  var status = STATUS_LABELS[state] || STATUS_LABELS.none;

  els.label.textContent = meta.label + ' (' + key + ')';
  els.status.textContent = status.text;
  els.status.className = 'tm-tt-status ' + status.cls;

  els.value.textContent = value === null || value === undefined ? '—' : formatValue(value);
  els.unit.textContent = meta.unit || '';
  els.pct.textContent = describePositionInBand(value, band);

  renderTooltipBands(els.bands, band, meta.unit);

  els.age.textContent = sample
    ? 'Last updated ' + formatAge(nowMs - sample.ts)
    : 'No sample received';

  // Note provisional status when applicable
  els.note.textContent = PROVISIONAL_THRESHOLD_KEYS[key]
    ? 'Provisional band derived from the sensor profile — pending engineering sign-off.'
    : '';
}

// Calculate reading position percentage within normal warning band
function describePositionInBand(value, band) {
  if (value === null || value === undefined || isNaN(value) || !band) {
    return '';
  }
  var lo = band.warningMin;
  var hi = band.warningMax;
  if (lo === undefined || hi === undefined || hi <= lo) {
    return '';
  }
  var pct = ((Number(value) - lo) / (hi - lo)) * 100;
  return '(' + Math.round(pct) + '% of normal range)';
}

function renderTooltipBands(el, band, unit) {
  if (!el) {
    return;
  }
  if (!band) {
    el.textContent = 'No threshold band configured for this sensor.';
    return;
  }
  var u = unit ? ' ' + unit : '';
  var rows = [
    { cls: 'tm-tt-sw-ok', text: 'Normal ' + rangeText(band.warningMin, band.warningMax) + u },
    { cls: 'tm-tt-sw-warn', text: 'Warning outside ' + rangeText(band.warningMin, band.warningMax) + u },
    { cls: 'tm-tt-sw-crit', text: 'Critical outside ' + rangeText(band.criticalMin, band.criticalMax) + u }
  ];
  var html = '';
  for (var i = 0; i < rows.length; i++) {
    html +=
      '<div class="tm-tt-band-row">' +
      '<span class="tm-tt-swatch ' + rows[i].cls + '"></span>' +
      '<span>' + rows[i].text + '</span>' +
      '</div>';
  }
  el.innerHTML = html;
}

function rangeText(min, max) {
  var lo = min === undefined || min === null ? '−∞' : formatValue(min);
  var hi = max === undefined || max === null ? '∞' : formatValue(max);
  return lo + '–' + hi;
}

function formatAge(ms) {
  if (ms === null || ms === undefined || isNaN(ms)) {
    return 'unknown';
  }
  var seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) {
    return seconds + 's ago';
  }
  var minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return minutes + 'm ' + (seconds % 60) + 's ago';
  }
  var hours = Math.floor(minutes / 60);
  return hours + 'h ' + (minutes % 60) + 'm ago';
}

function severityRank(state) {
  return { none: 0, healthy: 0, warning: 1, alarm: 2, down: 3 }[state] || 0;
}

function formatValue(value) {
  var n = Number(value);
  if (isNaN(n)) {
    return String(value);
  }
  return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
}

function renderOverallState(ctx, latest) {
  if (ctx.isStale) {
    ctx.overallState = 'down';
    ctx.overallStateLabel = 'Down';
    return;
  }
  var worst = 'healthy';
  ctx.kpiOrder.forEach(function (key) {
    var sample = latest[key];
    // Reuses the same memoised band renderKpiGrid() just resolved, rather
    // than walking the threshold table a second time for all 12 keys.
    var state = classifyBand(bandFor(ctx, key), sample ? sample.value : null);
    if (severityRank(state) > severityRank(worst)) {
      worst = state;
    }
  });
  // Also fold in the subsystem (3D-twin) states so the overall chip can never
  // read HEALTHY while a hotspot is showing WARNING/ALARM from subsystem data.
  var healthMap = ctx.subsystemHealthByMeshId;
  if (healthMap) {
    var meshIds = Object.keys(healthMap);
    for (var m = 0; m < meshIds.length; m++) {
      var s2 = healthMap[meshIds[m]];
      if (severityRank(s2) > severityRank(worst)) {
        worst = s2;
      }
    }
  }
  ctx.overallState = worst;
  ctx.overallStateLabel = worst.charAt(0).toUpperCase() + worst.slice(1);

  if (ctx.stateChipEl) {
    ctx.stateChipEl.className = 'tm-state-chip state-' + ctx.overallState;
  }
  if (ctx.stateTextEl) {
    ctx.stateTextEl.textContent = ctx.overallStateLabel;
  }
}
// CONTROLLER_SCRIPT_END

