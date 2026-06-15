#!/usr/bin/env python3
"""Split a Bambu/Orca multi-color 3MF into one mesh per painted filament colour.

Unlike the original color_split_enhanced.py, this:
  * parses ``paint_color`` as **hexadecimal** (so no triangles are dropped),
  * decodes each code to the real filament/extruder and resolves its colour
    from ``Metadata/project_settings.config``,
  * names each output by colour (e.g. ``bee_filament2_yellow_FFFF00.stl``),
  * writes a single colour-accurate ``*_preview.glb`` so you can confirm the
    split visually before printing,
  * reports palette colours that were defined but never actually painted.

Usage:
  python color_split_bambu.py input.3mf [-o OUT] [-f stl|obj|ply] [--info] [--no-preview]
"""
import argparse
import logging
import sys
import zipfile
from pathlib import Path

import numpy as np
import trimesh

import bambu_paint as bp

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _hex_to_rgba(color_hex: str) -> tuple:
    h = color_hex.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def _face_codes(model_xml: str) -> list:
    """Per-face paint code in document order (empty string = unpainted)."""
    groups = bp.extract_paint_groups(model_xml)
    n = sum(len(v) for v in groups.values())
    codes = [""] * n
    for code, idxs in groups.items():
        for i in idxs:
            codes[i] = code
    return codes


def load_mesh_and_codes(path: str):
    """Load geometry (trimesh) and the per-face paint code, palette, default extruder.

    trimesh(process=False) preserves triangle order, so face i corresponds to
    the i-th ``<triangle>`` in the model part -- a direct, exact mapping.
    """
    with zipfile.ZipFile(path) as z:
        palette = bp.read_filament_colors(z)
        default_extruder = bp.read_default_extruder(z)
        parts = bp.object_model_names(z)
        per_part_codes = [_face_codes(z.read(n).decode("utf-8", "replace")) for n in parts]

    scene = trimesh.load(str(path), process=False)
    geoms = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]

    if len(geoms) == 1 and len(per_part_codes) == 1:
        mesh, codes = geoms[0], per_part_codes[0]
    else:
        logger.warning("Multi-part model (%d geometry / %d model parts): aligning by "
                       "order (best-effort).", len(geoms), len(per_part_codes))
        mesh = trimesh.util.concatenate(geoms)
        codes = [c for part in per_part_codes for c in part]

    if len(codes) != len(mesh.faces):
        raise SystemExit(f"Aborting: {len(mesh.faces)} faces but {len(codes)} paint codes "
                         "- cannot map colours reliably.")
    return mesh, np.array(codes, dtype=object), palette, default_extruder


def color_groups(codes, palette, default_extruder):
    by_code = {}
    for i, c in enumerate(codes):
        by_code.setdefault(c, []).append(i)
    return bp.assign_colors(by_code, palette, default_extruder)


def report(groups, palette, total_faces):
    logger.info("Found %d colour group(s) across %d triangles:", len(groups), total_faces)
    for g in groups:
        pct = 100.0 * g.face_count / total_faces if total_faces else 0
        code = g.code or "(unpainted)"
        logger.info("  extruder %d  %-7s %s  code=%-4s  %8d faces (%4.1f%%)",
                    g.extruder, g.name, g.color_hex, code, g.face_count, pct)
    used = {g.color_hex.upper() for g in groups}
    unused = [c for c in palette if c and c.upper() not in used]
    if unused:
        logger.info("Palette colours defined but never painted: %s",
                    ", ".join(f"{c} ({bp.color_name(c)})" for c in unused))


def export_splits(mesh, groups, stem, outdir, fmt):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for g in groups:
        sub = mesh.submesh([g.faces], append=True)
        fname = f"{stem}_filament{g.extruder}_{g.name}_{g.color_hex.lstrip('#')}.{fmt}"
        path = out / fname
        sub.export(str(path))
        logger.info("Exported %s (%d faces)", path, g.face_count)
        written.append(path)
    return written


def export_preview(mesh, groups, stem, outdir):
    verts = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces)
    code_to_rgba = {g.code: _hex_to_rgba(g.color_hex) for g in groups}
    face_colors = np.empty((len(faces), 4), dtype=np.uint8)
    for g in groups:
        face_colors[g.faces] = code_to_rgba[g.code]
    # GLB carries per-vertex colours, so a vertex shared by two differently
    # coloured faces would be averaged (colour bleed at boundaries). Un-merge
    # vertices -- one independent triangle per face -- to keep colours crisp.
    pv_verts = verts[faces].reshape(-1, 3)
    pv_faces = np.arange(len(faces) * 3).reshape(-1, 3)
    pv_colors = np.repeat(face_colors, 3, axis=0)
    preview = trimesh.Trimesh(vertices=pv_verts, faces=pv_faces,
                              vertex_colors=pv_colors, process=False)
    path = Path(outdir) / f"{stem}_preview.glb"
    Path(outdir).mkdir(parents=True, exist_ok=True)
    preview.export(str(path))
    logger.info("Wrote colour preview %s", path)
    return path


def export_solid(mesh, codes, groups, stem, outdir, fmt,
                 resolution, smooth_iters, min_faces, arrange):
    """Volumetric mode: solid, watertight, mutually-fitting parts per colour."""
    import bambu_solid as bsolid
    group_codes = [g.code for g in groups]
    logger.info("Volumetric split @resolution=%d (voxelize + label + marching cubes "
                "+ repair; this can take a minute)...", resolution)
    result, pitch = bsolid.solid_color_split(mesh, list(codes), group_codes,
                                             resolution=resolution, smooth_iters=smooth_iters,
                                             min_faces=min_faces)
    out = Path(outdir); out.mkdir(parents=True, exist_ok=True)
    logger.info("voxel pitch ~%.3f (model units)", pitch)
    color_meshes = []
    for g in groups:
        bodies = result.get(g.code, [])
        if not bodies:
            logger.info("  %-7s: no solid bodies (skipped)", g.name); continue
        combined = trimesh.util.concatenate(bodies) if len(bodies) > 1 else bodies[0]
        combined.visual.face_colors = np.tile(_hex_to_rgba(g.color_hex),
                                              (len(combined.faces), 1)).astype(np.uint8)
        fn = out / f"{stem}_filament{g.extruder}_{g.name}_{g.color_hex.lstrip('#')}_solid.{fmt}"
        combined.export(str(fn))
        logger.info("  %-7s: %d bodies  %7d faces  watertight=%s  vol=%.1f  -> %s",
                    g.name, len(bodies), len(combined.faces), combined.is_watertight,
                    combined.volume, fn.name)
        color_meshes.append((g, combined))
    if arrange and color_meshes:
        _export_plate(color_meshes, stem, out)
    return color_meshes


def _export_plate(color_meshes, stem, outdir):
    """Drop each colour object to the bed and tile them on a plate -> .3mf + .glb."""
    import bambu_solid as bsolid
    dropped, footprints = [], []
    for g, m in color_meshes:
        mm = m.copy()
        mm.apply_translation([0, 0, -mm.bounds[0][2]])      # drop so min z = 0
        b = mm.bounds
        footprints.append((b[0][0], b[0][1], b[1][0], b[1][1]))
        dropped.append((g, mm))
    scene = trimesh.Scene()
    for (g, mm), (dx, dy) in zip(dropped, bsolid.grid_positions(footprints, gap=5.0)):
        mm = mm.copy(); mm.apply_translation([dx, dy, 0.0])
        scene.add_geometry(mm, geom_name=f"{g.name}_filament{g.extruder}")
    p3mf = Path(outdir) / f"{stem}_plate.3mf"
    pglb = Path(outdir) / f"{stem}_plate_preview.glb"
    scene.export(str(p3mf)); scene.export(str(pglb))
    logger.info("  plate: %d objects dropped to bed & arranged -> %s , %s",
                len(dropped), p3mf.name, pglb.name)


def main():
    parser = argparse.ArgumentParser(description="Split a Bambu/Orca multi-color 3MF by filament colour")
    parser.add_argument("input_file", help="Input 3MF file path")
    parser.add_argument("-o", "--output", default="output", help="Output directory")
    parser.add_argument("-f", "--format", default="stl", choices=["stl", "obj", "ply"],
                        help="Mesh export format (default: stl)")
    parser.add_argument("--info", action="store_true", help="Show colour info only; export nothing")
    parser.add_argument("--no-preview", action="store_true", help="Skip the colour preview .glb")
    parser.add_argument("--solid", action="store_true",
                        help="Volumetric mode: emit SOLID, watertight, mutually-fitting parts "
                             "(no slicer 'fix model' needed). Requires scikit-image + pymeshfix.")
    parser.add_argument("--resolution", type=int, default=300,
                        help="--solid voxel resolution along the longest axis "
                             "(default 300; higher = finer surface + bigger files). "
                             "EDT labelling makes even 400-500 take under a minute.")
    parser.add_argument("--smooth-iters", type=int, default=2,
                        help="--solid interior label-smoothing passes (default 2)")
    parser.add_argument("--min-faces", type=int, default=200,
                        help="--solid: drop bodies smaller than this many faces (artifact removal)")
    parser.add_argument("--no-arrange", action="store_true",
                        help="--solid: skip the combined plate-arranged 3MF")
    args = parser.parse_args()

    if not Path(args.input_file).exists():
        logger.error("Input file not found: %s", args.input_file)
        sys.exit(1)

    mesh, codes, palette, default_extruder = load_mesh_and_codes(args.input_file)
    groups = color_groups(codes, palette, default_extruder)
    total = len(codes)
    report(groups, palette, total)

    if args.info:
        return

    stem = Path(args.input_file).stem
    if args.solid:
        export_solid(mesh, codes, groups, stem, args.output, args.format,
                     args.resolution, args.smooth_iters, args.min_faces, not args.no_arrange)
        logger.info("Done (solid mode). Output in %s/", args.output)
        return

    export_splits(mesh, groups, stem, args.output, args.format)
    if not args.no_preview:
        export_preview(mesh, groups, stem, args.output)
    logger.info("Done. %d colour file(s) in %s/", len(groups), args.output)


if __name__ == "__main__":
    main()
