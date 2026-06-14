# Lean image for ColorSplit3mf's CLI (color_split_enhanced.py).
# The CLI only imports numpy + trimesh directly; lxml backs trimesh's 3MF
# loader, and scipy/networkx back some trimesh mesh ops. The heavy declared
# deps (open3d, scikit-learn, matplotlib, lib3mf) are unused on this path.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "trimesh>=3.9.0" \
    "numpy>=1.19.0" \
    "scipy>=1.5.0" \
    "networkx>=3.5.0" \
    "lxml>=6.0.0"

WORKDIR /app
COPY bambu_paint.py color_split_bambu.py color_split_enhanced.py /app/

# HOME so libraries that touch a cache/config dir work under an arbitrary -u UID.
ENV HOME=/tmp

# Default to the improved Bambu/Orca-aware splitter.
ENTRYPOINT ["python", "color_split_bambu.py"]
