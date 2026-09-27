"""Reads assets/catalog.json and checks every declared scene against its file."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from agrimon.config import Settings
from agrimon.contracts import Catalog, Scene


def load_catalog(settings: Settings) -> Catalog:
    data = json.loads(settings.catalog_path.read_text(encoding="utf-8"))
    return Catalog.model_validate(data)


def scene_path(settings: Settings, scene: Scene) -> Path:
    return (settings.assets_dir / scene.file).resolve()


def validate_catalog(settings: Settings, catalog: Catalog) -> list[str]:
    """Returns a list of problems; empty means every scene is usable."""
    import rasterio
    from rasterio.errors import NotGeoreferencedWarning

    problems: list[str] = []
    if not catalog.scenes:
        problems.append("catalog has no scenes")
    has_rgb = False
    for scene in catalog.scenes:
        path = scene_path(settings, scene)
        if not path.exists():
            problems.append(f"{scene.id}: file not found: {scene.file}")
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", NotGeoreferencedWarning)
                with rasterio.open(path) as ds:
                    if (ds.width, ds.height) != (scene.width, scene.height):
                        problems.append(f"{scene.id}: size {ds.width}x{ds.height} differs from catalog")
                    for band in scene.bands:
                        if band.index > ds.count:
                            problems.append(f"{scene.id}: band {band.name} index {band.index} > {ds.count}")
                    if ds.dtypes[0] != scene.dtype:
                        problems.append(f"{scene.id}: dtype {ds.dtypes[0]} differs from catalog {scene.dtype}")
        except Exception as exc:  # unreadable file
            problems.append(f"{scene.id}: cannot open: {exc}")
        if {"red", "green", "blue"} <= set(scene.band_names):
            has_rgb = True
    if catalog.scenes and not has_rgb:
        problems.append("catalog needs at least one RGB-compatible scene")
    return problems
