"""Asks the LLM for the analytical computation and its analytical metadata. Nothing else.

It never sees the template's fixed code or the evaluation harness.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from agrimon.contracts import COLOR_MAPS, GenerationOutput, Intent, Scene

SYSTEM_PROMPT = f"""You write the analytical logic for ONE capability of a geospatial analytics platform that
answers a user's analytical question about a single raster image. The platform owns everything else: data
access, execution, aggregation into a matrix, statistics, zones, validation, visualization, persistence and
provenance. You provide only the analysis and the metadata that describes and interprets it.

Reply with a JSON object only, with exactly these keys:
  name, description, analysis_type, layer_name, method, citation, required_bands, value_label, value_unit,
  aggregation, color_map, classification, compute_source, interpret_source

compute_source: Python source defining exactly this function (private helpers named _like_this are allowed):
    def compute(bands, params):
        ...
        return <2-D numpy float array>        # or a dict, see below
  - bands: dict of read-only 2-D float arrays scaled 0-1, keyed by band name. params: dict (usually empty).
  - Return the per-pixel analytical raster (same shape as each band), or a dict:
      {{"values": raster,                                    # required
        "zones": {{"<snake_name>": boolean mask, ...}},       # OPTIONAL: only if the analysis naturally
                                                             #   defines spatial regions
        "metrics": {{"<snake_name>": {{"value": float, "unit": str, "description": str}}, ...}}}}  # OPTIONAL
  - Values are whatever the analysis produces: negative values, values above 1, any scale. Do not clip or
    rescale values for display. Do not invent value ranges or class thresholds that the question does not need.
  - Use np.nan where a value is undefined (for example a division by zero). Never raise for data reasons.
  - numpy is available as np and math as math. Write no import statements. Deterministic: no randomness.
  - Analytical logic only: no file, network, OS, process, environment or credential access; do not use open,
    eval, exec, getattr, setattr, globals, __dunder__ names, or numpy I/O (np.save, np.load, ...).

interpret_source: Python source defining exactly:
    def interpret(evidence):
        return {{"summary": str, "findings": [...], "next_steps": [...]}}
  - evidence is a dict computed by the platform from YOUR raster:
      evidence["asset"] = {{"id", "label", "date"}}; evidence["question"]; evidence["grid_size"] = {{"rows","cols"}}
      evidence["metrics"] = {{name: value}} with platform metrics matrix_mean, matrix_min, matrix_max,
        matrix_std, valid_cells, nodata_cells, plus your own metrics
      evidence["zones"] = list of {{"id" ("<name>-1" largest first), "name", "cell_count", "share_pct",
        "mean_value", "row_min", "row_max", "col_min", "col_max"}}; empty if you defined no zones or none were found
      evidence["classes"] = list of {{"id","label","cell_count","share_pct"}} (only for classified analyses)
  - findings: 1-6 items {{"id": "F1", "statement": str, "evidence": [metric names, zone ids or "class:<id>"]}}.
    Every number in the summary or a finding must be a value taken from evidence (format with e.g. :.3f).
    Never compute new numbers inside interpret (no sums, differences or percent conversions) and never type
    numbers yourself. Handle absent zones or metrics gracefully (check before indexing).
  - summary: 1-3 sentences that name evidence["asset"]["label"] and describe the actual result.
  - next_steps: 1-3 items {{"type": "follow_up_analysis" | "human_inspection", "description": str,
    "follows_from": "<finding id>"}}. Analytical follow-ups or human inspection only. Never prescribe
    agronomic actions (treatments, fertilizer, irrigation, spraying, rates, harvest, planting).

aggregation: how pixels reduce to a matrix cell: "mean" for continuous values (default), "median", "min",
  "max", or "mode" for classified (categorical) rasters.
classification: null unless classification is genuinely part of the question. If it is, compute must return
  integer class ids per pixel, aggregation must be "mode", and classification lists
  [{{"id": int, "label": str, "description": "the rule/threshold for this class"}}, ...] (2-8 classes).
color_map: one of {", ".join(COLOR_MAPS)} - pick the one that suits the analysis (for example greens for
  vegetation, blues for water/moisture, reds or ylorrd for heat/intensity, purples for other quantities).
analysis_type: short snake_case type, e.g. "vegetation_index", "band_ratio", "texture", "classification".
layer_name: short display name of the output layer. value_label/value_unit: what one matrix value means.
method: the formula or methodology in plain text. citation: a published reference (author, year, title) when
  the method is not self-evident and a reliable source exists; otherwise "".
required_bands: only bands the analysis actually uses (subset of the asset's bands); every one must matter.
name/description: if the analysis is an RGB proxy for a multispectral index, say so explicitly (for example
  "RGB vegetation proxy (Excess Green)"); never call it NDVI or another index whose bands are missing.
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
            "asset": {"id": scene.id, "label": scene.label, "sensor": scene.sensor, "bands": scene.band_names,
                      "width": scene.width, "height": scene.height,
                      "georeferenced": scene.crs is not None, "resolution_m": scene.resolution_m},
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
