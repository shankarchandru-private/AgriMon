"""Builds the Context a capability receives."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agrimon.catalog import scene_path
from agrimon.config import Settings
from agrimon.contracts import BandRef, CapabilityManifest, Context, Scene


def build_context(
    settings: Settings,
    scene: Scene,
    manifest: CapabilityManifest,
    content_hash: str,
    mode: str,
    request_id: str,
    run_id: str,
    output_dir: Path,
    parameters: dict[str, Any] | None = None,
    scene_file: Path | None = None,
) -> Context:
    return Context(
        request_id=request_id,
        run_id=run_id,
        mode=mode,
        scene_id=scene.id,
        scene_label=scene.label,
        scene_date=scene.date_text,
        scene_path=str(scene_file or scene_path(settings, scene)),
        bands=[BandRef(name=b.name, index=b.index, scale=b.scale) for b in scene.bands],
        nodata=scene.nodata,
        resolution_m=scene.resolution_m,
        grid_rows=settings.grid.rows,
        grid_cols=settings.grid.cols,
        parameters=parameters or {},
        output_dir=str(output_dir),
        capability_id=manifest.id,
        capability_version=manifest.version,
        content_hash=content_hash,
        template_version=manifest.template_version,
        config_version=settings.config_version,
    )
