# Replacing the Turbine Test-Rig GLB: A Reconstruction Blueprint for a Convincing ThingsBoard + Babylon.js Digital Twin
## Executive Summary
The current `turbine_rig_prototype.glb` reads as a "generic 3D illustration" because it is a set of untextured primitive boxes and cylinders (1,698 verts / 1,596 faces) with flat PBR colors, no supporting baseplate, no piping runs, no instrumentation probes, and proportions that only loosely echo the schematic. None of these defects come from Babylon.js or ThingsBoard — they are all authoring problems in the mesh itself. The schematic (`UI_r6_DigitalTwin.pdf`) and the specification together describe a **small single-stage impulse steam turbine, roughly 100–500 kW class, in a horizontal turbine → gearbox → dynamometer test train** with combined trip-throttle admission (ESV/TV1/TV2), a wheel-case, an exhaust down-leg, three leakage/drain collection points, inter-gearbox-casing (inter-GBC) measurement, and a full turbovisory vibration set (2 axial casing + 4 turbine-shaft radial + 4 gearbox radial probes). This is precisely the machine class covered by **API 611** (general-purpose steam turbines, single-stage, ≤3,000 kW, ≤6,000 rpm), with the vibration architecture governed by **API 670 / ISO 20816 / ISO 7919** and the gear unit by **AGMA 6011 / API 613**.

The strongest reconstruction path is a **hybrid composite (Strategy D)**: rebuild the turbine/wheel-case, valves, and probe fittings yourself in Blender against API/manufacturer references, drop in downloadable CAD for the gearbox, dynamometer, valves, and piping, and skin everything with CC0 PBR metal/painted-steel textures — then wire ThingsBoard telemetry to named sensor anchor meshes in Babylon.js. Below are the diagnosis, the turbine-class identification, the standards that genuinely apply, ranked reusable assets with licenses and URLs, and a concrete final architecture with polygon budgets and naming conventions.

***
## 1. Diagnosis of the Current GLB
### 1.1 Problems in the 3D model itself
The six renders and the specification make the model faults unambiguous. The isometric and orthographic views show detached primitive clusters floating in space rather than a mounted machine train.

| Defect | Evidence | Why it looks poor |
|---|---|---|
| **Primitive geometry** | Spec confirms "basic box/cylinder primitives"; renders show plain cylinders/cubes[^1] | No fillets, flanges, ribs, or cast surfaces — the eye reads it as CAD blockout, not a machine |
| **Wrong/weak proportions** | Turbine barrel, gearbox cube, and dyno cylinder are near-equal masses in the renders | Real single-stage sets have a large-diameter wheel-case, a compact offset gearbox, and a distinct dyno — the mass hierarchy is missing[^2] |
| **No baseplate / supports** | Renders show components at different heights, unconnected | Real rigs sit on a common fabricated **baseplate/soleplate** with pedestals; its absence destroys realism[^3] |
| **No piping** | Spec lists "No piping, manifold detail"[^1] | Inlet steam line, exhaust down-leg, and 3 leakage/drain lines in the schematic are entirely unmodeled |
| **No instrumentation probes** | Spec: "no instrumentation probe representations"[^1] | The 20+ transmitters and 10 vibration probes in the PDF have zero physical presence |
| **Flat materials** | All components metallic 0.7 / roughness 0.35, no maps[^1] | Uniform matte gray with no normal/roughness/AO texture = "plastic toy" appearance[^4] |
| **Valve blockout** | Spec: "Valve assemblies lack mechanical detail and valve trim"[^1] | ESV/TV1/TV2 should read as trip-throttle valves with bonnets, actuators, handwheels |
| **Gearbox as a cube** | Spec: "Gearbox lacks individual gear mesh geometry"[^1] | No split-line, no shaft stubs, no inspection covers |
| **Topology / triangulation** | Cylinders show visible facet triangulation in renders | Low segment counts on round parts read as polygonal at close range |
| **Scale approximate** | Spec: "Model scale and proportions are approximate only"[^1] | Not dimensionally anchored to any real frame size |

The **component inventory is actually reasonable** — 15 meshes covering admission (4), casing (3), gearbox, dyno, exhaust, leakage (4) — so the *architecture map is correct*; it is the *fidelity, mounting, connective tissue (piping), and surface treatment* that fail. That is good news: you are refining a correct topology, not starting from a wrong concept.
### 1.2 Problems that would come from Babylon.js / ThingsBoard (implementation side)
There is **no evidence in the provided files of any Babylon.js or ThingsBoard code**, so these are *potential* implementation issues, not diagnosed ones:

- A ~50 KB, 1,596-face model will render trivially; there is no performance problem to solve — the risk is the opposite (too little geometry to look good on zoom).
- If sensor overlays misbehave, the usual causes are missing named anchor nodes, GUI controls not linked with `linkWithMesh`, or back-face culling not enabled on hotspot planes — all authoring/scene-setup choices, not model faults.[^5][^6]
- ThingsBoard custom widgets embed a canvas; the model must expose **stable, uniquely named meshes** for the widget's JS to bind telemetry to. The current GLB's mesh naming is unknown and should be standardized (Section 13).

**Bottom line:** every listed limitation is a modeling/authoring problem. Do not attribute the poor look to the web stack.

***
## 2. Identification of the Turbine / Test-Rig Class
Cross-referencing the schematic, the spec's own estimate, Triveni's product line, and API scope definitions converges on a clear class.

**This is a small single-stage impulse steam turbine in a mechanical-drive test train, API 611 general-purpose class.** API 611 explicitly covers single-stage turbines up to ~3,000 kW / 6,000 rpm at ≤48 bar / 400 °C, and the spec's own estimate of "single-stage, triple-throttle admission, 100–500 kW" sits squarely inside it. Triveni's own API 611 single-stage line matches the observable features one-for-one: **combined Trip & Throttle Valve, carbon-ring/labyrinth end seals, hydrodynamic journal bearings, casing accelerometers with optional shaft vibration probes**.[^1][^7][^8]

| Rig feature (from PDF) | Interpretation | Reference basis |
|---|---|---|
| Inlet steam + ESV + TV1 + TV2 | Emergency Stop Valve + two throttle/governor valves feeding a nozzle group (multi-valve single-stage admission) | Elliott Multi-YR and Triveni multi-valve single-stage admission[^2][^7] |
| Trapezoidal "Turbine" body | Single-stage impulse wheel-case (large inlet end, tapering casing) | saVRee/Elliott single-stage geometry[^2] |
| Wheel Case (PT120/TT120) | Steam space around the impulse wheel; pressure/temp tapping | Standard single-stage design[^9] |
| GB block, offset from turbine centerline | Parallel-shaft **speed-reduction/step gear** between turbine and dyno | Triveni Power Transmission test-rig gearboxes[^10] |
| Dyno with Power/Torque/Speed | **Load absorber (eddy-current or water-brake dynamometer)** | Triveni full-train dynamometer validation[^11][^12] |
| Exhaust down-leg (blue arrow) | Low-pressure exhaust to atmosphere/condenser | Back-pressure single-stage[^13] |
| Leakage 1/2/3 (red dashed) | Gland/carbon-ring leak-off and drain collection | Carbon-ring seal leak-off[^7] |
| Inter-GBC (PT161/163, TT161/163) | Inter-gearbox-casing pressure/temp between gear stages/bearings | AGMA/API gear-unit instrumentation[^14] |
| ZT600/601 axial, XT600–607 X/Y radial | Turbovisory probe set: 2 casing axial + 4 turbine-shaft + 4 gearbox-shaft radial | API 670 X-Y radial arrangement[^15] |

**What is known vs. what must be inferred.** *Known:* topology, instrument tags/locations, unit system, drive-train order, seal/bearing/valve types (from Triveni's own API 611 page). *Must be inferred (not in the PDF):* exact wheel diameter, casing dimensions, gear ratio, dyno type, baseplate size, nozzle count, and bearing span. Do **not** invent these as facts — model them as *engineering-plausible* using the reference frames below. For dimensional plausibility, the closest documented analogues are the **Elliott YR family** (single-stage, 12–28 in / 305–710 mm wheel pitch diameter, 3–10 in inlet, 6–14 in exhaust, 5,000–8,500 rpm, 150–4,027 kW) and **Dresser-Rand RLHA** (API 611, 335–1,865 kW, 3–6 in inlet, 6–10 in exhaust, 6,000–6,300 rpm). These give you real proportions to size the wheel-case, inlet, and exhaust convincingly.[^9][^2]

***
## 3. Relevant Global Engineering Standards
The task is to separate standards that *genuinely inform this rig* from ones that merely sound relevant. The verdict per standard:

| Standard | Applies? | What it informs here | Connection to PDF components |
|---|---|---|---|
| **API 611** — General-Purpose Steam Turbines | **Yes — primary** | Defines this exact machine class (single-stage, ≤3,000 kW, ≤6,000 rpm, ≤48 bar/400 °C); carbon-ring seals + anti-friction/hydrodynamic bearings; combined trip-throttle valve[^8][^16] | Turbine casing, ESV/TV admission, seals, bearing arrangement |
| **API 612** — Special-Purpose Steam Turbines | **Only as contrast** | Governs *critical/large* turbines with expanded monitoring, labyrinth seals, tilt-pad bearings; this small test turbine is 611-class, not 612 — cite it only to explain why 611 fits[^17][^18] | Not the governing spec; useful for the "why 611" narrative |
| **API 670** — Machinery Protection Systems | **Yes — for probes** | X-Y proximity-probe pairs at each radial bearing, radial probes 45° from top-dead-center; axial thrust probes; naming/mounting | Directly maps to XT600/601 (turbine inlet), XT602/603 (turbine outlet), XT604–607 (gearbox), ZT600/601 axial[^15][^19] |
| **ISO 20816** (supersedes **ISO 10816**) — Mechanical Vibration | **Yes — for casing/severity** | Casing/bearing-housing broadband vibration, A–D severity zones (mm/s RMS), measurement on non-rotating parts | ZT600/601 casing axial vibration; drives alarm-color thresholds in the twin[^20][^21] |
| **ISO 7919** — Shaft Vibration | **Yes — for shaft** | Relative shaft vibration via proximity probes (units in the PDF are **mills/mils**, i.e., shaft displacement) | XT600–607 shaft radial vibration in mils[^22] |
| **AGMA 6011** — High-Speed Helical Gear Units | **Yes — for gearbox** | Specification for high-speed enclosed helical gear units (turbo gear class); casing form, offset shafts | GB block, inter-GBC, gearbox radial probes[^23][^24] |
| **API 613** — Special-Purpose Gear Units | **Partially / by analogy** | Single-/double-helical parallel-shaft speed increasers/reducers for turbomachinery trains | Informs gearbox casing split-line, shaft stubs, appearance[^14][^25] |
| **ISA-5.1 / ANSI-ISA-5.1-2024** — Instrumentation Symbols | **Yes — for overlays** | Tag semantics: PT=pressure transmitter, TT=temperature transmitter, FT=flow transmitter; bubble symbology for 2D overlays | Every PT/TT/FT/ZT/XT tag and the ThingsBoard 2D symbol layer[^26][^27] |
| **ASME PTC 6** — Steam Turbine Performance Test Code | **Loosely — context only** | Defines *how performance is measured* (efficiency, heat rate); explains *why* the inlet/exhaust/flow instrumentation exists, but specifies **no geometry** | Justifies PT109/TT109/FT110 inlet and exhaust measurement placement — do not claim it dictates shapes |
| NEMA SM 23 | **Minor** | Nozzle forces/moments basis referenced by API 611 turbines | Only relevant if modeling nozzle/piping loads narrative[^7] |

**Guardrail:** API 611 and API 670 are the two standards that most concretely shape what you model and where probes sit. ISO 20816/7919 govern the *thresholds/coloration* logic, not geometry. ASME PTC 6 is contextual only — do not state it specifies dimensions.

***
## 4. Best Available Real-World
![](images/image_1.jpg)
Steam turbine
Use these to fix casing shape, valve arrangement, gearbox look, shaft alignment, supports, piping, and instrument placement. Ranked by usefulness to *this* rig.

**Tier 1 — closest architectural analogues (single-stage mechanical-drive turbines):**

- **Elliott YR / Multi-YR single-stage turbine catalog** — single-valve and multi-valve single-stage, full frame-size dimension tables (wheel pitch dia, inlet/exhaust sizes, rpm, weights). This is your best dimensional anchor. Format: PDF. Free. [Elliott YR spec][^2][^28]
- **Dresser-Rand RLHA API 611 single-stage** — axial-split casing, overspeed trip, governing systems, model dimension table (335–1,865 kW). PDF, free.[^9]
- **Triveni API 611 single-stage product page + brochures** — the actual OEM: trip-throttle valve, carbon-ring seals, hydrodynamic bearings, casing accelerometers/shaft probes; photographs of mounted machines on white baseplates. Brochure library.[^29][^7]
![](images/image_2.jpg)
Steam turbine low pressure inlet
![](images/image_3.jpg)
Siemens SST-5000 steam turbine
- **Triveni full-train dynamometer validation (PowerMag / LinkedIn)** — photos and description of turbine+gearbox+generator+dynamometer strung on one baseplate; directly matches your train order.[^12][^11]

**Tier 2 — visual/cutaway understanding:**

- **saVRee steam-turbine cutaways and inlet/valve diagrams** — labeled control valve, steam chest, admission nozzles, casing; excellent for valve/casing form.
![](images/image_4.jpg)
Steam turbine for pumps
- **Triveni manufacturing/test-facility pages** — mechanical steam-run test process, load-test facility (≤2 MWe), test-bed layout to reconstruct the *environment*.[^3][^30]

**Reference images to model against:**
**Other comparable OEMs to broaden the visual library:** Elliott (primary analogue), Shin Nippon, Siemens SST small frames, MAN, Mitsubishi — all make single-stage/small multi-stage mechanical-drive units; use their public brochures for casing/valve/gearbox styling. Triveni is the correct primary because the rig is theirs.

***
## 5. Best Downloadable 3D / CAD Assets (complete turbines)
No public model exactly matches a Triveni API 611 single-stage test train — expect to **combine and modify**. Ranked:

| # | Asset | Source / URL | Format | License | Download | Cost | Similarity | Reuse | Babylon fit |
|---|---|---|---|---|---|---|---|---|---|
| A1 | Steam Turbine (animated internal mechanics) by CanopyCreative | sketchfab.com/3d-models/steam-turbine-2471ad99fcf64ec286684784a80f85fe | glTF/GLB | Check per-model (Sketchfab CC or Store) | Yes if CC | Free/Store | Medium (shows steam path) | Flow-path & casing styling reference | Native glTF[^31] |
| A2 | Steam Turbine by landinweaver | sketchfab.com/3d-models/steam-turbine-bcc264eafbe4412d9c061d6d97f30b99 | glTF/GLB | **CC-BY** | Yes | Free | Medium | Barrel/casing base mesh | Native glTF, attribute author[^32] |
| A3 | Steam Turbine Generator Skoda 35 MW + 360 tour | sketchfab.com/3d-models/…7f0b3504d36945c5949a855106ecb1c7 | glTF/GLB | Per-model | Varies | Free | Low (too large, condensing) | Environment/scale mood only | Native glTF[^33] |
| A4 | Sketchfab `steamturbine` / `steam turbine` tag (downloadable filter) | sketchfab.com/tags/steamturbine ; sketchfab.com/search?q=steam+turbine&features=downloadable | glTF/GLB/FBX | Mixed CC0/CC-BY/NC | Filterable | Free | Varies | Casing/rotor blockouts | Native glTF[^34] |
| A5 | GrabCAD `steam turbine` tag | grabcad.com/library/tag/steam-turbine | STEP/IGES/native | GrabCAD terms (personal/eval; verify commercial) | Yes (login) | Free | Medium-high (engineering) | CAD casing/rotor to retopo | Needs STEP→mesh→decimate[^35][^36] |
| A6 | Tripo AI steam-turbine gallery | studio.tripo3d.ai/3d-model-gallery/steam-turbine | STL/FBX/GLB/OBJ/USDZ | Per-item | Yes | Free/premium | Low-medium | Quick blockouts | GLB direct[^37] |
| A7 | TurboSquid free glTF steam/industrial turbine | turbosquid.com/Search/3D-Models/free/steam-turbine-model/gltf | glTF/blend | TurboSquid royalty-free/editorial (read per item) | Yes | Free | Varies | Whole/partial | Native glTF[^38][^39] |

**Guidance:** treat A1/A2 as *styling/base-mesh* donors (attribute CC-BY authors), and A5 (GrabCAD STEP) as the *engineering-accurate* donor you retopologize. Verify each Sketchfab model's license badge before download — the platform mixes CC0, CC-BY, and NonCommercial.

***
## 6. Best Component-Level Assets
### C. Gearbox models
- **GrabCAD `gear reducer` / `gearbox` / `planetary gearbox` tags** — many STEP/IGES industrial reduction gearboxes and turbo gear units; pick a **parallel-shaft helical** unit to match AGMA 6011/API 613 form. Free (login), STEP → retopo for web.[^40][^41][^42]
- **Elecon TA/TAD turbo gear reference** (for correct proportions of a turbine step gear).[^24]
### D. Dynamometer models
![](images/image_5.jpg)
Eddy-Current Dynamometer
![](images/image_6.jpg)
Eddy Current Dynamometer
- **GrabCAD `dynamometer` / `eddy current` tags** — SolidWorks/SketchUp dyno assemblies; filter most-downloaded. STEP/native, free (login).[^43][^44][^45]
- Visual references for the dyno housing form (finned eddy-current or water-brake).
### E. Valves / piping / bearings / couplings
- **GrabCAD `gate valve` / `globe valve` / `valve` tags** — abundant STEP/IGES valves for ESV/TV bodies, bonnets, handwheels.[^46][^47][^48][^49]
- **GrabCAD flanges/pipe/coupling/bearing tags** — for inlet line, exhaust down-leg, leakage lines, shaft coupling, journal bearings.
- Model the **trip-throttle valve** as a globe-valve body + actuator + handwheel composite (matches Triveni combined T&T valve).[^7]

**Component reuse rule:** CAD (STEP/IGES) parts are geometrically accurate but heavy and un-UV'd. Import to Blender, **remesh/decimate to a web budget, then unwrap** for PBR textures.

***
## 7. Best Visual / Industrial Assets (materials, textures, HDRIs, symbols)
### G. SCADA / P&ID symbol libraries (for 2D overlay layer)
- **ANSI/ISA-5.1-2024** tag semantics and bubble symbols (PT/TT/FT/ZT/XT); Kimray P&ID reference guide for free ISA symbol usage. Render these as Babylon GUI/`AdvancedDynamicTexture` sprites.[^50][^26][^27]
### H. Industrial materials / PBR textures (prioritize CC0)
- **ambientCG** — 2,000+ CC0 PBR materials incl. Metal 032/041/046/048/049/050/053/055/061/062/063, corrugated steel; base color + normal + roughness + AO, multiple resolutions. **CC0, no attribution, free** — best default.[^51][^52][^4]
- **Poly Haven** — CC0 metal, painted metal shutter, factory wall, green metal rust, metal plate/grate. Free, CC0.[^53][^4]
- Use painted-steel + light rust variants for casing/baseplate; polished metal for shafts/couplings; insulation-cloth texture for the inlet steam line.
### I. HDRI / environment
- **Poly Haven HDRIs** and **ambientCG HDRIs** — CC0 industrial/warehouse/workshop lighting for realistic reflections in the test-cell scene. Free, CC0. Pick a factory/workshop HDRI to match Triveni's green-floor workshop look.[^53][^51]

***
## 8. Best Babylon.js-Compatible Visualization Resources (Section J)
Every technique below is confirmed reusable in Babylon.js:

| Feature | Babylon.js mechanism | Source |
|---|---|---|
| Sensor hotspots / floating labels | `GUI.AdvancedDynamicTexture` + `linkWithMesh`; parent GUI plane to submesh, enable `backFaceCulling` so it hides behind model | [^6][^5][^54] |
| Click/hover component selection | Scene picking / multi-pick rays; `onPointerUpObservable` on meshes | [^55][^6] |
| Glowing flow paths / heat coloration | `GlowLayer` + emissive material; animate emissive strength or UV offset | [^56][^57] |
| Animated steam / flow | Node Material with animated UV offset / procedural texture; `DynamicTexture` canvas | [^58][^59][^60] |
| Alarm/warning coloration | Drive material emissive/albedo from telemetry via `Animation.CreateAndStartAnimation` | [^56][^57] |
| Rotating shafts / gears | Per-node `rotation` animation on named shaft/gear meshes | [^55] |
| Vibration visualization | Small sinusoidal position offset on shaft nodes, amplitude ∝ mils reading (ISO 7919 scaled) | [^22] |
| Web asset prep | `gltf-transform` / `gltfpack` — Draco/meshopt geometry + WebP/KTX2 textures | [^61][^62][^63] |

Load these as your working set: the Babylon.js Node Material docs/editor, Dynamic Textures doc, GlowLayer glow examples, and the hotspot/annotation forum threads.[^5][^6][^58][^59][^56][^60]

***
## 9. Sensor Representation Strategy
The final model must support **both** a physical probe body **and** an interactive digital overlay for each tag. Represent them as follows, keyed to the PDF:

| Parameter (PDF tag) | Physical 3D representation | Placement | Digital overlay |
|---|---|---|---|
| Inlet pressure/temp/flow (PT109, TT109, FT110) | Transmitter body + impulse tube tap; orifice/flow element on inlet line | Inlet steam pipe upstream of ESV | ISA bubble "PT/TT/FT" + live value on hover[^26] |
| ESV actuator (PT108 / ACT_POS_FB) | Pneumatic/hydraulic actuator + positioner on trip-throttle valve | Above ESV valve bonnet | Actuator position bar (0–100%)[^7] |
| TV1/TV2 (PT111/TT111, PT112/TT112) | Two throttle-valve bodies with transmitters | Steam chest / valve rack before turbine | Per-valve P/T tooltips |
| Turbine inlet temp (PYRO_T) | Thermowell/pyrometer probe | Turbine inlet nozzle | Temp readout |
| Wheel case (PT120, TT120, FT162) | P/T taps + leakage flow element | Wheel-case body | P/T/flow card |
| Inter-GBC (PT161/163, TT161/163) | P/T taps between gear casings | Gearbox casing | P/T card |
| Exhaust (PT150A/B, TT150A/B) | P/T taps on exhaust down-leg | Exhaust manifold | P/T card |
| Leakage L1–L3 (PT160/161/162/163, FT162) | Small drain nozzles + collection pots | 3 leak-off points under casing/glands | Flow/pressure tags[^7] |
| Gearbox torque (GB_TRQ), Dyno power/speed/torque | Torque sensor on coupling; dyno readout head | Coupling + dyno | KPI gauges |
| **Turbine casing axial vib (ZT600 top, ZT601 bottom)** | **Accelerometer pucks** on casing top & bottom | Turbine casing (per ISO 20816) | Severity-colored dot (A–D zones)[^21] |
| **Turbine shaft radial (XT600/601 inlet, XT602/603 outlet)** | **X-Y proximity-probe pairs**, each pair 90° apart, mounted 45° from TDC | Inlet & outlet journal bearings | mils reading, orbit plot link[^15][^19] |
| **Gearbox radial (XT604/605 inlet, XT606/607 outlet)** | **X-Y proximity-probe pairs** | Gearbox input & output bearings | mils reading[^15] |

**Vibration detail (API 670):** model each radial location as **two cylindrical probe stems** entering the bearing housing at ±45° from top-dead-center (the X-Y orthogonal pair), and axial probes facing the shaft end / thrust collar for ZT600/601. Give each probe a **named anchor node** (e.g., `probe_XT600`) so ThingsBoard can bind the mils value and drive a color state.[^15]

***
## 10. Strategy Comparison — One Model vs. Composite
| Strategy | Description | Pros | Cons | Verdict |
|---|---|---|---|---|
| **A** | Find one turbine model and adapt | Fast start | No public model matches an API 611 single-stage test train; wrong architecture; heavy relicensing risk | Insufficient alone |
| **B** | Combine turbine + gearbox + dyno + valves + piping + instrumentation + environment | Each part best-in-class; matches schematic exactly | Integration/scale/material unification effort; mixed licenses to track | Strong, but needs custom glue |
| **C** | Rebuild key components from CAD/engineering refs | Maximum accuracy & clean topology; single license (yours) | Highest modeling effort | Best fidelity, slowest |
| **D — Hybrid (recommended)** | Custom-model the turbine/wheel-case, valves, probes; reuse downloadable CAD for gearbox/dyno/valves/piping; CC0 textures + HDRI; assemble & animate in Babylon | Balances effort, accuracy, licensing; hits every schematic element | Requires Blender + glTF pipeline discipline | **Recommended** |

**Recommendation: Strategy D.** The turbine casing, wheel-case, trip-throttle valves, and probe fittings define the rig's identity and have no clean drop-in — model these yourself against Elliott YR / Dresser-Rand RLHA / Triveni references. Reuse GrabCAD for the gearbox, dynamometer, valves, flanges, and couplings (retopologized), and unify everything with ambientCG/Poly Haven CC0 PBR and a workshop HDRI.

***
## 11. Exact Resources to Start With (Day-1 shortlist)
1. **Dimensions:** Elliott YR frame table + Dresser-Rand RLHA table → set wheel-case diameter, inlet/exhaust sizes, rpm, overall length.[^9][^2]
2. **OEM look:** Triveni API 611 single-stage page + brochure photos → valve/seal/bearing styling and baseplate color.[^29][^7]
3. **Gearbox:** a GrabCAD parallel-shaft helical reducer (STEP).[^40][^41]
4. **Dynamometer:** a GrabCAD eddy-current dyno (STEP) + Magtrol/SuperFlow visual refs.[^44]
5. **Valves/piping:** GrabCAD globe/gate valves + flanges/pipe.[^46][^47]
6. **Textures:** ambientCG Metal + painted-steel (CC0); Poly Haven painted metal/factory wall (CC0).[^53][^51]
7. **HDRI:** Poly Haven / ambientCG workshop HDRI (CC0).[^51][^53]
8. **Web pipeline:** `gltf-transform` (GitHub) + `gltfpack`.[^61][^64][^63]
9. **Babylon techniques:** GlowLayer, Node Material editor, Dynamic Textures, hotspot threads.[^6][^59][^56][^60]
## What must be modelled ourselves (no reusable drop-in)
- Single-stage **wheel-case / turbine casing** with correct taper and inlet nozzle group.
- **Trip-throttle ESV + TV1/TV2** valve rack with actuator/handwheels.
- **Probe fittings** (X-Y radial pairs at 45° TDC; axial casing pucks) — these are project-specific and must sit exactly where the PDF tags say.
- **Baseplate/soleplate + pedestals** tying turbine, gearbox, and dyno onto one frame.
- **Piping runs:** inlet steam (insulated), exhaust down-leg, three leakage/drain lines with collection pots.
- **Named sensor anchor nodes** for all 20+ process tags and 10 vibration probes.

***
## 12. Recommended Final 3D Architecture (Reconstruction Blueprint)
Target the model as a single GLB with a clean node hierarchy:

- **`Turbine_Assembly`**: tapered wheel-case (segmented ≥48-sided for smooth silhouette), inlet nozzle group, wheel-case body (PT120/TT120 taps), carbon-ring gland housings with leak-off nozzles, two journal-bearing housings with X-Y probe stems, coupling stub. Rotor/shaft as separate `Turbine_Shaft` node for spin animation; optional transparent-casing/cutaway variant exposing the impulse wheel.
- **`Admission_Assembly`**: ESV (trip-throttle globe body + actuator + positioner), TV1, TV2, steam chest, insulated inlet line, PT109/TT109/FT110 fittings.
- **`Gearbox_Assembly`**: parallel-shaft helical casing with split-line and inspection covers, input/output shaft stubs, inter-GBC taps (PT161/163, TT161/163), input/output X-Y probes (XT604–607).
- **`Dyno_Assembly`**: eddy-current/water-brake housing on its own pedestal, coupling to gearbox output, torque/speed/power readout head.
- **`Exhaust_Assembly`**: exhaust down-leg + PT150A/B, TT150A/B.
- **`Leakage_System`**: L1–L3 drain nozzles, small lines, collection pots, FT162 flow element.
- **`Baseplate`**: fabricated soleplate + pedestals + anchor bolts (grounds the whole train).
- **`Sensors`** (empty parent holding named anchors): `probe_XT600`…`XT607`, `probe_ZT600/601`, `tag_PT109`, `tag_TT109`, `tag_FT110`, etc.
- **`Environment`**: floor, optional control-cell backdrop, HDRI-lit.

Materials: painted-steel PBR (casing/baseplate, light wear), polished metal (shafts/couplings), insulation cloth (inlet line), dark cast (gearbox), finned metal (dyno). Emissive-capable submaterial on the steam-path/flow meshes for glow.

***
## 13. Babylon.js / ThingsBoard Preparation Spec
| Concern | Recommendation |
|---|---|
| **Format** | glTF 2.0 **.glb** (single file, embedded); export from Blender[^61] |
| **Polygon budget** | ~150k–400k tris total for the assembled train (web-comfortable at close zoom); LOD0 detailed, LOD1 ~40%, LOD2 ~15% for far views. Current 1,596 faces is far too low; CAD imports are far too high — decimate to budget[^62][^65] |
| **Compression** | `gltf-transform optimize` with **meshopt** (keeps hierarchy predictable) or Draco; **WebP/KTX2** textures at 1K for browser[^61][^63][^62] |
| **Materials** | PBR metallic-roughness only (glTF-native); reuse spec's metallic 0.7 / roughness 0.35 as a starting point but add normal/roughness/AO maps[^1] |
| **Textures** | 1K CC0 sets (ambientCG/Poly Haven); atlas where possible to cut draw calls[^51][^53] |
| **Animations** | Named clips: `shaft_spin`, `gear_spin`, `valve_open`, `steam_flow`, `vib_*`; drive via `AnimationGroup` |
| **Node hierarchy** | Assembly-based (Section 12); one root, logical sub-assemblies |
| **Naming conventions** | Machine-readable, tag-matched: `probe_XT600`, `tag_PT109`, `mesh_Turbine_Casing`, `node_Turbine_Shaft` — ThingsBoard widget binds telemetry by exact name |
| **Sensor attachment points** | Dedicated empty/anchor nodes at each probe/tag location; GUI planes parented to them with `backFaceCulling`[^6] |
| **Interaction/picking** | `scene.onPointerObservable` + `mesh.isPickable`; multi-pick for overlapping probes[^55][^6] |
| **Dynamic materials** | GlowLayer + emissive for flow/heat/alarm; animate emissive from telemetry[^56][^57] |
| **Camera** | `ArcRotateCamera` with framing presets (front/iso/cutaway/exploded) and smooth transitions[^55] |
| **ThingsBoard** | Deliver as one optimized .glb loaded by a custom widget; keep the mesh-name contract stable so the widget's JS can map RPC/telemetry to nodes |

***
## Key Takeaways
- The GLB looks poor purely because of **modeling/authoring** deficits — primitive geometry, no baseplate, no piping, no probes, flat untextured materials — **not** because of Babylon.js or ThingsBoard.[^1]
- The rig is an **API 611 single-stage steam turbine test train** (turbine → helical gearbox → dynamometer), ~100–500 kW class.[^7][^8]
- Standards that genuinely apply: **API 611** (machine), **API 670 + ISO 20816/7919** (vibration/probes), **AGMA 6011/API 613** (gearbox), **ISA-5.1** (tags/overlays); ASME PTC 6 and API 612 are contextual only.[^21][^15][^23][^26]
- No single downloadable model matches the rig; adopt **Strategy D (hybrid)** — custom-model the turbine/valves/probes, reuse GrabCAD gearbox/dyno/valves, skin with **CC0 ambientCG/Poly Haven** PBR and HDRI, and prepare via **gltf-transform/gltfpack** with tag-matched node names for ThingsBoard binding.[^51][^61]

---

## References

1. [turbine_rig_prototype_SPECIFICATION.pdf](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/30049091/ef3ecbe8-802d-4a92-93ec-71ae31b5d75e/turbine_rig_prototype_SPECIFICATION.pdf)

2. [Single-Stage Steam Turbines | PDF | Turbomachinery - Scribd](https://www.scribd.com/document/470007770/yr-steam-turbines) - Elliott YR steam turbines are designed for versatile operation in various environments, featuring a ...

3. [Leading Steam Turbine Manufacturer](https://www.triveniturbines.com/manufacturing/) - Triveni Turbines, World-class integrated manufacturing and testing facilities with best-in-class mac...

4. [Free Metal Textures (PBR, Seamless) | Cinevva](https://app.cinevva.com/game-assets/free-metal-textures) - Free CC0 seamless metal textures with PBR maps: steel, rust, painted metal, and industrial plate for...

5. [Interactive hotspots on model - Questions - Babylon.js Forum](https://forum.babylonjs.com/t/interactive-hotspots-on-model/4558) - Here's an example of a tooltip using the 2D GUI. You have many other options towards how you want to...

6. [How can I add hotspot buttons on a glb model - Babylon.js Forum](https://forum.babylonjs.com/t/how-can-i-add-hotspot-buttons-on-a-glb-model/48598) - The most simple way I can think of would be to create GUI.AdvancedDynamicTexture for a plane mesh, t...

7. [Single Stage Steam Turbine | Triveni Turbines](https://www.triveniturbines.com/products/api-steam-turbine/api-single-stage-turbine/) - Find the perfect single stage steam turbine for your project. Explore our selection, including API-c...

8. [API - STD 611 - General-purpose Steam Turbines for Petroleum ...](https://standards.globalspec.com/std/14517020/std-611) - Requirements for special-purpose turbines are defined in API 612. In case of conflict between this s...

9. [Axial Split Casing Overspeed Trip System Governing Systems ...](https://www.mcraeeng.com/files/single-stage-turbine-603159.pdf) - A Turbine turdy, versatile mechanical drive steam turbine for applications up to 2,500 HP (1,865kW)....

10. [Products | Triveni Power Transmission Limited](https://www.trivenipowertransmission.com/products.html) - Test Rig High-speed gearboxes developed for testing and validation applications across wide operatin...

11. [How Full-Train Validation Is Raising the Reliability Benchmark for ...](https://www.powermag.com/how-full-train-validation-is-raising-the-reliability-benchmark-for-high-power-steam-turbines/) - Triveni Turbine validated a complete 60-MW turbine-generator ・ using a dynamometer to simulate real ...

12. [Triveni Turbine Limited - LinkedIn](https://www.linkedin.com/company/triveni-turbines) - Triveni Turbines integrated the steam turbine, gearbox, generator and dynamometer to test the comple...

13. [Steam Turbine Product List](https://www.triveniturbines.com/products/) - We offer a wide range of API-compliant steam turbines from 5 kW and up to 100 MWe in Backpressure an...

14. [[PDF] api 613, fifth edition, special purpose gear units for petroleum ...](https://www.lubepower.com/images/docs/t33-16.pdf) - API 613 provides a conservative basis for building critical service process industry turbomachinery ...

15. [[PDF] API Standard 670](https://eballotprodstorage.blob.core.windows.net/eballotscontainer/670_e6_Ballot_Draft.pdf) - Two associated measurement locations (such as the X and Y proximity probes at a particular radial be...

16. [Difference Between API 611 and API 612 - Mechanical ... - Scribd](https://www.scribd.com/document/513256981/Difference-between-API-611-and-API-612-Mechanical-Engineering-Site) - Difference between API 611 and API 612 - Mechanical Engineering Site - Free download as PDF File (.p...

17. [API 611 vs API 612: Understanding the Difference Between ...](https://www.linkedin.com/pulse/api-611-vs-612-understanding-difference-between-general-purpose-kkfuc) - At first glance, both standards govern steam turbines used in petroleum, petrochemical, and gas proc...

18. [Driving Excellence with API 611 & API 612 Turbine Standards ...](https://www.linkedin.com/posts/pavan-gadgi-7baa7b155_steamturbines-apistandards-api611-activity-7347485265214525440-lWKJ) - By comparing API 611 and API 612 side-by-side, we see a path from good to great: • Match solutions p...

19. [Proximity Probes - MC-monitoring](https://mc-monitoring.com/products-service/sensors/proximity-probes/) - Proximity probes are non-contact eddy-current sensors used to measure shaft vibration and axial thru...

20. [ISO/DIS 20816-1 (en), Mechanical vibration — Measurement and ...](https://www.iso.org/obp/ui/en/) - This document establishes general guidelines for the measurement and evaluation of mechanical vibrat...

21. [ISO 10816 / 20816 Vibration Severity Chart and Limits Explained](https://theuniteststandard.com/articles/what-is-iso-10816-vibration.html) - ISO 10816 measures vibration on the non-rotating parts of a machine (bearing housings, casings), whi...

22. [ISO Vibration Standards: A Practical Guide for Engineers](https://www.forgereliability.com/iso-vibration-standards/) - Master ISO vibration standards with this guide for reliability engineers. Apply ISO 20816, 10816 & 7...

23. [[PDF] review of api versus agma gear standards - OAKTrust](https://oaktrust.library.tamu.edu/bitstreams/5bbb9f7f-edad-4c4e-bf30-aa23ffde1b68/download) - The AGMA Standard 6011 (1998) is a specification for high-speed enclosed helical gear units. It does...

24. [Custom Turbo Gearbox Units | Elecon API Double Helical Gear ...](https://www.artec-machine.com/custom-turbo-gearbox-units-elecon-api-double-helical-gear-systems/) - Capable of supporting outputs up to 150,000 kW, AGMA 6011-J14. API-613 High Speed 4

25. [[PDF] Special Purpose Gear Units for Petroleum, Chemical and Gas ...](http://aceconsultant.ir/wp-content/uploads/2024/08/API-613-5th-edition-2003.pdf) - HIGH SPEED GEAR UNITS. a gear may need high viscosity and a turbine may need a conventional mineral ...

26. [ANSI/ISA 5.1-2024: Instrumentation Symbols & Identification](https://blog.ansi.org/ansi/ansi-isa-5-1-2024-instrumentation-symbols/) - P&ID tag symbols are alphanumeric codes inside bubbles (circles, squares, or diamonds) that identify...

27. [[PDF] P&ID Reference Guide - Kimray](https://kimray.com/sites/default/files/uploads/training-demos/Kimray%20How%20to%20Read%20an%20Oil%20&%20Gas%20P&ID%20Reference%20Guide.pdf) - ANSI/ISA-5.1-2009 Instrumentation Symbols and Identification. Symbols 1-14, when combined with actua...

28. [Elliott Steam Turbines - PDF Catalogs | Technical Documentation](https://pdf.directindustry.com/pdf/elliott-group/elliott-steam-turbines/34817-71414.html) - The YR turbine models are standardized for quick turnaround and flexibility, available in single-val...

29. [Power Insights in Brochures | Triveni Turbines](https://www.triveniturbines.com/brochures/) - Explore and download Triveni Turbines' brochures and catalogues featuring high-performance steam tur...

30. [Optimizing Quality Assurance & Management in Power Solutions](https://www.triveniturbines.com/quality/) - Triveni Turbine Ltd … in-house Test Facility that performs 15+ point quality checks before dispatch....

31. [Steam Turbine - 3D model by CanopyCreative - Sketchfab](https://sketchfab.com/3d-models/steam-turbine-2471ad99fcf64ec286684784a80f85fe) - This interactive, animated 3D model visualises the internal mechanics of a steam turbine system, fro...

32. [Steam Turbine - Download Free 3D model by landinweaver](https://sketchfab.com/3d-models/steam-turbine-bcc264eafbe4412d9c061d6d97f30b99) - Sorry, the model can't be displayed. Please check out our FAQ to learn how to fix this issue. No des...

33. [Steam Turbine Generator Skoda 35 MW + Tour 360 - 3D model by ...](https://sketchfab.com/3d-models/steam-turbine-generator-skoda-35-mw-tour-360-7f0b3504d36945c5949a855106ecb1c7) - A component of the Szombierki heat and power plant - Skoda turbine set installed in the 1950s, repla...

34. [Steamturbine 3D models - Sketchfab](https://sketchfab.com/tags/steamturbine) - Steamturbine 3D models ready to view and download for free. Popular Steamturbine 3D models. View all...

35. [steam turbine - Recent models | 3D CAD Model ... - GrabCAD](https://grabcad.com/library/tag/steam%20turbine) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Join the GrabCAD ...

36. [steam-turbine - Recent models | 3D CAD Model ... - GrabCAD](https://grabcad.com/library/tag/steam-turbine) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Join the GrabCAD ...

37. [Steam Turbine 3D Models for Free Download and Print | Tripo AI](https://studio.tripo3d.ai/3d-model-gallery/steam-turbine) - Free & premium 20 steam turbine 3D models, ready for 3D printing, game development, 3D design, eComm...

38. [Free 3D GlTF Models - Download .gltf Files On TurboSquid](https://www.turbosquid.com/Search/3D-Models/free/steam-turbine-model/gltf) - 100+ free glTF 3D models. High quality .blend files for any industry--games, VFX, real-time, adverti...

39. [Free glTF Industrial-Steam-Turbine Models | TurboSquid](https://www.turbosquid.com/Search/3D-Models/free/industrial-steam-turbine/gltf) - Free glTF 3D industrial-steam-turbine models for download, files in gltf with low poly, animated, ri...

40. [gear reducer - 3D CAD Model Collection - GrabCAD](https://grabcad.com/library/tag/gear%20reducer) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Reducer (1:10 Rat...

41. [gearbox | 3D CAD Model Collection | GrabCAD Community Library](https://grabcad.com/library/tag/gearbox) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Precision Planeta...

42. [planetary gearbox - Recent models | GrabCAD Community Library](https://grabcad.com/library?utf8=%E2%9C%93&query=planetary%20gearbox) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. STEP / IGES. Plan...

43. [eddy current - 3D CAD Model Collection - GrabCAD](https://grabcad.com/library/tag/eddy%20current) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Join the GrabCAD ...

44. [dynamometer - Most liked models | GrabCAD Community Library](https://grabcad.com/library?softwares=google-sketchup&sort=most_liked&tags=dynamometer) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Join the GrabCAD ...

45. [SOLIDWORKS, dynamometer - Most downloaded models - GrabCAD](https://grabcad.com/library?softwares=solidworks&sort=most_downloaded&tags=dynamometer) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Join the GrabCAD ...

46. [gate valve | 3D CAD Model Collection | GrabCAD Community Library](https://grabcad.com/library?page=1&time=all_time&query=gate%20valve) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. STEP / IGES , Glo...

47. [Globe valve | 3D CAD Model Collection | GrabCAD Community Library](https://grabcad.com/library?query=Globe+valve+) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. STEP / IGES , Gat...

48. [STEP / IGES, valve - Most downloaded models | 3D CAD ... - GrabCAD](https://grabcad.com/library?page=4&softwares=step-slash-iges&sort=most_downloaded&tags=valve) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Join the GrabCAD ...

49. [valve - Recent models | 3D CAD Model Collection - GrabCAD](https://grabcad.com/library/tag/valve) - The GrabCAD Library offers millions of free CAD designs, CAD files, and 3D models. Join the GrabCAD ...

50. [ISA5.1, Instrumentation Symbols and Identification](https://www.isa.org/standards-and-publications/isa-standards/isa-standards-committees/isa5-1) - The purpose of this standard is to establish a uniform means of designating instruments and instrume...

51. [ambientCG - Free Textures, HDRIs and Models](https://ambientcg.com/) - Free 3D Assets Never Looked This Good! Get 2000+ PBR Materials, HDRIs and more for free under the CC...

52. [Category: Metal | ambientCG](https://ambientcg.com/list?category=Metal) - Get 2000+ PBR Materials, HDRIs and more for free under the Public Domain license.

53. [Textures: Metal • Poly Haven](https://polyhaven.com/textures/metal) - Free Metal PBR texture sets, ready to use for any purpose. No login required.

54. [Babylonjs hotspots/annotations - Questions - Babylon.js](https://forum.babylonjs.com/t/babylonjs-hotspots-annotations/13341) - I know there is a way to connect GUI with the mesh in Babylon. But I am not sure how it works when u...

55. [How do you attach a glf model to a mesh when the mesh is clicked?](https://forum.babylonjs.com/t/how-do-you-attach-a-glf-model-to-a-mesh-when-the-mesh-is-clicked/17240) - First load all of your assets in the scene using asset containers. Here's a simple example: playgrou...

56. [How to make glow shader to mimic the Car led's animation ...](https://forum.babylonjs.com/t/how-to-make-glow-shader-to-mimic-the-car-leds-animation-happening-nowadays/48080) - You simply need to have some emissive areas in your glb. An emissive material is enough to activate ...

57. [Node material animations - Questions - Babylon.js](https://forum.babylonjs.com/t/node-material-animations/20294) - This example is doing two different types of setting variables, one for enabling/disabling the glow ...

58. [Node Material | Babylon.js Documentation](https://doc.babylonjs.com/features/featuresDeepDive/materials/node_material/nodeMaterial) - The Node Material is a simple, highly customizable material that you can build yourself piece by pie...

59. [Dynamic Textures | Babylon.js Documentation](https://doc.babylonjs.com/features/featuresDeepDive/materials/using/dynamicTexture) - This playground example incorporates a user-manipulated dynamic texture allowing the customization o...

60. [Babylon.js Node Material Editor](https://nodematerial-editor.babylonjs.com/) - Cube Cylinder Plane Shader ball Sphere Load...

61. [glTF Transform](https://gltf-transform.dev/) - Transform supports reading, editing, and writing 3D models in glTF 2.0 format. bundling, splitting, ...

62. [About the gltf-transform Tool - Questions - Babylon.js Forum](https://forum.babylonjs.com/t/about-the-gltf-transform-tool/49116) - You may try to use Draco compression, it gives even better results sometimes. to compress resources ...

63. [Meshopt | View3D - NAVER Open Source](https://naver.github.io/egjs-view3d/docs/tutorials/Compression/Meshopt) - Meshopt Compression is GPU-friendly mesh optimization that makes meshes smaller and faster to render...

64. [donmccurdy/glTF-Transform: glTF 2.0 SDK for JavaScript ... - GitHub](https://github.com/donmccurdy/glTF-Transform) - Transform supports reading, editing, and writing 3D models in glTF 2.0 format. optimizing an existin...

65. [Plant geometry for large GLTF-based scenes - three.js forum](https://discourse.threejs.org/t/plant-geometry-for-large-gltf-based-scenes/86354) - And use draco compression to reduce gltf file size … to run the file through an optimizer like gltfp...

