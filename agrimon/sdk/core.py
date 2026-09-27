"""Platform SDK used by the fixed template. Imports only agrimon.contracts, NumPy and rasterio.

Division of labour:
  capability  -> compute(bands, params): the analytical raster, optional region masks, optional metrics
                 interpret(evidence):   summary, findings and next steps from the platform's evidence
  platform    -> data access, aggregation into the matrix, matrix statistics, zones, class summaries,
                 validation, provenance and the ToolResult itself.
"""

from __future__ import annotations

import math
import re
import warnings
from collections import deque
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from agrimon.contracts import (
    Classification,
    ClassSummary,
    Context,
    GridSize,
    Interpretation,
    Message,
    Metric,
    Provenance,
    ToolResult,
    Zone,
)

NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
MAX_ZONES_PER_MASK = 3


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def fmt(x: float, digits: int = 3) -> str:
    """Formats a number compactly; the harness traces numbers with rounding tolerance."""
    x = float(x)
    if x.is_integer():
        return str(int(x))
    return f"{x:.{digits}f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- data access


def load_bands(context: Context, names: Sequence[str]) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Returns the named bands of the selected asset scaled to 0-1, and a nodata mask (True = nodata)."""
    import rasterio
    from rasterio.errors import NotGeoreferencedWarning

    refs = {b.name: b for b in context.bands}
    missing = [n for n in names if n not in refs]
    if missing:
        raise ValueError(f"asset {context.asset_id} has no band(s): {', '.join(missing)}")
    arrays: dict[str, np.ndarray] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(context.asset_path) as ds:
            shape = (ds.height, ds.width)
            nodata = np.ones(shape, dtype=bool) if context.nodata is not None else np.zeros(shape, dtype=bool)
            for name in names:
                raw = ds.read(refs[name].index).astype("float64")
                if context.nodata is not None:
                    nodata &= raw == context.nodata
                arrays[name] = raw * refs[name].scale
    for arr in arrays.values():
        arr.setflags(write=False)  # the analysis reads its inputs; it never edits them
    return arrays, nodata


# --------------------------------------------------------------------------- capability output


def analysis_output(out: Any, shape: tuple[int, int]) -> dict[str, Any]:
    """Validates what compute() returned: an array, or {"values", optional "zones", optional "metrics"}."""
    if not isinstance(out, Mapping):
        out = {"values": out}
    unknown = set(out) - {"values", "zones", "metrics"}
    if unknown:
        raise ValueError(f"compute() returned unknown keys: {sorted(unknown)}")
    values = np.asarray(out.get("values"), dtype="float64")
    if values.shape != shape:
        raise ValueError(f"compute() values must have the asset's shape {shape}, got {values.shape}")
    values = np.where(np.isfinite(values), values, np.nan)

    zones: Optional[dict[str, np.ndarray]] = None
    if out.get("zones") is not None:
        if not isinstance(out["zones"], Mapping):
            raise ValueError("compute() zones must be a dict of {name: boolean mask}")
        zones = {}
        for name, mask in out["zones"].items():
            if not NAME.match(str(name)):
                raise ValueError(f"zone name '{name}' must be snake_case")
            m = np.asarray(mask)
            if m.shape != shape:
                raise ValueError(f"zone mask '{name}' must have the asset's shape {shape}")
            zones[str(name)] = m.astype(bool)

    metrics: list[dict] = []
    for name, spec in (out.get("metrics") or {}).items():
        if not NAME.match(str(name)):
            raise ValueError(f"metric name '{name}' must be snake_case")
        if isinstance(spec, Mapping):
            value, unit, desc = spec.get("value"), str(spec.get("unit", "")), str(spec.get("description", ""))
        else:
            value, unit, desc = spec, "", ""
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"metric '{name}' is not a finite number")
        metrics.append({"name": str(name), "value": round(value, 4), "unit": unit, "description": desc,
                        "source": "capability"})
    return {"values": values, "zones": zones, "metrics": metrics}


# --------------------------------------------------------------------------- matrix


def _edges(n: int, parts: int) -> np.ndarray:
    return np.linspace(0, n, parts + 1).round().astype(int)


def _reduce(v: np.ndarray, how: str) -> float:
    if how == "mean":
        return float(v.mean())
    if how == "median":
        return float(np.median(v))
    if how == "min":
        return float(v.min())
    if how == "max":
        return float(v.max())
    vals, counts = np.unique(v, return_counts=True)  # mode; ties -> smallest value
    return float(vals[np.argmax(counts)])


def to_matrix(values: np.ndarray, nodata: np.ndarray, rows: int, cols: int, aggregation: str) -> dict[str, Any]:
    """Aggregates the per-pixel analytical raster into a rows x cols matrix (NaN = no valid pixels)."""
    valid = (~nodata) & np.isfinite(values)
    h, w = values.shape
    re_, ce = _edges(h, rows), _edges(w, cols)
    matrix = np.full((rows, cols), np.nan)
    count = np.zeros((rows, cols), dtype=int)
    for i in range(rows):
        for j in range(cols):
            ok = valid[re_[i]: re_[i + 1], ce[j]: ce[j + 1]]
            if ok.any():
                matrix[i, j] = _reduce(values[re_[i]: re_[i + 1], ce[j]: ce[j + 1]][ok], aggregation)
                count[i, j] = int(ok.sum())
    return {"matrix": matrix, "count": count, "rows": rows, "cols": cols,
            "cell_height_px": h / rows, "cell_width_px": w / cols, "valid": valid}


def matrix_metrics(grid: dict, unit: str) -> list[dict]:
    """Platform statistics of the returned matrix. Recomputable by anyone from the matrix itself."""
    m = grid["matrix"]
    ok = np.isfinite(m)
    out = []
    if ok.any():
        v = m[ok]
        for name, val, desc in (
            ("matrix_mean", v.mean(), "Mean of the matrix cells"),
            ("matrix_min", v.min(), "Lowest matrix cell"),
            ("matrix_max", v.max(), "Highest matrix cell"),
            ("matrix_std", v.std(), "Standard deviation of the matrix cells"),
        ):
            out.append({"name": name, "value": round(float(val), 4), "unit": unit, "description": desc, "source": "platform"})
    out.append({"name": "valid_cells", "value": int(ok.sum()), "unit": "cells", "description": "Matrix cells with data", "source": "platform"})
    out.append({"name": "nodata_cells", "value": int((~ok).sum()), "unit": "cells", "description": "Matrix cells without data", "source": "platform"})
    return out


# --------------------------------------------------------------------------- zones


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    seen = np.zeros(mask.shape, dtype=bool)
    comps = []
    rows, cols = mask.shape
    for i in range(rows):
        for j in range(cols):
            if mask[i, j] and not seen[i, j]:
                comp, queue = [], deque([(i, j)])
                seen[i, j] = True
                while queue:
                    r, c = queue.popleft()
                    comp.append((r, c))
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < rows and 0 <= nc < cols and mask[nr, nc] and not seen[nr, nc]:
                            seen[nr, nc] = True
                            queue.append((nr, nc))
                comps.append(comp)
    comps.sort(key=lambda comp: (-len(comp), comp[0]))
    return comps


def zones_from_masks(masks: Optional[dict[str, np.ndarray]], grid: dict, context: Context) -> Optional[list[dict]]:
    """Turns the capability's region masks into zones: connected matrix cells where most valid pixels are in the mask.

    Returns None when the capability defined no regions (zones are optional).
    """
    if masks is None:
        return None
    m, valid = grid["matrix"], grid["valid"]
    rows, cols = grid["rows"], grid["cols"]
    h, w = valid.shape
    re_, ce = _edges(h, rows), _edges(w, cols)
    total_valid = int(np.isfinite(m).sum())
    cell_area = None
    if context.resolution_m:
        cell_area = grid["cell_height_px"] * grid["cell_width_px"] * context.resolution_m ** 2
    zones: list[dict] = []
    for name, mask in masks.items():
        cellmask = np.zeros((rows, cols), dtype=bool)
        for i in range(rows):
            for j in range(cols):
                ok = valid[re_[i]: re_[i + 1], ce[j]: ce[j + 1]]
                if ok.any() and np.isfinite(m[i, j]):
                    cellmask[i, j] = mask[re_[i]: re_[i + 1], ce[j]: ce[j + 1]][ok].mean() >= 0.5
        for k, comp in enumerate(_components(cellmask)[:MAX_ZONES_PER_MASK], start=1):
            rr = [r for r, _ in comp]
            cc = [c for _, c in comp]
            zones.append({
                "id": f"{name}-{k}",
                "name": name,
                "cell_count": len(comp),
                "share_pct": round(100.0 * len(comp) / total_valid, 2) if total_valid else 0.0,
                "mean_value": round(float(np.mean([m[r, c] for r, c in comp])), 4),
                "area_m2": round(cell_area * len(comp), 1) if cell_area else None,
                "row_min": min(rr), "row_max": max(rr), "col_min": min(cc), "col_max": max(cc),
                "cells": [(int(r), int(c)) for r, c in comp],
            })
    return zones


# --------------------------------------------------------------------------- classification


def class_summary(grid: dict, classes: Optional[Sequence[Mapping]]) -> Optional[dict]:
    """For classified rasters: counts and shares per declared class. None for continuous analyses."""
    if classes is None:
        return None
    m = grid["matrix"]
    ok = np.isfinite(m)
    ids = {int(c["id"]) for c in classes}
    present = {float(v) for v in np.unique(m[ok])}
    stray = sorted(v for v in present if not (v.is_integer() and int(v) in ids))
    if stray:
        raise ValueError(f"classified matrix contains values that are not declared class ids: {stray[:5]}")
    total = int(ok.sum())
    out = []
    for c in classes:
        n = int((m[ok] == int(c["id"])).sum())
        out.append({"id": int(c["id"]), "label": c["label"], "description": c.get("description", ""),
                    "cell_count": n, "share_pct": round(100.0 * n / total, 2) if total else 0.0})
    return {"classes": out}


# --------------------------------------------------------------------------- interpretation


def evidence(context: Context, grid: dict, metrics: Sequence[dict], zones: Optional[Sequence[dict]],
             classification: Optional[dict], value_label: str, value_unit: str) -> dict:
    """The plain-Python evidence handed to interpret(). Everything a finding may cite is here."""
    return {
        "asset": {"id": context.asset_id, "label": context.asset_label, "date": context.asset_date},
        "question": context.question,
        "grid_size": {"rows": grid["rows"], "cols": grid["cols"]},
        "value_label": value_label,
        "value_unit": value_unit,
        "metrics": {m["name"]: m["value"] for m in metrics},
        "metric_units": {m["name"]: m["unit"] for m in metrics},
        "zones": [{k: v for k, v in z.items() if k != "cells"} for z in (zones or [])],
        "zones_defined": zones is not None,
        "classes": list(classification["classes"]) if classification else [],
    }


def interpretation(obj: Any) -> Interpretation:
    if not isinstance(obj, Mapping):
        raise ValueError("interpret() must return a dict with summary, findings and next_steps")
    return Interpretation.model_validate(dict(obj))


# --------------------------------------------------------------------------- result


def build_result(context: Context, meta: Mapping, grid: dict, metrics: Sequence[dict], zones: Optional[Sequence[dict]],
                 classification: Optional[dict], interp: Interpretation, started_at: str) -> ToolResult:
    m = grid["matrix"]
    cell_size = None
    if context.resolution_m:
        cell_size = round(context.resolution_m * (grid["cell_width_px"] + grid["cell_height_px"]) / 2, 2)
    warns: list[Message] = []
    if zones is not None and not zones:
        warns.append(Message(code="no_zones", message="The analysis defined regions, but none covered a matrix cell"))
    return ToolResult(
        status="success",
        layer_name=meta["layer_name"],
        description=meta["description"],
        analysis_type=meta["analysis_type"],
        asset_id=context.asset_id,
        metrics=[Metric(**x) for x in metrics],
        matrix=[[None if not np.isfinite(v) else round(float(v), 5) for v in row] for row in m],
        grid_size=GridSize(rows=grid["rows"], cols=grid["cols"], cell_width_px=round(grid["cell_width_px"], 3),
                           cell_height_px=round(grid["cell_height_px"], 3), cell_size_m=cell_size),
        color_map=meta["color_map"],
        zones=[Zone(**z) for z in zones] if zones is not None else None,
        classification=Classification(classes=[ClassSummary(**c) for c in classification["classes"]])
        if classification else None,
        summary=interp.summary,
        findings=interp.findings,
        next_steps=interp.next_steps,
        provenance=Provenance(
            capability_id=context.capability_id,
            capability_version=context.capability_version,
            content_hash=context.content_hash,
            template_version=context.template_version,
            asset_id=context.asset_id,
            asset_file=context.asset_path.replace("\\", "/").split("/")[-1],
            parameters=context.parameters,
            config_version=context.config_version,
            started_at=started_at,
            finished_at=now(),
        ),
        warnings=warns,
    )
