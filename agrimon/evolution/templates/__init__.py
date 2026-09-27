"""The fixed capability template.

Every capability, seed or generated, is assembled here: a fixed header, three slots, and a
fixed footer that owns the execution interface execute(context) -> ToolResult. Admission
checks the fixed parts byte-for-byte, so the LLM can only supply analytical logic.
"""

from __future__ import annotations

import pprint

TEMPLATE_VERSION = "1"

SLOT_NAMES = ("SLOT 1", "SLOT 2", "SLOT 3")

HEADER = '''# AgriMon capability, assembled from the fixed capability template.
# Only the three SLOT sections differ between capabilities; everything else is
# checked byte-for-byte at admission.
# template-version: 1
import math

import numpy as np

from agrimon import sdk

'''

FOOTER = '''

def execute(context):
    """Fixed interface: execute(context) -> ToolResult. Not editable by generation."""
    started_at = sdk.now()
    bands, nodata = sdk.load_bands(context, REQUIRED_BANDS)
    params = dict(PARAMETERS)
    params.update(context.parameters)
    values = np.asarray(compute_values(bands, params), dtype="float64")
    if values.shape != nodata.shape:
        raise ValueError("compute_values must return one value per pixel")
    grid = sdk.to_grid(values, nodata, context.grid_rows, context.grid_cols)
    class_grid = sdk.classify(grid["mean"], CLASSES)
    metrics = sdk.standard_metrics(values, nodata, grid, class_grid, CLASSES, VALUE_UNIT)
    zones = sdk.find_zones(class_grid, grid, CLASSES, context)
    findings = sdk.render_findings(FINDING_RULES, metrics, zones, CLASSES)
    summary = sdk.summarize(context, VALUE_LABEL, metrics, zones, CLASSES)
    return sdk.build_result(
        context, DESCRIPTION, VALUE_LABEL, metrics, grid, class_grid, CLASSES,
        zones, summary, findings, NEXT_STEPS, started_at,
    )
'''


def _begin(slot: str) -> str:
    return f"# ==== BEGIN {slot} ====\n"


def _end(slot: str) -> str:
    return f"# ==== END {slot} ====\n"


SLOT2_NAMES = ("DESCRIPTION", "REQUIRED_BANDS", "VALUE_LABEL", "VALUE_UNIT", "VALUE_RANGE", "PARAMETERS", "CLASSES")
SLOT3_NAMES = ("FINDING_RULES", "NEXT_STEPS")


def _literal(name: str, value) -> str:
    return f"{name} = {pprint.pformat(value, width=100, sort_dicts=False)}\n"


def assemble(
    compute_values_source: str,
    description: str,
    required_bands: list[str],
    value_label: str,
    value_unit: str,
    value_range: tuple[float, float],
    parameters: dict,
    classes: list[dict],
    finding_rules: list[dict],
    next_steps: list[dict],
) -> str:
    """Builds capability.py. Slots 2 and 3 are written as Python literals by this trusted code."""
    slot1 = compute_values_source.strip("\n") + "\n"
    slot2 = "".join(
        _literal(n, v)
        for n, v in (
            ("DESCRIPTION", description),
            ("REQUIRED_BANDS", list(required_bands)),
            ("VALUE_LABEL", value_label),
            ("VALUE_UNIT", value_unit),
            ("VALUE_RANGE", (float(value_range[0]), float(value_range[1]))),
            ("PARAMETERS", dict(parameters)),
            ("CLASSES", [dict(c) for c in sorted(classes, key=lambda c: c["min"])]),
        )
    )
    slot3 = _literal("FINDING_RULES", [dict(r) for r in finding_rules]) + _literal(
        "NEXT_STEPS", [dict(s) for s in next_steps]
    )
    return (
        HEADER
        + _begin("SLOT 1") + slot1 + _end("SLOT 1") + "\n"
        + _begin("SLOT 2") + slot2 + _end("SLOT 2") + "\n"
        + _begin("SLOT 3") + slot3 + _end("SLOT 3")
        + FOOTER
    )


def split(source: str) -> tuple[str, dict[str, str]]:
    """Returns (fixed_text, {slot: body}). Raises ValueError if markers are missing or out of order."""
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
    ref = assemble("def compute_values(bands, params):\n    return 0\n", "d", ["red"], "v", "u", (0, 1), {},
                   [{"id": 0, "label": "a", "color": "#000000", "min": 0, "max": 1}],
                   [{"id": "F1", "template": "x {metric.mean_value}"}], [])
    return split(ref)[0]
