# AgriMon capability, assembled from the fixed capability template.
# Only the three SLOT sections differ between capabilities; everything else is
# checked byte-for-byte at admission.
# template-version: 1
import math

import numpy as np

from agrimon import sdk

# ==== BEGIN SLOT 1 ====
def compute_values(bands, params):
    """Rec. 709 luma from 0-1 scaled red, green and blue."""
    return 0.2126 * bands["red"] + 0.7152 * bands["green"] + 0.0722 * bands["blue"]
# ==== END SLOT 1 ====

# ==== BEGIN SLOT 2 ====
DESCRIPTION = ('Per-pixel brightness of the true-color image as a luminance-weighted mean of red, green and '
 'blue, summarized on a grid with its brightest and darkest regions. Formula: brightness = 0.2126 '
 'R + 0.7152 G + 0.0722 B (bands scaled to 0-1).')
REQUIRED_BANDS = ['red', 'green', 'blue']
VALUE_LABEL = 'Brightness (0-1)'
VALUE_UNIT = 'fraction'
VALUE_RANGE = (0.0, 1.0)
PARAMETERS = {}
CLASSES = [{'id': 0, 'label': 'very dark', 'color': '#1b1f3b', 'min': 0.0, 'max': 0.2},
 {'id': 1, 'label': 'dark', 'color': '#3d4f7d', 'min': 0.2, 'max': 0.4},
 {'id': 2, 'label': 'medium', 'color': '#8a94a6', 'min': 0.4, 'max': 0.6},
 {'id': 3, 'label': 'bright', 'color': '#d9c27a', 'min': 0.6, 'max': 0.8},
 {'id': 4, 'label': 'very bright', 'color': '#fff3b0', 'min': 0.8, 'max': 1.0}]
# ==== END SLOT 2 ====

# ==== BEGIN SLOT 3 ====
FINDING_RULES = [{'id': 'F1',
  'template': 'Mean brightness is {metric.mean_value} on a 0 to 1 scale, ranging from '
              '{metric.min_value} to {metric.max_value}.'},
 {'id': 'F2',
  'template': 'The largest {zone.high-1.label} covers {zone.high-1.share_pct}% of valid cells, '
              'with mean brightness {zone.high-1.mean_value}.'},
 {'id': 'F3',
  'template': 'The largest {zone.low-1.label} covers {zone.low-1.share_pct}% of valid cells, with '
              'mean brightness {zone.low-1.mean_value}.'}]
NEXT_STEPS = [{'type': 'human_inspection',
  'description': 'Inspect the darkest region in the source image: brightness alone cannot separate '
                 'water, shadow, dense canopy and wet ground.',
  'follows_from': 'F3'},
 {'type': 'follow_up_analysis',
  'description': 'Compare the brightest region with a color-based analysis, such as an RGB '
                 'vegetation proxy, to see whether it is bare soil, built surface or dry '
                 'vegetation.',
  'follows_from': 'F2'},
 {'type': 'follow_up_analysis',
  'description': 'Repeat the overview on another acquisition of the same area to check whether the '
                 'brightness pattern persists.',
  'follows_from': 'F1'}]
# ==== END SLOT 3 ====


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
