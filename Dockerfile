# Image for ColorSplit3mf's Bambu/Orca-aware CLI (color_split_bambu.py).
# Surface mode needs only trimesh + numpy (lxml backs trimesh's 3MF loader,
# scipy/networkx back some mesh ops). Solid/volumetric mode (--solid) adds
# scikit-image (marching cubes) and pymeshfix (watertight repair). The heavy
# declared deps of the upstream project (open3d, scikit-learn, matplotlib,
# lib3mf) are unused on this path.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "trimesh>=3.9.0" \
    "numpy>=1.19.0" \
    "scipy>=1.5.0" \
    "networkx>=3.5.0" \
    "lxml>=6.0.0" \
    "scikit-image>=0.22" \
    "pymeshfix>=0.16"

WORKDIR /app
COPY bambu_paint.py bambu_solid.py color_split_bambu.py color_split_enhanced.py /app/

# HOME so libraries that touch a cache/config dir work under an arbitrary -u UID.
ENV HOME=/tmp

# Default to the improved Bambu/Orca-aware splitter.
ENTRYPOINT ["python", "color_split_bambu.py"]
