# ColorSplit Enhanced

Split 3MF files by paint color/material into separate components.

> **Bambu/Orca users:** see **[`color_split_bambu.py`](#bambuorca-color-accurate-splitter-new)** below — it
> fixes a bug where hex paint codes were silently dropped, and labels each
> output with its real filament colour. It is the recommended entry point and
> the default in the Docker image.

## Features

- Extract paint color information from 3MF files
- Split multi-color models into individual components
- Export as STL, OBJ, or PLY files
- Command line and programmatic API

### Visual Example

In this example we use a Makerworld remix of
- https://github.com/DrLex0/print3D-hinged-locked-treasure-chest
- https://makerworld.com/en/models/910440-hinged-locked-treasure-chest#profileId-1490628

![Multi-color 3MF Model](content/before.png)

The Makerworld version is a .3mf painted in Bambu Studio
Which is what we want.

![Separated Components A](content/after1.png)
![Separated Components B](content/after2.png)

*The tool automatically detects paint colors in 3MF files and creates separate files for each color group, making it easy to print different parts in different colors or materials.*

## Installation

```bash
uv pip install .
```

## Quick Start

```bash
# Split a 3MF file by color
python color_split_enhanced.py Hinged-Locked-Chest_MultiColor.3mf

# Show color info only
python color_split_enhanced.py input.3mf --info

# Custom output
python color_split_enhanced.py input.3mf -o my_output -f obj
```

## Programmatic Usage

```python
from color_split_enhanced import EnhancedColorSplitter

splitter = EnhancedColorSplitter("input.3mf")
splitter.load_3mf()
splitter.export_split_meshes("output", "stl")
```

## Arguments

- `input_file`: 3MF file to process
- `-o, --output`: Output directory (default: output)
- `-f, --format`: Format: stl, obj, ply (default: stl)
- `--info`: Show info only, don't export

## Output

Files named: `{original_name}_{color_key}.{format}`

Example: `Hinged-Locked-Chest_MultiColor_paint_color_1.stl`

## Dependencies

- trimesh, numpy, matplotlib, open3d

---

## Bambu/Orca color-accurate splitter (NEW)

`color_split_bambu.py` is a focused, dependency-light splitter for 3MF files
painted in **Bambu Studio / OrcaSlicer**. It correctly handles per-triangle MMU
color painting and resolves each group to its real filament colour.

### Why it exists — the bug it fixes

Bambu/Orca store painting in the `paint_color` attribute of each `<triangle>`,
and the value is **hexadecimal**. The original `color_split_enhanced.py` matched
it with `paint_color="(\d+)"` (decimal only). Any code containing a hex letter
(e.g. `0C`) matched *neither* that pattern nor the "no paint" pattern, so those
triangles were **silently dropped** — collapsing a multi-color model into too
few groups.

On a real 4-filament bee model, the original tool kept 862,130 of 1,498,890
triangles and reported 2 groups; **636,760 triangles (every `0C`/black face)
just disappeared.** This tool keeps all of them and reports the correct 3 groups.

### How `paint_color` is decoded

For a whole (non-subdivided) facet:

```
extruder = int(paint_color, 16) >> 2      # 1-based; unpainted -> object default
```

e.g. `"8"` → filament 2, `"0C"` → filament 3. Filament colours are read from
`Metadata/project_settings.config` (`filament_colour`), and the object's default
extruder from `Metadata/model_settings.config`.

> Scope: handles solid-colour (whole-facet) painting, which covers typical MMU
> models. Partially-painted facets (a triangle split between colours) are
> assigned by their top-level code rather than re-tessellated.

### Usage

```bash
# Show colour breakdown only (no files written)
python color_split_bambu.py model.3mf --info

# Split into one STL per filament colour + a colour preview
python color_split_bambu.py model.3mf -o output -f stl
```

Outputs are named by colour, e.g. `model_filament2_yellow_FFFF00.stl`, plus a
`model_preview.glb` tinted with the real filament colours so you can confirm the
split before printing. `--info` also reports palette colours that were defined
but never actually painted.

### Run with Docker (no local Python needed)

```bash
docker build -t colorsplit3mf .

# mount the folder with your .3mf as /data and an output folder as /out
docker run --rm -u "$(id -u):$(id -g)" \
  -v "$PWD":/data -v "$PWD/output":/out \
  colorsplit3mf "/data/model.3mf" -o /out -f stl
```

The image is `python:3.12-slim` plus `trimesh`, `numpy`, `scipy`, `networkx`,
`lxml` (no `open3d`), so it stays small and builds in seconds.

### Tests

```bash
python -m unittest discover -s tests
# optional regression against a local sample:
SAMPLE_3MF=/path/to/model.3mf python -m unittest discover -s tests
```
