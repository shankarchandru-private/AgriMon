"""The fixed capability template (version 2).

Every capability, seed or generated, is assembled here:
  fixed header  | SLOT 1: analytical code  | SLOT 2: analytical metadata  | fixed footer
The footer owns the execution interface execute(context) -> ToolResult and every platform
concern (data access, aggregation, statistics, zones, validation, provenance). SLOT 1 holds only
compute(bands, params) and interpret(evidence), plus optional private helpers named _like_this.
Admission checks the fixed parts byte-for-byte.
"""

from __future__ import annotations

import pprint
from typing import Any, Optional

TEMPLATE_VERSION = "2"

SLOT_NAMES = ("SLOT 1", "SLOT 2")

HEADER = '''# AgriMon capability, assembled from the fixed capability template.
# Only the two SLOT sections differ between capabilities; everything else is
# checked byte-for-byte at admission.
# template-version: 2
import math

import numpy as np

from agrimon import sdk

'''

FOOTER = '''

def execute(context):
    """Fixed interface: execute(context) -> ToolResult. The platform owns everything in here."""
    started_at = sdk.now()
    bands, nodata = sdk.load_bands(context, REQUIRED_BANDS)
    params = dict(PARAMETERS)
    params.update(context.parameters)
    output = sdk.analysis_output(compute(bands, params), nodata.shape)
    grid = sdk.to_matrix(output["values"], nodata, context.grid_rows, context.grid_cols, AGGREGATION)
    metrics = sdk.matrix_metrics(grid, VALUE_UNIT) + output["metrics"]
    zones = sdk.zones_from_masks(output["zones"], grid, context)
    classification = sdk.class_summary(grid, CLASSIFICATION)
    evidence = sdk.evidence(context, grid, metrics, zones, classification, VALUE_LABEL, VALUE_UNIT)
    interpretation = sdk.interpretation(interpret(evidence))
    meta = {"layer_name": LAYER_NAME, "analysis_type": ANALYSIS_TYPE, "description": DESCRIPTION,
            "color_map": COLOR_MAP}
    return sdk.build_result(context, meta, grid, metrics, zones, classification, interpretation, started_at)
'''

SLOT2_NAMES = ("LAYER_NAME", "ANALYSIS_TYPE", "DESCRIPTION", "REQUIRED_BANDS", "VALUE_LABEL", "VALUE_UNIT",
               "AGGREGATION", "COLOR_MAP", "CLASSIFICATION", "PARAMETERS")


def _begin(slot: str) -> str:
    return f"# ==== BEGIN {slot} ====\n"


def _end(slot: str) -> str:
    return f"# ==== END {slot} ====\n"


def _literal(name: str, value) -> str:
    return f"{name} = {pprint.pformat(value, width=100, sort_dicts=False)}\n"


def assemble(
    compute_source: str,
    interpret_source: str,
    layer_name: str,
    analysis_type: str,
    description: str,
    required_bands: list[str],
    value_label: str,
    value_unit: str,
    aggregation: str,
    color_map: str,
    classification: Optional[list[dict]],
    parameters: dict[str, Any],
) -> str:
    """Builds capability.py. SLOT 2 is written as Python literals by this trusted code."""
    slot1 = compute_source.strip("\n") + "\n\n\n" + interpret_source.strip("\n") + "\n"
    slot2 = "".join(
        _literal(n, v)
        for n, v in (
            ("LAYER_NAME", layer_name),
            ("ANALYSIS_TYPE", analysis_type),
            ("DESCRIPTION", description),
            ("REQUIRED_BANDS", list(required_bands)),
            ("VALUE_LABEL", value_label),
            ("VALUE_UNIT", value_unit),
            ("AGGREGATION", aggregation),
            ("COLOR_MAP", color_map),
            ("CLASSIFICATION", [dict(c) for c in classification] if classification is not None else None),
            ("PARAMETERS", dict(parameters)),
        )
    )
    return (HEADER + _begin("SLOT 1") + slot1 + _end("SLOT 1") + "\n"
            + _begin("SLOT 2") + slot2 + _end("SLOT 2") + FOOTER)


def split(source: str) -> tuple[str, dict[str, str]]:
    """Returns (fixed_text, {slot: body}). Raises ValueError if markers are missing or out of order."""
    source = source.replace("\r\n", "\n")
    fixed_parts: list[str] = []
    slots: dict[str, str] = {}
    rest = source
    for slot in SLOT_NAMES:
        b, e = _begin(slot), _end(slot)
        if rest.count(b) != 1 or rest.count(e) != 1:
            raise ValueError(f"{slot} markers missing or repeated")
        before, _, after = rest.partition(b)
        body, _, rest = after.partition(e)
        fixed_parts.append(before)
        slots[slot] = body
    fixed_parts.append(rest)
    return "|".join(fixed_parts), slots


def expected_fixed_text() -> str:
    """The fixed text every capability must carry, taken from a reference assembly."""
    ref = assemble("def compute(bands, params):\n    return 0\n", "def interpret(evidence):\n    return {}\n",
                   "l", "t", "d", ["red"], "v", "u", "mean", "greens", None, {})
    return split(ref)[0]
