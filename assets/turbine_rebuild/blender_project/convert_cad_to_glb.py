"""Headless STEP/IGES -> self-contained .glb conversion.

Two-stage pipeline (see DECISIONS.md for why each stage exists):
  1. FreeCAD (freecadcmd) reads the STEP/IGES shape and tessellates it to a
     mesh, written out as .obj.
  2. trimesh loads the .obj and re-exports as a single self-contained .glb
     (NOT bare .gltf — that writes external .bin buffers with generic
     filenames that collide across multiple conversions in the same folder).

Known limits:
  - Source filenames must be ASCII. FreeCAD's Part.Shape.read() fails
    silently (no traceback, zero script output) on accented filenames.
    Copy to an ASCII-safe name first if needed.
  - FreeCAD cannot read SolidWorks native files (.SLDPRT/.SLDASM) at all —
    OSError('Unknown extension'). STEP/IGES only.
  - Output triangle counts are NOT decimated. Raw FreeCAD tessellation
    produces a "faceted" mesh (no shared vertex topology), which defeats
    gltf-transform's edge-collapse simplify/weld almost entirely. Real
    decimation needs to happen in Blender (Decimate modifier / remesh),
    not this script.

Usage (must run the FreeCAD stage inside the freecad_env conda env via
freecadcmd, not plain python3 — FreeCAD's Python module isn't on a normal
interpreter's path):

    conda run -n freecad_env freecadcmd convert_cad_to_glb.py \
        <input.step_or_iges> <output_basename>

Then this same script's second stage (trimesh) runs fine under the normal
project python3 — split into two invocations if trimesh isn't installed
inside freecad_env.
"""
import os
import sys

OUT_DIR = "assets/turbine_rebuild/cad_source/_converted_gltf"


def freecad_stage(src_path, out_basename):
    import FreeCAD
    import Part
    import Mesh

    os.makedirs(OUT_DIR, exist_ok=True)
    doc = FreeCAD.newDocument("conv")
    shape = Part.Shape()
    shape.read(src_path)

    obj = doc.addObject("Part::Feature", "ImportedShape")
    obj.Shape = shape
    doc.recompute()

    mesh = Mesh.Mesh()
    mesh.addFacets(shape.tessellate(0.1))

    obj_path = os.path.join(OUT_DIR, f"{out_basename}.obj")
    mesh.write(obj_path)

    bbox = shape.BoundBox
    print(
        f"OK: {src_path} -> {obj_path} | triangles={mesh.CountFacets} | "
        f"bbox_mm=({bbox.XLength:.1f}, {bbox.YLength:.1f}, {bbox.ZLength:.1f})",
        flush=True,
    )
    FreeCAD.closeDocument(doc.Name)


def trimesh_stage(out_basename):
    import trimesh

    obj_path = os.path.join(OUT_DIR, f"{out_basename}.obj")
    glb_path = os.path.join(OUT_DIR, f"{out_basename}.glb")
    m = trimesh.load(obj_path)
    m.export(glb_path)  # self-contained .glb — do NOT use bare .gltf here
    os.remove(obj_path)
    print(f"OK: {obj_path} -> {glb_path} (obj intermediate removed)", flush=True)


# NOTE: no `if __name__ == "__main__":` guard here on purpose.
# freecadcmd runs a passed .py file with __name__ set to the filename
# (e.g. "convert_cad_to_glb"), NOT "__main__" — a standard Python idiom
# silently never fires under freecadcmd. Confirmed by direct test; this
# cost real debugging time, so it's called out here instead of buried in
# DECISIONS.md alone. Module-level execution is safe since this file is
# always run standalone, never imported.

# freecadcmd prepends 'freecadcmd' as argv[0] (script path becomes argv[1]),
# while plain `python3 script.py a b` gives argv[0]=script, argv[1]=a,
# argv[2]=b. Negative indices are correct under both callers.
_src, _out_basename = sys.argv[-2], sys.argv[-1]

try:
    import FreeCAD  # noqa: F401
except ImportError:
    trimesh_stage(_out_basename)
else:
    freecad_stage(_src, _out_basename)
