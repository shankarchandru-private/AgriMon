"""SDK implementation. Imports only agrimon.contracts, NumPy and rasterio."""

from __future__ import annotations

import re
import warnings
from collections import deque
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np

from agrimon.contracts import (
    ColorClass,
    Context,
    Finding,
    Grid,
    Message,
    Metric,
    NextStep,
    Provenance,
    ToolResult,
    Zone,
)

PLACEHOLDER = re.compile(r"\{(metric|zone|class)\.([A-Za-z0-9_\-]+?)(?:\.([a-z_]+))?\}")
ZONE_FIELDS = {"share_pct", "mean_value", "cell_count", "area_m2", "label"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def fmt(x: float) -> str:
    """Formats a number the same way everywhere, so the harness can trace it."""
    x = float(x)
    if x.is_integer():
        return str(int(x))
    return f"{x:.3f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- 1. bands


def load_bands(context: Context, names: Sequence[str]) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Returns the named bands scaled to 0-1 and a boolean nodata mask (True = nodata)."""
    import rasterio
    from rasterio.errors import NotGeoreferencedWarning

    refs = {b.name: b for b in context.bands}
    missing = [n for n in names if n not in refs]
    if missing:
        raise ValueError(f"scene {context.scene_id} has no band(s): {', '.join(missing)}")
    arrays: dict[str, np.ndarray] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(context.scene_path) as ds:
            nodata = np.ones((ds.height, ds.width), dtype=bool) if context.nodata is not None else np.zeros(
                (ds.height, ds.width), dtype=bool
            )
            for name in names:
                raw = ds.read(refs[name].index).astype("float64")
                if context.nodata is not None:
                    nodata &= raw == context.nodata
                arrays[name] = raw * refs[name].scale
    return arrays, nodata


# --------------------------------------------------------------------------- 2. grid


def to_grid(values: np.ndarray, nodata: np.ndarray, rows: int, cols: int) -> dict[str, Any]:
    """Per-cell mean, minimum, maximum and valid-pixel count."""
    values = np.asarray(values, dtype="float64")
    valid = (~nodata) & np.isfinite(values)
    h, w = values.shape
    r_edges = np.linspace(0, h, rows + 1).round().astype(int)
    c_edges = np.linspace(0, w, cols + 1).round().astype(int)
    mean = np.full((rows, cols), np.nan)
    vmin = np.full((rows, cols), np.nan)
    vmax = np.full((rows, cols), np.nan)
    count = np.zeros((rows, cols), dtype=int)
    for i in range(rows):
        for j in range(cols):
            block = values[r_edges[i]: r_edges[i + 1], c_edges[j]: c_edges[j + 1]]
            ok = valid[r_edges[i]: r_edges[i + 1], c_edges[j]: c_edges[j + 1]]
            if ok.any():
                v = block[ok]
                mean[i, j], vmin[i, j], vmax[i, j], count[i, j] = v.mean(), v.min(), v.max(), ok.sum()
    return {
        "mean": mean,
        "min": vmin,
        "max": vmax,
        "count": count,
        "rows": rows,
        "cols": cols,
        "cell_height_px": h / rows,
        "cell_width_px": w / cols,
    }


# --------------------------------------------------------------------------- 3. classes


def _classes(classes: Sequence[dict]) -> list[dict]:
    return sorted(classes, key=lambda c: c["min"])


def classify(grid_mean: np.ndarray, classes: Sequence[dict]) -> np.ndarray:
    """Class id per cell from the declared breaks; -1 marks nodata cells."""
    ordered = _classes(classes)
    out = np.full(grid_mean.shape, -1, dtype=int)
    finite = np.isfinite(grid_mean)
    for i, c in enumerate(ordered):
        sel = finite & (out == -1)
        if i < len(ordered) - 1:  # last class takes everything left, including its max
            sel &= grid_mean < c["max"]
        out[sel] = c["id"]
    return out


# --------------------------------------------------------------------------- 4. zones


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


def find_zones(
    class_grid: np.ndarray, grid: dict, classes: Sequence[dict], context: Context, max_zones: int = 3
) -> list[dict]:
    """Connected cells (4-connectivity) of the highest and lowest classes present.

    Zone ids are high-1..high-3 (largest first) and low-1..low-3. Area is given only
    when the scene has a known resolution.
    """
    by_id = {c["id"]: c for c in classes}
    present = sorted({int(v) for v in np.unique(class_grid) if v >= 0}, key=lambda cid: by_id[cid]["min"])
    if not present:
        return []
    total_valid = int((class_grid >= 0).sum())
    cell_area = None
    if context.resolution_m:
        cell_area = grid["cell_height_px"] * grid["cell_width_px"] * context.resolution_m**2
    zones: list[dict] = []
    for prefix, cid in (("high", present[-1]), ("low", present[0])):
        for k, comp in enumerate(_components(class_grid == cid)[:max_zones], start=1):
            rr = [r for r, _ in comp]
            cc = [c for _, c in comp]
            zones.append({
                "id": f"{prefix}-{k}",
                "class_id": cid,
                "label": f"{by_id[cid]['label']} region",
                "cell_count": len(comp),
                "share_pct": round(100.0 * len(comp) / total_valid, 2),
                "area_m2": round(cell_area * len(comp), 1) if cell_area else None,
                "mean_value": round(float(np.nanmean([grid["mean"][r, c] for r, c in comp])), 3),
                "row_min": min(rr),
                "row_max": max(rr),
                "col_min": min(cc),
                "col_max": max(cc),
            })
    return zones


# --------------------------------------------------------------------------- 5. metrics


def standard_metrics(
    values: np.ndarray, nodata: np.ndarray, grid: dict, class_grid: np.ndarray, classes: Sequence[dict], unit: str
) -> list[dict]:
    """Mean, minimum and maximum; share of cells per class; nodata count."""
    values = np.asarray(values, dtype="float64")
    valid = (~nodata) & np.isfinite(values)
    metrics: list[dict] = []
    if valid.any():
        v = values[valid]
        metrics += [
            {"name": "mean_value", "value": round(float(v.mean()), 3), "unit": unit, "description": "Mean over valid pixels"},
            {"name": "min_value", "value": round(float(v.min()), 3), "unit": unit, "description": "Minimum over valid pixels"},
            {"name": "max_value", "value": round(float(v.max()), 3), "unit": unit, "description": "Maximum over valid pixels"},
        ]
    valid_cells = int((class_grid >= 0).sum())
    metrics += [
        {"name": "valid_cells", "value": valid_cells, "unit": "cells", "description": "Grid cells with data"},
        {"name": "nodata_cells", "value": int((class_grid < 0).sum()), "unit": "cells", "description": "Grid cells without data"},
    ]
    for c in _classes(classes):
        share = 100.0 * int((class_grid == c["id"]).sum()) / valid_cells if valid_cells else 0.0
        metrics.append({
            "name": f"class_{c['id']}_share_pct",
            "value": round(share, 2),
            "unit": "percent",
            "description": f"Share of valid cells in class '{c['label']}'",
        })
    return metrics


# --------------------------------------------------------------------------- 6. findings


def render_findings(
    rules: Sequence[dict], metrics: Sequence[dict], zones: Sequence[dict], classes: Sequence[dict]
) -> list[dict]:
    """Fills finding placeholders from computed values and attaches evidence references.

    A rule is dropped when it references a missing metric or zone, or cites no evidence at all.
    """
    m = {x["name"]: x for x in metrics}
    z = {x["id"]: x for x in zones}
    c = {str(x["id"]): x for x in classes}
    findings = []
    for rule in rules:
        evidence: list[str] = []
        missing = False

        def sub(match: re.Match) -> str:
            nonlocal missing
            kind, ref, field = match.group(1), match.group(2), match.group(3)
            if kind == "metric":
                if ref not in m:
                    missing = True
                    return ""
                evidence.append(ref)
                return fmt(m[ref]["value"])
            if kind == "zone":
                if ref not in z or (field and field not in ZONE_FIELDS):
                    missing = True
                    return ""
                evidence.append(ref)
                val = z[ref].get(field or "label")
                if val is None:
                    missing = True
                    return ""
                return val if isinstance(val, str) else fmt(val)
            if ref not in c:
                missing = True
                return ""
            return c[ref]["label"]

        text = PLACEHOLDER.sub(sub, rule["template"])
        if missing or not evidence:
            continue
        findings.append({"id": rule["id"], "statement": text, "evidence": sorted(set(evidence))})
    return findings


# --------------------------------------------------------------------------- 7. summary


def summarize(
    context: Context, value_label: str, metrics: Sequence[dict], zones: Sequence[dict], classes: Sequence[dict]
) -> str:
    """A short summary composed only from computed values."""
    m = {x["name"]: x["value"] for x in metrics}
    ordered = _classes(classes)
    parts = [f"{context.scene_label} ({context.scene_date}):"]
    if "mean_value" in m:
        parts.append(
            f"{value_label} averages {fmt(m['mean_value'])} (range {fmt(m['min_value'])} to {fmt(m['max_value'])})"
            f" across {fmt(m['valid_cells'])} valid cells of a {context.grid_rows}x{context.grid_cols} grid."
        )
    present = [c for c in ordered if m.get("class_%s_share_pct" % c["id"], 0) > 0]
    if present:
        hi, lo = present[-1], present[0]
        hi_share = fmt(m["class_%s_share_pct" % hi["id"]])
        lo_share = fmt(m["class_%s_share_pct" % lo["id"]])
        if hi is lo:
            parts.append(f"All valid cells fall in the '{hi['label']}' class ({hi_share}%).")
        else:
            parts.append(
                f"The highest class present, '{hi['label']}', covers {hi_share}% of cells;"
                f" the lowest, '{lo['label']}', covers {lo_share}%."
            )
    return " ".join(parts)


# --------------------------------------------------------------------------- 8. result


def _nan_to_none(arr: np.ndarray, digits: int = 4) -> list[list[float | None]]:
    return [[None if not np.isfinite(v) else round(float(v), digits) for v in row] for row in arr]


def build_result(
    context: Context,
    description: str,
    value_label: str,
    metrics: Sequence[dict],
    grid: dict,
    class_grid: np.ndarray,
    classes: Sequence[dict],
    zones: Sequence[dict],
    summary: str,
    findings: Sequence[dict],
    next_steps: Sequence[dict],
    started_at: str,
) -> ToolResult:
    """Assembles and validates the ToolResult. Next steps survive only if their finding does."""
    finding_ids = {f["id"] for f in findings}
    cell_size = None
    if context.resolution_m:
        cell_size = round(context.resolution_m * (grid["cell_width_px"] + grid["cell_height_px"]) / 2, 2)
    warnings_: list[Message] = []
    if not findings:
        warnings_.append(Message(code="no_findings", message="No finding rule could be grounded in computed values"))
    return ToolResult(
        status="success",
        description=description,
        metrics=[Metric(**x) for x in metrics],
        grid=Grid(
            rows=grid["rows"],
            cols=grid["cols"],
            cell_width_px=round(grid["cell_width_px"], 3),
            cell_height_px=round(grid["cell_height_px"], 3),
            cell_size_m=cell_size,
            value_label=value_label,
            class_ids=[[int(v) for v in row] for row in class_grid],
            values=_nan_to_none(grid["mean"]),
            minimum=_nan_to_none(grid["min"]),
            maximum=_nan_to_none(grid["max"]),
        ),
        color_map=[ColorClass(**c) for c in _classes(classes)],
        zones=[Zone(**z) for z in zones],
        summary=summary,
        findings=[Finding(**f) for f in findings],
        next_steps=[NextStep(**s) for s in next_steps if s["follows_from"] in finding_ids],
        provenance=Provenance(
            capability_id=context.capability_id,
            capability_version=context.capability_version,
            content_hash=context.content_hash,
            template_version=context.template_version,
            scene_id=context.scene_id,
            asset_file=context.scene_path.replace("\\", "/").split("/")[-1],
            parameters=context.parameters,
            config_version=context.config_version,
            started_at=started_at,
            finished_at=now(),
        ),
        warnings=warnings_,
    )
