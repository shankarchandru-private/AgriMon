"""Turns a GenerationOutput (LLM slots or the developer seed) into capability.py + manifest."""

from __future__ import annotations

import hashlib

from agrimon.contracts import CapabilityManifest, GenerationOutput
from agrimon.evolution.templates import TEMPLATE_VERSION, assemble


def content_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def make_candidate(
    gen: GenerationOutput,
    capability_id: str,
    analysis_key: str,
    origin: str,
    version: str = "1.0.0",
    aliases: list[str] | None = None,
    source_request_id: str | None = None,
) -> tuple[str, CapabilityManifest]:
    classes = [c.model_dump() for c in gen.classes]
    rules = [r.model_dump() for r in gen.finding_rules]
    steps = [s.model_dump() for s in gen.next_steps]
    description = f"{gen.description} Formula: {gen.formula}."
    source = assemble(
        compute_values_source=gen.compute_values_source,
        description=description,
        required_bands=gen.required_bands,
        value_label=gen.value_label,
        value_unit=gen.value_unit,
        value_range=(gen.value_min, gen.value_max),
        parameters={},
        classes=classes,
        finding_rules=rules,
        next_steps=steps,
    )
    manifest = CapabilityManifest(
        id=capability_id,
        version=version,
        template_version=TEMPLATE_VERSION,
        analysis_key=analysis_key,
        aliases=aliases or [],
        name=gen.name,
        description=gen.description,
        required_bands=gen.required_bands,
        value_label=gen.value_label,
        value_unit=gen.value_unit,
        value_min=gen.value_min,
        value_max=gen.value_max,
        classes=classes,
        formula=gen.formula,
        citation=gen.citation,
        parameters={},
        finding_rules=rules,
        next_steps=steps,
        origin=origin,
        source_request_id=source_request_id,
    )
    return source, manifest
