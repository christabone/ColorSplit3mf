#!/usr/bin/env python3
"""Paint-color parsing and filament-color resolution for Bambu/Orca 3MF files.

Why this exists
---------------
Bambu Studio / OrcaSlicer store per-triangle MMU "color painting" in the
``paint_color`` attribute of each ``<triangle>`` in ``3D/Objects/*.model``.
The value is a **hexadecimal** code, and for a whole (non-subdivided) facet the
painted filament is::

    extruder = int(paint_color, 16) >> 2          # 1-based

(e.g. ``"8"`` -> 2, ``"0C"`` -> 3). Unpainted triangles carry no attribute and
print with the object's default extruder.

The original tool parsed ``paint_color`` with the regex ``paint_color="(\\d+)"``,
which only matches decimal digits. Any code containing a hex letter (``0C``,
``A``, ...) matched neither that pattern nor the "no paint" pattern, so those
triangles were silently dropped -- collapsing a multi-color model into far
fewer groups. This module fixes the parsing and resolves each group to the real
filament colour from ``Metadata/project_settings.config``.

This module is pure (stdlib only) so it can be unit-tested without trimesh.
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Capture v1/v2/v3 and the remainder of the tag (which may hold paint_color).
_TRIANGLE_RE = re.compile(r'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"([^>]*)>')
_PAINT_RE = re.compile(r'paint_color="([0-9A-Fa-f]+)"')

# Common filament hex -> friendly name, used only for tidy output filenames.
_COLOR_NAMES = {
    "#FFFFFF": "white", "#000000": "black", "#FF0000": "red", "#00FF00": "green",
    "#0000FF": "blue", "#FFFF00": "yellow", "#FF80C0": "pink", "#FFA500": "orange",
    "#808080": "gray", "#A0A0A0": "gray",
}


def decode_paint_color(code: Optional[str]) -> int:
    """Decode a ``paint_color`` code to a 1-based extruder/filament index.

    Returns 0 for unpainted (empty/None), meaning "use the object default".
    Handles the whole-facet (non-subdivided) case, which is what Bambu MMU
    color painting produces for solid-colored regions.
    """
    if not code:
        return 0
    return int(code, 16) >> 2


def extract_paint_groups(model_xml: str) -> Dict[str, List[int]]:
    """Group triangle (face) indices by raw ``paint_color`` code.

    Faces are numbered 0-based in document order (matching how trimesh loads the
    mesh). Unpainted triangles are grouped under the empty-string key. Every
    triangle lands in exactly one group -- nothing is dropped.
    """
    groups: Dict[str, List[int]] = {}
    for face_idx, m in enumerate(_TRIANGLE_RE.finditer(model_xml)):
        paint = _PAINT_RE.search(m.group(4))
        code = paint.group(1).upper() if paint else ""
        groups.setdefault(code, []).append(face_idx)
    return groups


def color_name(color_hex: str) -> str:
    """Friendly lowercase name for a hex colour, falling back to the bare hex."""
    return _COLOR_NAMES.get(color_hex.upper(), color_hex.lstrip("#").lower())


def _filament_color(palette: List[str], extruder: int) -> str:
    """Resolve a 1-based extruder index to a hex colour from the palette."""
    if 1 <= extruder <= len(palette) and palette[extruder - 1]:
        return palette[extruder - 1]
    return "#808080"  # unknown -> neutral gray


@dataclass
class ColorGroup:
    """One printable color: its paint code, resolved extruder, hex colour and faces."""
    code: str
    extruder: int
    color_hex: str
    faces: List[int] = field(default_factory=list)
    count: Optional[int] = None

    @property
    def face_count(self) -> int:
        return self.count if self.count is not None else len(self.faces)

    @property
    def name(self) -> str:
        return color_name(self.color_hex)


def assign_colors(groups: Dict[str, List[int]], filament_colors: List[str],
                  default_extruder: int = 1) -> List[ColorGroup]:
    """Map each paint-code group to its real extruder + filament colour."""
    out: List[ColorGroup] = []
    for code, faces in groups.items():
        decoded = decode_paint_color(code)
        extruder = default_extruder if decoded == 0 else decoded
        out.append(ColorGroup(code=code, extruder=extruder,
                              color_hex=_filament_color(filament_colors, extruder),
                              faces=list(faces)))
    out.sort(key=lambda g: g.extruder)
    return out


# --- 3MF package helpers -------------------------------------------------

def read_filament_colors(z: zipfile.ZipFile) -> List[str]:
    """Read the filament palette (hex strings) from project_settings.config."""
    try:
        cfg = json.loads(z.read("Metadata/project_settings.config"))
    except (KeyError, ValueError):
        return []
    return cfg.get("filament_colour") or cfg.get("filament_multi_colour") or []


def read_default_extruder(z: zipfile.ZipFile) -> int:
    """Read the object's default extruder from model_settings.config (default 1)."""
    try:
        txt = z.read("Metadata/model_settings.config").decode("utf-8", "replace")
    except KeyError:
        return 1
    m = re.search(r'key="extruder"\s+value="(\d+)"', txt)
    return int(m.group(1)) if m else 1


def object_model_names(z: zipfile.ZipFile) -> List[str]:
    """All mesh model parts in the package (the files that carry paint data)."""
    return [n for n in z.namelist() if n.endswith(".model") and "Objects" in n]


@dataclass
class Analysis:
    total_triangles: int
    groups: List[ColorGroup]
    palette: List[str]


def analyze_3mf(path: str) -> Analysis:
    """Parse a 3MF and report color groups + resolved colours, without trimesh.

    Aggregates paint codes across every object model part. Useful for ``--info``
    and for regression testing.
    """
    with zipfile.ZipFile(path) as z:
        palette = read_filament_colors(z)
        default_ex = read_default_extruder(z)
        merged: Dict[str, int] = {}
        total = 0
        for name in object_model_names(z):
            xml = z.read(name).decode("utf-8", "replace")
            for code, faces in extract_paint_groups(xml).items():
                merged[code] = merged.get(code, 0) + len(faces)
                total += len(faces)

    groups: List[ColorGroup] = []
    for code, cnt in merged.items():
        decoded = decode_paint_color(code)
        extruder = default_ex if decoded == 0 else decoded
        groups.append(ColorGroup(code=code, extruder=extruder,
                                 color_hex=_filament_color(palette, extruder),
                                 count=cnt))
    groups.sort(key=lambda g: g.extruder)
    return Analysis(total_triangles=total, groups=groups, palette=palette)
