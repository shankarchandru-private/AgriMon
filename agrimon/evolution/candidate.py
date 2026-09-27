"""Turns a GenerationOutput (LLM or the developer seed) into capability.py + manifest, and persists it.

The content hash is always taken from the persisted file's bytes, never from the in-memory string,
so provenance holds on every platform (for example Windows, where text mode rewrites line endings).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from agrimon.contracts import CapabilityManifest, GenerationOutput
from agrimon.evolution.templates import TEMPLATE_VERSION, assemble


def file_hash(path: Path) -> str:
    """SHA-256 of the persisted capability file bytes: the root of the provenance chain."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def persist_source(path: Path, source: str) -> str:
    """Writes the capability as UTF-8 with LF line endings (byte-exact on every OS) and returns its hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source.encode("utf-8"))
    return file_hash(path)


def make_candidate(
    gen: GenerationOutput,
    capability_id: str,
    analysis_key: str,
    origin: str,
    version: str = "1.0.0",
    aliases: list[str] | None = None,
    source_request_id: str | None = None,
) -> tuple[str, CapabilityManifest]:
    classification = [c.model_dump() for c in gen.classification] if gen.classification is not None else None
    source = assemble(
        compute_source=gen.compute_source,
        interpret_source=gen.interpret_source,
        layer_name=gen.layer_name,
        analysis_type=gen.analysis_type,
        description=f"{gen.description} Method: {gen.method}",
        required_bands=gen.required_bands,
        value_label=gen.value_label,
        value_unit=gen.value_unit,
        aggregation=gen.aggregation,
        color_map=gen.color_map,
        classification=classification,
        parameters={},
    )
    manifest = CapabilityManifest(
        id=capability_id,
        version=version,
        template_version=TEMPLATE_VERSION,
        analysis_key=analysis_key,
        aliases=aliases or [],
        name=gen.name,
        description=gen.description,
        analysis_type=gen.analysis_type,
        layer_name=gen.layer_name,
        required_bands=gen.required_bands,
        value_label=gen.value_label,
        value_unit=gen.value_unit,
        aggregation=gen.aggregation,
        color_map=gen.color_map,
        classification=gen.classification,
        method=gen.method,
        citation=gen.citation,
        parameters={},
        origin=origin,
        source_request_id=source_request_id,
    )
    return source, manifest
