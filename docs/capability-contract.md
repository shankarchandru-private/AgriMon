# AgriMon · Capability contract

Every capability, seed or generated, is one `capability.py` assembled from the fixed template
(version 1) plus a `manifest.json`. The template owns the execution interface; the LLM supplies only
analytical logic and its declarations.

## The template

```python
# fixed header
import math
import numpy as np
from agrimon import sdk

# ==== BEGIN SLOT 1 ====        LLM: the only analytical code
def compute_values(bands, params):
    ...                          # bands: dict of 2-D arrays scaled 0-1; return one value per pixel
# ==== END SLOT 1 ====

# ==== BEGIN SLOT 2 ====        written as literals by trusted code from the LLM's declarations
DESCRIPTION, REQUIRED_BANDS, VALUE_LABEL, VALUE_UNIT, VALUE_RANGE, PARAMETERS, CLASSES
# ==== END SLOT 2 ====

# ==== BEGIN SLOT 3 ====
FINDING_RULES, NEXT_STEPS
# ==== END SLOT 3 ====

# fixed footer
def execute(context):            # Execute(Context) -> ToolResult, never generated
    load_bands -> compute_values -> to_grid -> classify -> standard_metrics
    -> find_zones -> render_findings -> summarize -> build_result
```

Admission rejects any change to the fixed sections, imports in slot 1, and calls or names that reach
the file system, network, OS or Python internals.

## SDK (`agrimon.sdk`)

`load_bands`, `to_grid`, `classify`, `find_zones`, `standard_metrics`, `render_findings`,
`summarize`, `build_result` (plus `fmt`, `now`). Capabilities may import only `agrimon.sdk`, NumPy and
`math`; all raster access goes through `load_bands`.

## Context (input)

Request and run ids; mode (`committed`, `staged`, `probe`); scene id, label, date and path; band names,
indices and scale factors; nodata; resolution (if known); grid rows and columns; parameters; output
folder; capability id, version and content hash; template and config versions. No secrets.

## ToolResult v1 (output)

| Field | Content |
| --- | --- |
| `status` | `success`, `partial` or `failed` (failed carries errors and no findings) |
| `description` | What was computed and how |
| `metrics` | `mean_value`, `min_value`, `max_value`, `valid_cells`, `nodata_cells`, `class_<id>_share_pct`, each with a unit |
| `grid` | Rows, columns, cell size, and per cell: class id (−1 = no data), mean, minimum, maximum |
| `color_map` | Per class: id, label, colour, value range |
| `zones` | `high-1..3` and `low-1..3`: largest connected regions of the highest and lowest classes present |
| `summary` | Composed from computed values only |
| `findings` | Statements rendered from rule templates, each with evidence references |
| `next_steps` | Typed `follow_up_analysis` or `human_inspection`, each tied to a finding |
| `provenance` | Capability id, version and content hash, scene, parameters, config version, timestamps |
| `warnings`, `errors` | Structured messages |

## Grounding rules

Analytical output must be grounded in computed evidence.

- Finding templates may use only `{metric.<name>}`, `{zone.<id>[.field]}` and `{class.<id>}`
  placeholders. A rule whose metric or zone is missing, or that cites no evidence, is dropped.
- The harness checks that every number in the summary and findings appears in metrics or zones, that
  every finding cites existing evidence, and that no finding or next step prescribes treatments,
  inputs, rates, spraying, irrigation or fertilizer.
- An RGB proxy is named as such (for example "RGB vegetation proxy (Excess Green)"), never as NDVI.

## Manifest

Id, version, template version, analysis key and aliases, name, description, required bands, value
label, unit and range, classes, formula and citation, parameters, finding rules, next steps, origin
(`seed` or `generated`) and the request that created it.
