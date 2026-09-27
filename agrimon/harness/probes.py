"""Synthetic probe rasters behind the probe-behaviour check.

constant.tif: every pixel the same mid-grey, so any per-pixel analysis must yield one class.
masked.tif:   top-left quadrant is nodata (0 in all bands); the rest is a smooth pattern.
Both are 96x96, 3-band uint8, not georeferenced. Rebuilt by scripts/prepare_assets.py.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np

from agrimon.contracts import BandInfo, Scene

PROBE_DIR = Path(__file__).resolve().parent / "probes"
SIZE = 96
_BANDS = [BandInfo(name=n, index=i + 1, scale=1 / 255) for i, n in enumerate(["red", "green", "blue"])]


def probe_scenes() -> dict[str, tuple[Scene, Path]]:
    common = dict(sensor="synthetic probe", source="agrimon harness", width=SIZE, height=SIZE, dtype="uint8", bands=_BANDS)
    return {
        "constant": (Scene(id="probe_constant", label="Probe: constant", file="constant.tif", **common),
                     PROBE_DIR / "constant.tif"),
        "masked": (Scene(id="probe_masked", label="Probe: masked", file="masked.tif", nodata=0, **common),
                   PROBE_DIR / "masked.tif"),
    }


def masked_quadrant() -> tuple[int, int]:
    """Pixel rows and cols (exclusive) of the nodata quadrant."""
    return SIZE // 2, SIZE // 2


def build_probes() -> None:
    import rasterio
    from rasterio.errors import NotGeoreferencedWarning

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    constant = np.full((3, SIZE, SIZE), 128, dtype="uint8")
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    pattern = np.stack([
        40 + (xx * 150 // SIZE),
        40 + (yy * 150 // SIZE),
        40 + ((xx + yy) * 75 // SIZE),
    ]).astype("uint8")
    r, c = masked_quadrant()
    pattern[:, :r, :c] = 0
    profile = dict(driver="GTiff", width=SIZE, height=SIZE, count=3, dtype="uint8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(PROBE_DIR / "constant.tif", "w", **profile) as ds:
            ds.write(constant)
        with rasterio.open(PROBE_DIR / "masked.tif", "w", nodata=0, **profile) as ds:
            ds.write(pattern)
