#!/usr/bin/env python3
"""Volumetric color segmentation: turn a surface-painted solid into one
*solid, watertight* mesh per colour, with parts that mate (for gluing).

Pipeline (solid_color_split):
  1. voxelize the solid + fill its interior (robust even if not perfectly closed)
  2. label every interior voxel by its nearest painted-surface colour (KDTree)
  3. majority-smooth the label field (kills interior noise that otherwise
     fragments each colour into hundreds of pieces)
  4. marching cubes per colour -> watertight solid bodies; adjacent colours
     share the voxel boundary so the parts fit together
  5. orient outward (fix_normals); pymeshfix only as a fallback for the rare
     non-watertight body (blanket repair destroys volume)

numpy + scipy are required; trimesh/skimage/pymeshfix are imported lazily inside
the heavy functions so the lean (surface-mode) image doesn't need them.
"""
import math
import numpy as np
from scipy import ndimage


def smooth_labels(lab, filled, n_labels, iters=2):
    """Majority-smooth an integer label grid (labels 1..n_labels; 0 = empty).

    Each pass replaces every filled voxel with the most common label in its
    3x3x3 neighbourhood, removing isolated interior pockets while keeping the
    partition exact (every filled voxel keeps a label, empties stay 0).
    """
    out = lab.astype(np.int32)
    for _ in range(iters):
        counts = np.stack([ndimage.uniform_filter((out == k + 1).astype(np.float32), size=3)
                           for k in range(n_labels)])
        out = np.where(filled, counts.argmax(0) + 1, 0).astype(np.int32)
    return out


def grid_positions(footprints, gap=2.0):
    """Translations to lay AABB footprints out in a non-overlapping grid.

    footprints: list of (min_x, min_y, max_x, max_y). Returns a list of
    (dx, dy) translations that move each footprint into a near-square grid of
    uniform cells (sized to the largest footprint + gap), centred per cell.
    """
    fps = [tuple(map(float, fp)) for fp in footprints]
    n = len(fps)
    if n == 0:
        return []
    cols = math.ceil(math.sqrt(n))
    cell_w = max(mxx - mnx for mnx, mny, mxx, mxy in fps) + gap
    cell_d = max(mxy - mny for mnx, mny, mxx, mxy in fps) + gap
    trans = []
    for i, (mnx, mny, mxx, mxy) in enumerate(fps):
        r, c = divmod(i, cols)
        cur_cx, cur_cy = (mnx + mxx) / 2.0, (mny + mxy) / 2.0
        trans.append((c * cell_w - cur_cx, r * cell_d - cur_cy))
    return trans


def _repair_component(c):
    """Return a watertight, outward-oriented version of one MC component."""
    import trimesh
    c.merge_vertices()
    trimesh.repair.fix_normals(c)
    if not c.is_watertight:
        import pymeshfix
        mf = pymeshfix.MeshFix(np.asarray(c.vertices), np.asarray(c.faces, np.int32))
        mf.repair(remove_smallest_components=False)
        c = trimesh.Trimesh(mf.points, mf.faces, process=True)
        trimesh.repair.fix_normals(c)
    if c.volume < 0:
        c.invert()
    return c


def solid_color_split(mesh, face_codes, group_codes,
                      resolution=250, smooth_iters=2, min_faces=200):
    """Segment a solid mesh into watertight solid bodies per colour.

    mesh:        trimesh.Trimesh (the original solid)
    face_codes:  per-face paint code (len == len(mesh.faces))
    group_codes: distinct codes in colour-group order
    Returns (result, pitch) where result maps code -> list of watertight bodies
    (trimesh.Trimesh) in the mesh's original coordinate frame.
    """
    import trimesh
    from scipy.spatial import cKDTree
    from skimage import measure

    V = np.asarray(mesh.vertices)
    F = np.asarray(mesh.faces)
    cent = V[F].mean(axis=1)
    c2l = {code: i + 1 for i, code in enumerate(group_codes)}
    flab = np.array([c2l[c] for c in face_codes], np.int32)

    pitch = float((V.max(0) - V.min(0)).max()) / resolution
    vg = mesh.voxelized(pitch)
    filled = ndimage.binary_fill_holes(vg.matrix)

    occ = np.argwhere(filled)
    occ_world = trimesh.transform_points(occ.astype(np.float64), vg.transform)
    _, nn = cKDTree(cent).query(occ_world, k=1, workers=-1)
    lab = np.zeros(filled.shape, np.int32)
    lab[occ[:, 0], occ[:, 1], occ[:, 2]] = flab[nn]
    lab = smooth_labels(lab, filled, len(group_codes), smooth_iters)

    result = {}
    for code in group_codes:
        k = c2l[code]
        mask = np.pad((lab == k).astype(np.float32), 1)
        if mask.sum() == 0:
            result[code] = []
            continue
        v, f, _, _ = measure.marching_cubes(mask, level=0.5)
        world = trimesh.transform_points(v - 1.0, vg.transform)
        m = trimesh.Trimesh(vertices=world, faces=f, process=False)
        bodies = [_repair_component(c) for c in m.split(only_watertight=False)
                  if len(c.faces) >= min_faces]
        result[code] = bodies
    return result, pitch
