"""Synthetic probes and input variants used by the harness to test analytical behaviour.

constant.tif: every pixel the same mid-grey, so any per-pixel analysis must produce a uniform matrix.
masked.tif:   top-left quadrant is nodata (0 in all bands); the rest is a smooth pattern.
Variants of the real asset (horizontal flip, one band inverted) are written per evaluation to test
that the matrix is derived from the actual input and responds to it.
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


def _quiet():
    from rasterio.errors import NotGeoreferencedWarning

    ctx = warnings.catch_warnings()
    ctx.__enter__()
    warnings.simplefilter("ignore", NotGeoreferencedWarning)
    return ctx


def build_probes() -> None:
    import rasterio

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    constant = np.full((3, SIZE, SIZE), 128, dtype="uint8")
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    pattern = np.stack([40 + (xx * 150 // SIZE), 40 + (yy * 150 // SIZE), 40 + ((xx + yy) * 75 // SIZE)]).astype("uint8")
    r, c = masked_quadrant()
    pattern[:, :r, :c] = 0
    profile = dict(driver="GTiff", width=SIZE, height=SIZE, count=3, dtype="uint8")
    q = _quiet()
    try:
        with rasterio.open(PROBE_DIR / "constant.tif", "w", **profile) as ds:
            ds.write(constant)
        with rasterio.open(PROBE_DIR / "masked.tif", "w", nodata=0, **profile) as ds:
            ds.write(pattern)
    finally:
        q.__exit__(None, None, None)


def write_variant(source: Path, dest: Path, kind: str, band_index: int | None = None) -> Path:
    """Writes a lossless variant of an asset: 'flip' (left-right) or 'invert' (one band, 1-based)."""
    import rasterio

    q = _quiet()
    try:
        with rasterio.open(source) as ds:
            data = ds.read()
            nodata = ds.nodata
        if kind == "flip":
            data = data[:, :, ::-1]
        elif kind == "invert":
            info = np.iinfo(data.dtype) if np.issubdtype(data.dtype, np.integer) else None
            top = info.max if info else float(np.nanmax(data[band_index - 1]))
            data = data.copy()
            data[band_index - 1] = top - data[band_index - 1]
        else:
            raise ValueError(kind)
        dest.parent.mkdir(parents=True, exist_ok=True)
        profile = dict(driver="GTiff", width=data.shape[2], height=data.shape[1], count=data.shape[0], dtype=str(data.dtype))
        if nodata is not None:
            profile["nodata"] = nodata
        with rasterio.open(dest, "w", **profile) as out:
            out.write(np.ascontiguousarray(data))
    finally:
        q.__exit__(None, None, None)
    return dest
