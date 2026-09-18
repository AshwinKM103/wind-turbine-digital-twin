**Do not abandon custom 3D entirely—but do abandon building a custom 3D renderer as your first step.** Use the linked ThingsBoard IoT Hub **3D Model Viewer** for the first serious turbine digital-twin implementation, then build a custom widget only if its verified limitations block the specific advanced interactions you need.

The widget already gives you the most expensive baseline capabilities: GLB loading, mesh-to-entity mapping, telemetry-driven mesh colors, in-scene labels/tooltips, camera positioning, and mesh-click actions into ThingsBoard drill-down states.\[[thingsboard](https://thingsboard.io/iot-hub/widgets/3d-model-viewer/)\]

## The decision

| Question | Recommendation |
| --- | --- |
| Should you use the linked widget? | **Yes—make it your primary 3D proof-of-concept.** |
| Should you discard the custom-widget plan forever? | **No.** Keep it as an advanced/fallback path. |
| Should you begin with Three.js/Babylon.js from scratch? | **No.** It would duplicate confirmed functionality and delay the demo. |
| Should the 3D viewer replace SVG SCADA? | **No.** Keep a high-quality SVG process/turbovisory view for engineering clarity. |
| Is this sufficient for a professor-facing impressive dashboard? | **Very likely**, if the GLB, state rules, labels, drill-down and companion SVG are executed well. |
| Can it support your approximate 60-channel dataset? | **Yes at the component level**, with a carefully designed mesh/entity model and progressive disclosure. |

## Why the IoT Hub widget is the right first move

The widget is not merely a static 3D file viewer. Its published capabilities directly match the core digital-twin interaction model:

- It loads a **GLB** model directly inside a ThingsBoard widget.
- It binds each ThingsBoard datasource entity to a correspondingly named GLB mesh using the `meshId` attribute.
- A JavaScript **color function** receives current telemetry and attributes, allowing condition-based component coloring.
- Its tooltip and label functions are evaluated on each data update.
- Clicking a mesh launches a ThingsBoard action, including navigation to a component-specific dashboard state.
- It supports two named mesh groups—such as a main equipment group and sensor/cutaway group—through its **Mesh type** prefix setting.
- It supports a user-defined camera position, with a shortcut that logs the current camera coordinates for reuse.\[[thingsboard](https://thingsboard.io/iot-hub/widgets/3d-model-viewer/)\]

That means it already solves roughly this portion of a custom Babylon.js/Three.js widget:

```
GLB loader                          ✓
WebGL renderer                      ✓
Camera controls                     ✓
Mesh discovery and mapping          ✓
Live ThingsBoard data binding       ✓
Condition color updates             ✓
Labels/tooltips                     ✓
Mesh click/picking                  ✓
Dashboard drill-down action         ✓
Model hosting through TB Resources  ✓
```

Those are substantial engineering tasks. Reimplementing them from scratch only makes sense if you need behavior the widget demonstrably cannot provide.

## What you should build with it

Use the linked 3D Model Viewer for the **component-level** turbine train, not as an attempt to show 60 permanent numeric labels.

### GLB mesh plan

Create a turbine GLB with individual meshes named in the convention expected by the widget:

```
Turbine.001             → Turbine casing
Turbine.002             → Wheel case
Turbine.003             → Intermediate GBC

SteamAdmission.001      → Inlet steam pipe
SteamAdmission.002      → ESV
SteamAdmission.003      → TV1
SteamAdmission.004      → TV2

Gearbox.001             → Gearbox
Dyno.001                → Dyno
Exhaust.001             → Exhaust path

Leakage.001             → Leakage 1
Leakage.002             → Leakage 2
Leakage.003             → Leakage 3, upstream/left
Leakage.004             → Leakage 3, downstream/right
```

The widget documentation states that a mesh name must match the mapped entity’s `meshId`, and recommends a prefix-plus-index naming pattern such as `Silo.003`. It also supports selection by mesh prefix, so groups such as `Turbine`, `Gearbox`, `Sensor` and `Leakage` are practical.\[[thingsboard](https://thingsboard.io/iot-hub/widgets/3d-model-viewer/)\]

Do not combine the complete rig into one GLB mesh. You would lose independent color changes, click targets and component-specific labels.

### ThingsBoard entities

Create one parent test-rig asset and major subsystem/component assets:

```
Steam Turbine Test Rig
│
├── Inlet and Steam Admission
├── ESV
├── TV1
├── TV2
├── Turbine
├── Wheel Case
├── Intermediate GBC
├── Gearbox
├── Dyno
├── Exhaust
├── Leakage 1
├── Leakage 2
├── Leakage 3 Upstream
└── Leakage 3 Downstream
```

Set each entity’s shared attribute:

```
{
  "meshId": "Turbine.001"
}
```

Then publish or derive component-level current telemetry such as:

```
healthState
healthScore
activeAlarmCount
maxSeverity
dominantSensor
dominantValue
dominantUnit
lastUpdateTs
```

This is preferable to putting every raw sensor into a giant color function.

## How your actual channels fit

The source schematic and CSV support a component-level mapping that works very well with this 3D viewer.

| 3D component | Primary live telemetry | Permanent label recommendation | Click target |
| --- | --- | --- | --- |
| Inlet / `SteamAdmission.001` | `PT_109A`, `TT_109A`, `FT_110A` | Inlet P, T, mass flow | Steam admission state |
| ESV / `SteamAdmission.002` | `PT_111B`, `ACT_POS_FB`, `HP_DEMAND` | ESV state / actuator feedback | ESV details |
| TV1 / `SteamAdmission.003` | `PT_111`, `TT_111` | TV1 pressure/temperature | Steam admission state |
| TV2 / `SteamAdmission.004` | `PT_112`, `TT_112` | TV2 pressure/temperature | Steam admission state |
| Turbine / `Turbine.001` | `TURBINE_SPEED`, `PYRO_T`, ZT600/601, XT600–603 | Speed + overall turbine condition | Turbine condition |
| Wheel case / `Turbine.002` | `PT_120`, `TT_120_R`, `TT_120` | Wheel-case P/T | Turbine detail |
| Intermediate GBC / `Turbine.003` | `PT_111C`, `TT_111C`, `TT_111C_R` | Inter-GBC condition | Turbine detail |
| Gearbox / `Gearbox.001` | `GB_TRQ`, `PYRO_GB`, XT604–607 | Torque + gearbox health | Gearbox condition |
| Dyno / `Dyno.001` | `Dyno Water O/L` | Dyno utility/condition status | Dyno detail |
| Exhaust / `Exhaust.001` | `PT_150A/B`, `TT_150A/B` | Exhaust pressure/temperature summary | Exhaust detail |
| Leakage 1 | `PT_162`, `TT_162`, `FT_162` | Leakage P/T/F | Leakage analysis |
| Leakage 2 | `PT_161`, `TT_161` | Leakage P/T | Leakage analysis |
| Leakage 3 upstream | `PT_160`, `TT_160` | Leakage P/T | Leakage analysis |
| Leakage 3 downstream | `PT_163`, `TT_163` | Leakage P/T | Leakage analysis |

The mapping above follows the supplied turbine process schematic. It deliberately leaves PT110A/B, PT153, PT201, PT253, several RTDs, and other channels out of the 3D machine until their physical placement is confirmed.\[[ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/30049091/6c928126-8a18-4036-bb69-dae7b29a9d57/UI_r6_DigitalTwin.pdf)\]

## What not to rely on it for

Use the 3D viewer unless testing proves it cannot do enough. Its published feature set does **not** explicitly guarantee the following:

| Advanced requirement | Should you expect it out of the box? | Practical decision |
| --- | --- | --- |
| Interactive GLB model | Yes | Use it |
| Component colors from telemetry | Yes | Use it |
| Component labels/tooltips | Yes | Use it |
| Clicking component for drill-down | Yes | Use it |
| Camera orbit and zoom | Likely; normal for the viewer | Test it |
| Saved camera start point | Yes | Use it |
| Sensor-marker mesh group | Indicated through mesh prefixes | Test it |
| Per-sensor 60-marker management | Uncertain | Design progressively |
| Shaft rotation from `TURBINE_SPEED` | Not documented | Do not assume |
| TV1/TV2/ESV movement from `ACT_POS_FB` | Not documented | Do not assume |
| Live particle steam flow | Not documented | Custom enhancement |
| Leakage-flow animation from `FT_162` | Not documented | Custom enhancement |
| Transparent casing toggle | Not documented | Model/export or custom path |
| Cutaway/section clipping | Not documented | Advanced custom path |
| Exploded mechanical model | Not documented | Use pre-authored GLB states or custom path |
| Historical 3D replay timeline | Not documented | Custom development |
| Real vibration waveform/orbit | Not possible from current scalar dataset | Requires waveform/phase data |
| Chart selection synchronized with 3D selection | Not documented | Implement through states/actions or custom bridge |

The correct strategy is not “the widget does everything” but rather:

> **Use it for the 80 percent that is already solved, then custom-build only the 20 percent that produces unique educational and visual value.**

## Recommended dashboard architecture

### Level 1 — Command overview

Use the 3D Model Viewer as the dominant visual element.

Persistent values:

- Turbine speed from `TURBINE_SPEED`.
- Gearbox torque from `GB_TRQ`.
- HP demand from `HP_DEMAND`.
- Actuator feedback from `ACT_POS_FB`.
- Inlet pressure, temperature and mass flow from `PT_109A`, `TT_109A`, `FT_110A`.
- Highest vibration severity across ZT600/601 and XT600–607.
- Turbine and gearbox pyro temperatures from `PYRO_T` and `PYRO_GB`.
- Overall health, data freshness and active alarm count.

Keep labels concise. A 3D view full of numeric tags will look less professional and become unreadable.

### Level 2 — Process SCADA

Use a custom/native ThingsBoard SVG view built directly from your PDF arrangement:

```
Inlet → ESV → TV1 / TV2 → Turbine → Gearbox → Dyno
                 ↓
       Wheel case / intermediate GBC / exhaust / leakage paths
```

This is where every pressure, temperature and flow channel can have an exact readable tag. ThingsBoard’s official SCADA system supports interactive SVG elements, tags, behavior and rendering functions.\[[github](https://github.com/yyunju80/thingsboard---IoT)\]

### Level 3 — Turbine and gearbox condition

Provide:

- Turbine condition summary.
- Gearbox condition summary.
- X/Y paired vibration cards.
- ZT600 and ZT601 axial channels.
- XT600–XT603 turbine radial channels.
- XT604–XT607 gearbox radial channels.
- Torque, speed, pyro temperatures.
- Per-channel latest value, limits and historical charts.

The physical arrangement in the supplied turbovisory drawing should remain visible here, because it is the most credible visual representation of the probe arrangement.\[[ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/30049091/6c928126-8a18-4036-bb69-dae7b29a9d57/UI_r6_DigitalTwin.pdf)\]

### Level 4 — Sensor detail

On sensor or component click, open a sensor state showing:

- Tag name.
- Engineering unit.
- Latest value and timestamp.
- Data quality.
- Warning, alarm and critical threshold.
- Trend over the selected dashboard time window.
- Minimum, maximum and mean.
- Related channels.
- Active and historical alarms.

### Level 5 — Test replay and diagnostics

Only after you correct the source timestamps to sufficient resolution:

- Select a historical interval.
- Move through a time slider.
- Synchronize 3D component colors and labels with trend charts.
- Clearly display “Historical replay,” not “Live.”
- Add transitions between startup, loading, steady-state and coast-down if those states are represented in the data.

## The final answer

**Use the linked 3D Model Viewer now. Do not begin by building a custom Babylon.js or Three.js turbine renderer.**

Your recommended path is:

1. Install the widget.
2. Export its JSON and inspect/configure it in your own ThingsBoard instance.
3. Build a low-poly, correctly segmented turbine-train GLB first.
4. Validate mesh mapping, labels, tooltips, telemetry coloring and dashboard click navigation using your actual sensor keys.
5. Create the high-quality SVG SCADA and turbovisory views in parallel.
6. Only write a custom 3D widget if testing reveals a need for live shaft rotation, valve mechanics, steam particles, advanced clipping/cutaway, exploded view, dense sensor-marker behavior or historical 3D replay.

For your academic objective, a polished GLB mapped through this widget, paired with a precise SVG process mimic and real ThingsBoard diagnostics, is likely the **best balance of visual impact, technical credibility, engineering accuracy and implementation risk**.\[[thingsboard](https://thingsboard.io/iot-hub/widgets/3d-model-viewer/)\]\[[github](https://github.com/yyunju80/thingsboard---IoT)\]