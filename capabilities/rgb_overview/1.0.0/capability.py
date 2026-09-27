# AgriMon capability, assembled from the fixed capability template.
# Only the two SLOT sections differ between capabilities; everything else is
# checked byte-for-byte at admission.
# template-version: 2
import math

import numpy as np

from agrimon import sdk

# ==== BEGIN SLOT 1 ====
def compute(bands, params):
    """Rec. 709 luma of the 0-1 scaled true-color bands; regions from the scene's own percentiles."""
    luma = 0.2126 * bands["red"] + 0.7152 * bands["green"] + 0.0722 * bands["blue"]
    p10 = float(np.nanpercentile(luma, 10))
    p90 = float(np.nanpercentile(luma, 90))
    return {
        "values": luma,
        "zones": {"brightest": luma >= p90, "darkest": luma <= p10},
        "metrics": {
            "brightness_p10": {"value": p10, "unit": "fraction", "description": "10th percentile of pixel brightness"},
            "brightness_p90": {"value": p90, "unit": "fraction", "description": "90th percentile of pixel brightness"},
        },
    }


def interpret(evidence):
    """Summary, findings and next steps built only from the evidence the platform computed."""
    m = evidence["metrics"]
    asset = evidence["asset"]
    grid = evidence["grid_size"]
    zones = evidence["zones"]
    summary = (
        f"{asset['label']} ({asset['date']}): cell brightness averages {m['matrix_mean']:.3f} "
        f"(range {m['matrix_min']:.3f} to {m['matrix_max']:.3f}) across {int(m['valid_cells'])} valid cells "
        f"of a {grid['rows']}x{grid['cols']} matrix."
    )
    findings = [{
        "id": "F1",
        "statement": f"Mean cell brightness is {m['matrix_mean']:.3f}, ranging from {m['matrix_min']:.3f} "
                     f"to {m['matrix_max']:.3f}.",
        "evidence": ["matrix_mean", "matrix_min", "matrix_max"],
    }]
    steps = [{"type": "follow_up_analysis",
              "description": "Repeat the overview on another acquisition of the same area to check whether "
                             "the brightness pattern persists.",
              "follows_from": "F1"}]
    for name, metric, fid, word in (("brightest", "brightness_p90", "F2", "at or above"),
                                    ("darkest", "brightness_p10", "F3", "at or below")):
        found = [z for z in zones if z["name"] == name]
        if found:
            z = found[0]
            findings.append({
                "id": fid,
                "statement": f"The largest {name} region ({z['id']}) covers {z['share_pct']}% of valid cells "
                             f"with mean brightness {z['mean_value']:.3f}; its pixels are {word} "
                             f"{m[metric]:.3f}.",
                "evidence": [z["id"], metric],
            })
    ids = {f["id"] for f in findings}
    if "F3" in ids:
        steps.append({"type": "human_inspection",
                      "description": "Inspect the darkest region in the source image: brightness alone cannot "
                                     "separate water, shadow, dense canopy and wet ground.",
                      "follows_from": "F3"})
    if "F2" in ids:
        steps.append({"type": "follow_up_analysis",
                      "description": "Compare the brightest region with a color-based analysis, such as an RGB "
                                     "vegetation proxy, to see whether it is bare soil, built surface or dry vegetation.",
                      "follows_from": "F2"})
    return {"summary": summary, "findings": findings, "next_steps": steps}
# ==== END SLOT 1 ====

# ==== BEGIN SLOT 2 ====
LAYER_NAME = 'Brightness (Rec. 709 luma)'
ANALYSIS_TYPE = 'brightness_overview'
DESCRIPTION = ('Per-pixel brightness of the true-color image as a luminance-weighted mean of red, green and '
 "blue, with the scene's brightest and darkest regions. Method: brightness = 0.2126 R + 0.7152 G + "
 '0.0722 B on 0-1 scaled bands; regions at the 10th and 90th percentiles')
REQUIRED_BANDS = ['red', 'green', 'blue']
VALUE_LABEL = 'Brightness'
VALUE_UNIT = 'fraction'
AGGREGATION = 'mean'
COLOR_MAP = 'ylorrd'
CLASSIFICATION = None
PARAMETERS = {}
# ==== END SLOT 2 ====


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
