"""Asks the LLM for the three template slots. It never sees the template's fixed code or the harness."""

from __future__ import annotations

import json

from pydantic import ValidationError

from agrimon.contracts import GenerationOutput, Intent, Scene

SYSTEM_PROMPT = """You write the analytical logic for ONE capability of a geospatial analytics system that
analyzes a single true-color raster image. Reply with a JSON object only, with exactly these keys:
name, description, formula, citation, required_bands, value_label, value_unit, value_min, value_max,
classes, compute_values_source, finding_rules, next_steps.

The execution interface is fixed and not yours. A fixed template loads the bands, calls your
compute_values(bands, params), aggregates the result to a grid, classifies cells with your classes,
finds zones, computes metrics, and renders your finding rules and the summary.

compute_values_source: Python source of exactly one function, and nothing else:
    def compute_values(bands, params):
        ...
        return <2-D numpy float array with the same shape as each band>
  - bands is a dict of 2-D float arrays scaled to 0-1, keyed by band name.
  - numpy is available as np and math as math. Write no import statements.
  - No file, network or OS access. Do not use open, eval, exec, compile, getattr, setattr, globals,
    locals, input, __import__ or any __dunder__ name.
  - Where a value is undefined (for example a division by zero) return np.nan for that pixel; never raise.
  - Deterministic: no randomness.

value_min, value_max: the theoretical range of compute_values.
classes: 3 to 6 contiguous classes covering [value_min, value_max] with no gaps or overlaps:
  ids 0..n-1 in ascending value order, first min == value_min, each max == the next min,
  last max == value_max. Colors are "#RRGGBB". Labels are short words without numbers.
finding_rules: 2 to 4 objects {"id": "F1", "template": "..."}. Templates reference only these placeholders:
  {metric.mean_value} {metric.min_value} {metric.max_value} {metric.valid_cells} {metric.nodata_cells}
  {metric.class_<id>_share_pct}   (for example {metric.class_0_share_pct})
  {zone.high-1.label} {zone.high-1.share_pct} {zone.high-1.mean_value} {zone.high-1.cell_count}
  (zones high-1..high-3 are the largest connected regions of the highest class present; low-1..low-3 of the lowest)
  Every number in a finding must come from a placeholder: never type numbers into the text yourself.
next_steps: 1 to 3 objects {"type": "follow_up_analysis" or "human_inspection", "description": "...",
  "follows_from": "<finding id>"}. They propose further analysis or human inspection only. Never prescribe
  treatments, inputs, rates, spraying, irrigation, fertilizer or any other management action.
formula: the formula in plain text. citation: a published source for the index or method (author, year, title).
name and description: if the analysis is an RGB proxy for a multispectral index, say so explicitly
(for example "RGB vegetation proxy (Excess Green)"); never call it NDVI or another multispectral index.
"""


class GenerationError(RuntimeError):
    pass


class Generator:
    def __init__(self, llm):
        self.llm = llm

    def generate(self, intent: Intent, scene: Scene, feedback: str | None = None) -> GenerationOutput:
        if self.llm is None:
            raise GenerationError("no OpenAI key configured: add OPENAI_API_KEY to .env and restart")
        payload = {
            "question": intent.question,
            "analysis_key": intent.analysis_key,
            "analysis_description": intent.description,
            "assumptions": intent.assumptions,
            "scene": {"label": scene.label, "sensor": scene.sensor, "bands": scene.band_names},
            "required_bands_must_be_subset_of": scene.band_names,
        }
        user = json.dumps(payload, indent=2)
        if feedback:
            user += f"\n\nYour previous candidate was rejected. Fix these problems:\n{feedback}"
        try:
            raw = self.llm.complete_json("generation", SYSTEM_PROMPT, user)
        except Exception as exc:
            raise GenerationError(f"generation call failed: {exc}") from exc
        try:
            return GenerationOutput.model_validate(raw)
        except ValidationError as exc:
            lines = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:6]]
            raise GenerationError("generation output invalid: " + "; ".join(lines)) from exc
