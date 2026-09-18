# Turbine 3D Rebuild — Phase 1/2 Decision Log

Tracks judgment calls made while executing the GLB Reconstruction Blueprint
(`docs/roadmap/3d-turbine/blueprint.md`).
Update this file whenever a non-obvious choice is made so future sessions don't
re-derive the reasoning.

## Phase 1 — Foundation (complete)

- **Sensor-mesh naming contract** built at `app/config/turbine_sensor_mesh_map.json`
  (34 entries) directly from Blueprint Section 9. This is the binding contract
  ThingsBoard's widget JS will use to attach telemetry to named GLB nodes —
  do not rename mesh_name values without updating both this file and the
  eventual Blender scene.
- **Dimension references**: Dresser-Rand RLHA table fully captured (2 frame
  sizes, verified). Elliott YR table is **partial/unverified** — only frame
  names + wheel diameters recovered via search snippets; the full spec table
  (inlet/exhaust size, rpm, capacity, weight per frame) could not be fetched.
  Every direct host (elliott-turbo.com, Scribd, pdf4pro, pdfcoffee) blocked
  scripted access (403 / connection reset / login wall). **Open item**: a
  human opening the link in a real browser can finish this in ~2 minutes;
  see `reference_images/dimension_tables.md` for the exact URLs.
- **Blender node hierarchy scaffold** (`blender_project/node_hierarchy_scaffold.json`)
  built from Blueprint Section 12. Deviated from the literal task instruction:
  instead of parking all 34 sensors under one `Sensors` node, they were
  distributed into their physically correct parent assembly (e.g. `PT109`
  under `Admission_Assembly`) using the `assembly_parent` field already
  present in the sensor map. Kept — it's more useful for Blender work later,
  and no sensor data was lost (35 total children = 34 sensors + `Turbine_Shaft`).
- **Material assignment map** (`textures/material_assignment_map.json`) maps
  all 17 downloaded CC0 textures + 3 HDRIs to specific assemblies, sourced
  from the notes already written into `asset_inventory.csv` — no new
  judgment calls invented there.
- **Licensing wall confirmed real**: every non-CC0 source in the Blueprint
  (Sketchfab, GrabCAD, Tripo AI, TurboSquid) turned out to require an
  authenticated, human, browser session — no automated agent can download
  from these. This is why CAD acquisition became a manual (user) task instead
  of something Flash/Haiku could execute.

## Phase 1.5 — Manual CAD acquisition (in progress)

Decision: split CAD downloads between user (manual GrabCAD browser session,
required due to the licensing wall above) and Claude (link curation +
visual/format verification once user pastes screenshots).

### Downloaded so far

| Component | Folder | Format status | Verdict |
|---|---|---|---|
| Gearbox | `cad_source/gearbox_single_stage_helical/` | **SolidWorks native only** (12 files: `.SLDPRT`/`.SLDASM`) — no STEP/IGES in the download | Good visual match (parallel-shaft helical, split-line casing) — kept, needs conversion before Blender use |
| Gate valve | `cad_source/gate_valve/` | Has both `.STEP` and `.IGS` — ready to use, best-equipped of the three | Correct shape (threaded ends, straight bore, wheel handle) — lower priority (general piping only, not part of admission rack) |
| Globe valve | `cad_source/globe_valve/` | Has `.IGS` — ready to use | **Primary match for ESV/TV1/TV2 trip-throttle bodies** — has bonnet + handwheel + flow-direction arrow, exactly the shape Blueprint Section 6/12 calls for |
| Dynamometer | not yet downloaded | — | First attempt (search tag "eddy current") returned the **wrong machine class** — an automated OD-measurement/eddy-current-NDT/laser-marking inspection line, not a load-absorbing dynamometer. "Eddy current" is ambiguous between NDT flaw-detection and dynamometer braking; the search tag doesn't disambiguate. **Better candidate found** (unverified — GrabCAD blocks automated fetch, 403): `grabcad.com/library/small-engine-dynamometer-1` — user should visually confirm before downloading. |

**File integrity check performed**: read raw STEP/IGES headers directly
(both are ASCII formats). Confirmed genuine CAD exports, not corrupted or
placeholder files — gate valve STEP is AP214 schema from SolidWorks 2013;
globe valve IGES confirmed millimeter units, SolidWorks 2013, dated
2014-05-09.

**Attribution tracking**: all three downloaded components logged into
`ATTRIBUTION.md`'s GrabCAD table with placeholder "NOT YET CAPTURED" license
text — **user has not yet reported the exact license string shown on each
GrabCAD download page**. This must be filled in before any of these assets
are used in a commercial/external deliverable (GrabCAD's Community Terms are
ambiguous on commercial rights by default).

## Phase 2 prep — CAD conversion tooling (in progress)

- **Problem**: this execution environment has zero 3D/CAD tooling out of the
  box — no Blender, no FreeCAD, no OpenCascade/pythonocc, no mesh library.
  Confirmed by direct check, not assumed.
- **Decision**: install **FreeCAD** via conda into an isolated environment
  (`conda create -n freecad_env -c conda-forge freecad`), rather than the
  base Python env, so it's reversible and won't collide with other project
  dependencies. Chose FreeCAD over pythonocc-core directly because it has a
  more complete scripted import/export pipeline (STEP/IGES → glTF/OBJ) via
  `freecadcmd`, and a larger community track record for headless conversion
  scripts.
- **Status at time of writing**: install kicked off, running in background —
  check `conda env list` for `freecad_env` and `conda run -n freecad_env
  freecadcmd --version` to confirm before relying on it.
- **Once available**, plan is to script a headless conversion for:
  - `cad_source/gate_valve/original.STEP` → glTF
  - `cad_source/globe_valve/Válvula globo 1 polegada - Deca.IGS` → glTF
  - Gearbox: **blocked** — FreeCAD's SolidWorks import support is unreliable
    for complex assemblies; may need a different tool or the user opening it
    in real SolidWorks/OnShape to export STEP first. Do not assume FreeCAD
    will handle `final.SLDASM` cleanly — verify before trusting the output.

## Phase 2 prep — CAD conversion executed (complete, with caveats)

FreeCAD install (conda env `freecad_env`, FreeCAD 1.1.3) succeeded. Converted
both ready valve files (gate valve STEP, globe valve IGES) through a working
headless pipeline: **FreeCAD (`freecadcmd`, `Part.Shape.read` +
`shape.tessellate(0.1)` + `Mesh.write`) → OBJ → trimesh → self-contained
`.glb`.** Output files:

- `cad_source/_converted_gltf/gate_valve.glb` — 1,085,028 triangles, bbox
  57.5 × 110.6 × 55.0 mm (matches the "1 inch" marking visible in the
  reference render — plausible real-world scale)
- `cad_source/_converted_gltf/globe_valve.glb` — 297,532 triangles, bbox
  70.0 × 130.3 × 78.0 mm

**Bugs hit and fixed along the way (documented so they aren't re-debugged
blind next time):**

1. `freecadcmd` silently produced zero script output/failed on the globe
   valve's original filename (`Válvula globo 1 polegada - Deca.IGS`) —
   the accented characters broke something in FreeCAD's file-path handling
   at the C++ layer, with no traceback surfaced. **Fix**: copied the file to
   an ASCII-safe name (`globe_valve_1in_deca.igs`) before conversion.
   General lesson: any file this pipeline touches needs an ASCII filename
   first — don't assume UTF-8 filenames are safe with FreeCAD's importer.
2. `trimesh`'s `.gltf` (non-binary) export writes external `.bin` buffers
   with **generic, non-unique filenames** (`gltf_buffer_0.bin`, etc.) into
   the working directory. Exporting a second mesh into the same folder
   silently overwrote the first mesh's buffer file, corrupting it —
   confirmed by two "different" decimated outputs having byte-identical
   file sizes and triangle counts, and the first `.gltf` failing to
   reload entirely. **Fix**: always export as self-contained `.glb`
   (binary glTF, buffers embedded) when working in a shared directory —
   never bare `.gltf` with default buffer naming. **This is a real
   correctness bug, not a style preference — verify triangle counts with
   an independent loader after every conversion step, don't trust a
   tool's own summary line.**
3. `@gltf-transform/cli simplify` (meshoptimizer-based edge-collapse)
   achieved only ~10% triangle reduction regardless of `--ratio`/`--error`
   settings, and its own `weld` pre-pass found nothing to merge (file size
   unchanged after weld). Root cause: FreeCAD's raw tessellation output is
   **"faceted"** — every triangle owns its own unique vertex positions with
   no shared topology/indices, even where triangles are visually adjacent.
   Edge-collapse simplification needs a proper manifold mesh with shared
   vertices to find valid collapse candidates; a faceted mesh gives it
   almost nothing to work with, and CLI-level welding wasn't able to
   recover that topology automatically (likely a tolerance/epsilon
   mismatch between tessellation noise and exact-match welding).
   **Decision: did not keep fighting this with CLI tools.** The raw,
   un-decimated `.glb` files (above) are correct and usable, just heavier
   than the report's target budget. Real decimation/retopology for these
   parts needs to happen inside Blender (Decimate modifier with a proper
   remesh, or manual retopo) — which is what the blueprint's Strategy D
   assumed a human would do in Blender anyway. Treat this as expected
   Phase 2 work, not a blocker to fix here.

4. `freecadcmd script.py` runs the script with `__name__` set to the
   **filename** (e.g. `"convert_cad_to_glb"`), never `"__main__"`. A normal
   `if __name__ == "__main__":` guard silently never fires — the script
   appears to do nothing, with the only visible output being FreeCAD's
   banner and a bare exit code 1 on any code that assumed the guard would
   run. Confirmed by direct test. **Any future script meant to run via
   `freecadcmd` must not gate its entry point behind that guard** — run
   top-level code unconditionally instead. This is now baked into
   `blender_project/convert_cad_to_glb.py`, which is the cleaned-up,
   tested, reusable version of the ad-hoc scripts used above (those
   scratch scripts were deleted after verifying this one reproduces their
   output correctly).

**Gearbox**: attempted and confirmed blocked. Tested `Part.Shape.read()` on
`housing.SLDPRT` alone (simplest possible case, single part, no assembly
references) — failed immediately with `OSError('Unknown extension')`. This
is not a missing-package or config problem: **open-source FreeCAD has no
native reader for SolidWorks' proprietary binary format at all**, with or
without an add-on. This closes off the "try converting it here" path
entirely — don't re-attempt this with the same tool. Real options, in order
of effort:
1. User (or anyone) opens the files in real SolidWorks and does File → Save
   As → STEP. Cleanest, fully faithful.
2. Try OnShape's free tier (browser-based, has a SolidWorks import + STEP
   export flow) — untested here, no login credentials available to verify.
3. Re-search GrabCAD for a *different* parallel-shaft helical gearbox model
   that ships with STEP/IGES natively from the start (the valve searches
   proved this is possible — both valve downloads had native STEP/IGES
   available; this gearbox model just happened not to).

## Outstanding decisions for the user

1. Confirm the `small-engine-dynamometer-1` GrabCAD candidate visually
   before downloading (I can't fetch GrabCAD pages directly — 403 blocked).
2. Report back the license text shown on the GrabCAD download page for all
   three (soon to be four) downloaded components, for `ATTRIBUTION.md`.
3. Decide how to handle the gearbox's SolidWorks-only format if FreeCAD's
   conversion doesn't work cleanly — options are: open in FreeCAD manually,
   use a paid/online converter, or find a different gearbox model that
   ships with STEP/IGES natively (re-search GrabCAD with the "STEP/IGES"
   software filter applied from the start, as already done for the valves).
4. Confirm the Elliott YR frame-size table (see Phase 1 note above) if a
   precise dimensional anchor is wanted before Blender modeling locks in
   scale.
