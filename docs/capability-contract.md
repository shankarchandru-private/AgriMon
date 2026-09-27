# AgriMon · Capability contract (toolresult/2, manifest/2, template 2)

**Division of responsibility.** The platform owns execution orchestration, data access, validation,
visualization, persistence, evaluation and provenance. A generated capability owns only the
analytical computation and the analytical metadata needed to describe and interpret it.

Every capability, seed or generated, is one `capability.py` assembled from the fixed template plus a
`manifest.json`.

## The template

```python
# fixed header
import math
import numpy as np
from agrimon import sdk

# ==== BEGIN SLOT 1 ====        LLM: analytical code only (functions, no imports)
def compute(bands, params):      # bands: dict of read-only 2-D float arrays scaled 0-1
    ...                          # return a per-pixel array, or
                                 # {"values": array, "zones": {name: bool mask}, "metrics": [...]}
def interpret(evidence):         # evidence: computed values only (metrics, zones, classes, grid)
    ...                          # return {"summary", "findings", "next_steps"}
def _helper(...): ...            # optional private helpers
# ==== END SLOT 1 ====

# ==== BEGIN SLOT 2 ====        literals written by trusted code from the LLM's declarations
LAYER_NAME, ANALYSIS_TYPE, DESCRIPTION, REQUIRED_BANDS, VALUE_LABEL, VALUE_UNIT,
AGGREGATION, COLOR_MAP, CLASSIFICATION, PARAMETERS
# ==== END SLOT 2 ====

# fixed footer: execute(context) -> ToolResult, never generated
load_bands -> compute -> analysis_output -> to_matrix -> matrix_metrics (+ capability metrics)
-> zones_from_masks -> class_summary -> evidence -> interpret -> build_result
```

## Analysis freedom

Visualization does not dictate the analytical contract.

- **Continuous analyses** return a continuous matrix and metrics. No universal value range, no
  required min/max bounds; negative values and values above 1 are fine. Use `np.nan` where a value is
  undefined.
- **Zones are optional.** A capability returns boolean masks only when regions are meaningful for
  the question; the platform turns them into connected-component zones.
- **Classification only when requested.** `CLASSIFICATION` is `None` unless the question asks for
  classes. When present it has at least two classes and `AGGREGATION = "mode"`.
- **The platform derives visualization stats** from the matrix: observed min/max, a 2nd–98th
  percentile display range, and a histogram. `COLOR_MAP` is one of `greens`, `blues`, `reds`,
  `purples`, `ylorrd`, chosen by the generator.

## Guardrails

The analytical logic must not access the filesystem, the network or credentials, launch processes,
modify application state, the registry or committed capabilities, persist files, or talk to external
services. Enforced twice:

1. **Admission** (`ast`, before any execution): fixed sections unchanged; slot 1 only function
   definitions (`compute`, `interpret`, private `_helpers`); no imports, `open`, `eval`, `exec`,
   `getattr`, `__import__` and similar; no `os`, `sys`, `subprocess`, `socket`, `sdk`, `context` and
   similar names; no NumPy I/O (`save`, `load`, `fromfile`, `tofile`, `memmap`, ...), no `np.random`,
   no private attributes; slot 2 literals only and consistent with the manifest and the asset.
2. **Runtime guard** in the capability subprocess (audit hook, active while the capability module
   loads and runs): blocks sockets, subprocesses, file writes, deletes and renames, ctypes and similar.
   A blocked attempt fails the run with `guardrail_violation` even if the code catches the error.
   The subprocess environment carries no API key.

## Context (input)

Request and run ids; mode; the question and analysis key; the selected asset (id, label, date, path,
width, height, bands, nodata, resolution); grid rows and columns; parameters; output folder; capability
id, version and content hash; template and config versions. No secrets.

## ToolResult v2 (output)

| Field | Content |
| --- | --- |
| `status` | `success`, `partial` or `failed` (failed carries errors and no findings) |
| `layer_name`, `description`, `analysis_type` | What the layer is and how it was computed |
| `asset_id` | The asset analysed (must equal `provenance.asset_id`) |
| `metrics` | Platform matrix statistics (`matrix_mean/min/max/std`, `valid_cells`, `nodata_cells`, source `platform`) plus capability metrics (source `capability`) |
| `matrix` | JSON rows × cols of numbers or `null`, derived from the input (48×48 by default) |
| `grid_size` | rows, cols, cell size in pixels (and metres when georeferenced) |
| `color_map` | One of the five allowed names |
| `zones` | Optional; id, name, cell count, share, mean value, bounds and cells |
| `classification` | Optional; classes with cell counts and shares |
| `summary`, `findings`, `next_steps` | Written by `interpret` from evidence; findings cite evidence; next steps are `follow_up_analysis` or `human_inspection` |
| `provenance` | Capability id, version, content hash, asset, parameters, config, timestamps |
| `warnings`, `errors` | Structured messages |

## Grounding

- Every number in the summary and findings must appear in the returned metrics, zones or classes.
- Every finding cites evidence that exists (`matrix_mean`, a zone id, `class:<id>`).
- No agronomic prescriptions (treatments, rates, spraying, irrigation, fertilizer).
- A citation is recorded when a reliable source exists; its absence is a warning, not a failure.
- An RGB proxy is named as such (for example "Excess Green (ExG)"), never as NDVI.

## Provenance

`persisted capability.py bytes → SHA-256 → Context → ToolResult.provenance → EvaluationReport → commit`.
The hash is always taken from the file on disk, never from an in-memory string, and the registry
re-verifies the copied file's hash at commit and before every match-path run.
