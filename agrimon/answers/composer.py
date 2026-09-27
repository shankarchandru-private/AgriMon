"""Builds the Answer shown in the UI: the ToolResult plus which capability produced it."""

from __future__ import annotations

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
        "categories": [c.model_dump() for c in report.categories],
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
    )
