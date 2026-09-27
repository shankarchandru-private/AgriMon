"""Builds the Answer shown in the UI: the ToolResult, which capability produced it, and platform-derived
visualization statistics. The capability never supplies display bounds; the platform derives them here."""

from __future__ import annotations

import numpy as np

from agrimon.contracts import Answer, EvaluationReport, ToolResult


def evaluation_summary(report: EvaluationReport | None, report_ref: str | None) -> dict | None:
    if report is None:
        return None
    return {
        "report_ref": report_ref,
        "verdict": report.verdict,
        "overall_score": report.overall_score,
        "blocking_passed": report.blocking_passed,
        "blocking_total": report.blocking_total,
        "warnings_raised": report.warnings_raised,
        "harness_version": report.harness_version,
        "categories": [c.model_dump() for c in report.categories],
    }


def visualization(tr: ToolResult) -> dict | None:
    """Observed range, a robust display range (2nd-98th percentile) and a histogram of the matrix."""
    if tr.matrix is None:
        return None
    m = np.array([[np.nan if v is None else v for v in row] for row in tr.matrix], dtype=float)
    v = m[np.isfinite(m)]
    if v.size == 0:
        return {"observed_min": None, "observed_max": None, "display_min": None, "display_max": None,
                "histogram": [], "categorical": tr.classification is not None}
    lo, hi = float(np.percentile(v, 2)), float(np.percentile(v, 98))
    if hi <= lo:
        lo, hi = float(v.min()), float(v.max())
    counts, edges = np.histogram(v, bins=12)
    return {
        "observed_min": round(float(v.min()), 5),
        "observed_max": round(float(v.max()), 5),
        "display_min": round(lo, 5),
        "display_max": round(hi, 5),
        "histogram": [{"from": round(float(edges[i]), 5), "to": round(float(edges[i + 1]), 5), "count": int(c)}
                      for i, c in enumerate(counts)],
        "categorical": tr.classification is not None,
    }


def compose(
    source: str,
    capability_id: str,
    capability_version: str,
    run_id: str,
    tool_result: ToolResult,
    report: EvaluationReport | None,
    report_ref: str | None,
) -> Answer:
    return Answer(
        source=source,
        capability_id=capability_id,
        capability_version=capability_version,
        run_id=run_id,
        tool_result=tool_result,
        evaluation=evaluation_summary(report, report_ref),
        visualization=visualization(tool_result),
    )
