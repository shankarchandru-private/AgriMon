"""Developer tool: builds assets/catalog.json from the files in assets/scenes/.

Existing labels, sensors, sources and dates in catalog.json are preserved; size, dtype,
CRS and bands are read from each file. Also (re)builds the harness probe rasters.

Usage:  python scripts/prepare_assets.py
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import rasterio  # noqa: E402
from rasterio.errors import NotGeoreferencedWarning  # noqa: E402

from agrimon.contracts import Catalog  # noqa: E402

EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
RGB = ["red", "green", "blue"]


def main() -> None:
    catalog_path = ROOT / "assets" / "catalog.json"
    existing = {}
    if catalog_path.exists():
        existing = {s["file"]: s for s in json.loads(catalog_path.read_text())["scenes"]}

    scenes = []
    for path in sorted((ROOT / "assets" / "scenes").iterdir()):
        if path.suffix.lower() not in EXTENSIONS:
            continue
        rel = f"scenes/{path.name}"
        prev = existing.get(rel, {})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(path) as ds:
                if ds.count < 3:
                    print(f"skip {rel}: needs at least 3 bands for RGB")
                    continue
                scale = 1 / 255 if ds.dtypes[0] == "uint8" else 1 / 65535 if ds.dtypes[0] == "uint16" else 1.0
                crs = ds.crs.to_string() if ds.crs else None
                res = abs(ds.transform.a) if ds.crs and ds.crs.is_projected else None
                scenes.append({
                    "id": prev.get("id", path.stem.lower()),
                    "label": prev.get("label", path.stem.replace("_", " ").title()),
                    "file": rel,
                    "sensor": prev.get("sensor", "True-color RGB image"),
                    "source": prev.get("source", "unspecified"),
                    "acquisition_date": prev.get("acquisition_date"),
                    "crs": crs,
                    "width": ds.width,
                    "height": ds.height,
                    "resolution_m": prev.get("resolution_m", res),
                    "dtype": ds.dtypes[0],
                    "nodata": ds.nodata,
                    "bands": prev.get("bands") or [
                        {"name": RGB[i], "index": i + 1, "scale": scale} for i in range(3)
                    ],
                })
    Catalog.model_validate({"scenes": scenes})  # fail loudly on anything malformed
    catalog_path.write_text(json.dumps({"catalog_version": "catalog/1", "scenes": scenes}, indent=2) + "\n")
    print(f"wrote {catalog_path.relative_to(ROOT)} with {len(scenes)} scene(s)")

    from agrimon.harness.probes import build_probes

    build_probes()
    print("rebuilt harness probe rasters")


if __name__ == "__main__":
    main()
