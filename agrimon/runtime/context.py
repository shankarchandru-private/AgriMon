"""Builds the Context a capability receives: the selected asset, its bands and size, request metadata."""

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
    question: str = "",
) -> Context:
    """content_hash must be the SHA-256 of the persisted capability file (see evolution.candidate.file_hash)."""
    return Context(
        request_id=request_id,
        run_id=run_id,
        mode=mode,
        question=question,
        analysis_key=manifest.analysis_key,
        asset_id=scene.id,
        asset_label=scene.label,
        asset_date=scene.date_text,
        asset_path=str(scene_file or scene_path(settings, scene)),
        asset_width=scene.width,
        asset_height=scene.height,
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
