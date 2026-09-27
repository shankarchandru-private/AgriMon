"""The seed capability, written by developers: a true-color brightness overview.

A continuous analysis: no classes and no fixed value bounds. Its brightest and darkest regions
are defined from the scene's own brightness distribution (10th and 90th percentiles). It is
assembled from the same template and committed through the same harness gate as generated
capabilities (see scripts/reset_demo.py).
"""

from agrimon.contracts import GenerationOutput

SEED_ID = "rgb_overview"
SEED_ANALYSIS_KEY = "brightness_overview"
SEED_ALIASES = ["true_color_overview", "rgb_brightness_overview"]

COMPUTE = '''def compute(bands, params):
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
    }'''

INTERPRET = '''def interpret(evidence):
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
    return {"summary": summary, "findings": findings, "next_steps": steps}'''

SEED = GenerationOutput(
    name="True-color brightness overview",
    description=(
        "Per-pixel brightness of the true-color image as a luminance-weighted mean of red, green and "
        "blue, with the scene's brightest and darkest regions."
    ),
    analysis_type="brightness_overview",
    layer_name="Brightness (Rec. 709 luma)",
    method="brightness = 0.2126 R + 0.7152 G + 0.0722 B on 0-1 scaled bands; regions at the 10th and 90th percentiles",
    citation="ITU-R Recommendation BT.709-6, luma coefficients (2015)",
    required_bands=["red", "green", "blue"],
    value_label="Brightness",
    value_unit="fraction",
    aggregation="mean",
    color_map="ylorrd",
    classification=None,
    compute_source=COMPUTE,
    interpret_source=INTERPRET,
)
