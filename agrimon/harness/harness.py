"""The 17-check evaluation harness: 13 blocking checks decide the verdict, 4 raise warnings.

Hand-written and trusted. Its source, probes and thresholds never appear in a generation prompt.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from pydantic import ValidationError

from agrimon.config import Settings
from agrimon.contracts import (
    CapabilityManifest,
    CategoryScore,
    CheckResult,
    Context,
    EvaluationReport,
    Intent,
    Registry,
    Scene,
    ToolResult,
)
from agrimon.harness.probes import masked_quadrant, probe_scenes
from agrimon.observability import get_logger
from agrimon.runtime import RunOutcome, Runtime, build_context

log = get_logger("harness")

HARNESS_VERSION = "1.0"
CATEGORIES = ["Contract", "Execution", "Data", "Analytical quality", "Grounding", "User value", "Governance"]
NUMBER = re.compile(r"(?<![A-Za-z_\d.])-?\d+(?:\.\d+)?(?![A-Za-z_\d])")
PRESCRIPTIVE = [
    re.compile(r"\b(apply|spray|fertili[sz]e|irrigate|treat|replant|re-?seed|harvest|till|plough|plow|drain)\b", re.I),
    re.compile(r"\b(herbicide|pesticide|fungicide|insecticide|fertili[sz]er)s?\b", re.I),
    re.compile(r"\b\d+(\.\d+)?\s*(kg|lb|lbs|litres?|liters?|gal|gallons?|mm|inches)\b", re.I),
]

Judge = Callable[[str, CapabilityManifest, ToolResult], Optional[tuple[float, str]]]


def _c(name, category, blocking, passed, observed="", expected="", evidence="", score=None) -> CheckResult:
    return CheckResult(
        name=name, category=category, blocking=blocking, passed=bool(passed),
        score=float(score if score is not None else (1.0 if passed else 0.0)),
        observed=str(observed)[:500], expected=str(expected)[:300], evidence=str(evidence)[:500],
    )


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


class Harness:
    def __init__(self, settings: Settings, runtime: Runtime):
        self.settings = settings
        self.runtime = runtime

    # ------------------------------------------------------------------ entry point
    def evaluate(
        self,
        *,
        capability_file: Path,
        manifest: CapabilityManifest,
        first_run: RunOutcome,
        context: Context,
        scene: Scene,
        snapshot: Registry,
        admission_violations: list[str],
        intent: Intent | None,
        work_dir: Path,
        subject: str = "candidate",
        judge: Judge | None = None,
    ) -> EvaluationReport:
        source_hash = hashlib.sha256(capability_file.read_bytes()).hexdigest()
        tr = first_run.tool_result
        has_result = tr.status != "failed" and tr.grid is not None
        checks: list[CheckResult] = []

        # Contract ------------------------------------------------------------
        checks.append(self._schema(tr))
        checks.append(self._completeness(tr, has_result))
        # Execution -----------------------------------------------------------
        checks.append(_c("Clean run", "Execution", True, first_run.ok,
                         observed=f"exit={first_run.exit_reason}, {first_run.duration_s:.2f}s",
                         expected=f"exit=ok within {self.settings.runtime.timeout_seconds:g}s",
                         evidence="; ".join(e.message for e in tr.errors)))
        checks.append(self._reproducibility(capability_file, context, tr, has_result, work_dir))
        # Data ----------------------------------------------------------------
        checks.append(self._input_validity(manifest, scene, tr, has_result))
        checks.append(self._value_ranges(manifest, tr, has_result))
        # Analytical quality --------------------------------------------------
        checks.append(self._probes(capability_file, manifest, source_hash, has_result, work_dir))
        checks.append(self._class_spread(tr, has_result))
        # Grounding -----------------------------------------------------------
        checks.append(self._numbers_traced(manifest, scene, tr, has_result))
        checks.append(self._evidence_refs(tr, has_result))
        checks.append(self._no_prescriptions(tr))
        checks.append(_c("Formula citation", "Grounding", False,
                         bool(manifest.formula.strip()) and len(manifest.citation.strip()) >= 10,
                         observed=f"formula='{manifest.formula}'; citation='{manifest.citation}'",
                         expected="a formula and a published source"))
        # User value ----------------------------------------------------------
        checks.append(self._answers_intent(intent, manifest, tr, has_result, judge))
        checks.append(self._readable_summary(scene, tr, has_result))
        # Governance ----------------------------------------------------------
        checks.append(_c("Admission passed", "Governance", True, not admission_violations,
                         observed="; ".join(admission_violations) or "all 7 admission rules passed",
                         expected="no admission violations"))
        checks.append(self._not_duplicate(manifest, snapshot))
        checks.append(self._provenance(tr, manifest, source_hash, scene, has_result))

        return self._report(checks, manifest, source_hash, subject)

    # ------------------------------------------------------------------ scoring
    def _report(self, checks, manifest, source_hash, subject) -> EvaluationReport:
        cats = []
        for cat in CATEGORIES:
            items = [c for c in checks if c.category == cat]
            cats.append(CategoryScore(
                category=cat,
                score=round(sum(c.score for c in items) / len(items), 3),
                passed=all(c.passed for c in items if c.blocking),
            ))
        blocking = [c for c in checks if c.blocking]
        verdict = "pass" if all(c.passed for c in blocking) else "fail"
        return EvaluationReport(
            report_id=uuid.uuid4().hex[:12],
            subject=subject,
            capability_id=manifest.id,
            capability_version=manifest.version,
            content_hash=source_hash,
            harness_version=HARNESS_VERSION,
            config_version=self.settings.config_version,
            checks=checks,
            categories=cats,
            blocking_passed=sum(c.passed for c in blocking),
            blocking_total=len(blocking),
            warnings_raised=sum(not c.passed for c in checks if not c.blocking),
            overall_score=round(sum(c.score for c in checks) / len(checks), 3),
            verdict=verdict,
        )

    # ------------------------------------------------------------------ Contract
    @staticmethod
    def _schema(tr: ToolResult) -> CheckResult:
        try:
            ToolResult.model_validate(tr.model_dump())
            ok = tr.status == "success"
            obs = f"valid {tr.contract_version}, status={tr.status}"
        except ValidationError as exc:
            ok, obs = False, str(exc).splitlines()[0]
        return _c("Schema conformance", "Contract", True, ok, observed=obs, expected="valid toolresult/1 with status=success")

    def _completeness(self, tr: ToolResult, has_result: bool) -> CheckResult:
        if not has_result:
            return _c("Completeness", "Contract", True, False, observed="no result", expected="all fields present")
        missing = []
        if not tr.metrics:
            missing.append("metrics")
        if not tr.summary.strip():
            missing.append("summary")
        if not tr.findings:
            missing.append("findings")
        if not tr.zones:
            missing.append("zones")
        classes_in_grid = {v for row in tr.grid.class_ids for v in row if v >= 0}
        uncovered = classes_in_grid - {c.id for c in tr.color_map}
        if uncovered:
            missing.append(f"color_map for classes {sorted(uncovered)}")
        return _c("Completeness", "Contract", True, not missing,
                  observed="missing: " + ", ".join(missing) if missing else "all fields present; color map covers the grid",
                  expected="metrics, grid, color map, zones, summary, findings")

    # ------------------------------------------------------------------ Execution
    def _reproducibility(self, cap: Path, ctx: Context, tr: ToolResult, has_result: bool, work_dir: Path) -> CheckResult:
        if not has_result:
            return _c("Reproducibility", "Execution", True, False, observed="no first result to compare")
        again = self.runtime.run(cap, ctx.model_copy(update={"run_id": ctx.run_id + "-repro"}), work_dir / "repro")
        if not again.ok:
            return _c("Reproducibility", "Execution", True, False, observed=f"second run failed: {again.exit_reason}")
        a, b = tr.grid, again.tool_result.grid
        same_classes = a.class_ids == b.class_ids
        same_values = a.values == b.values
        same_metrics = [(m.name, m.value) for m in tr.metrics] == [(m.name, m.value) for m in again.tool_result.metrics]
        ok = same_classes and same_values and same_metrics
        return _c("Reproducibility", "Execution", True, ok,
                  observed=f"classes equal={same_classes}, values equal={same_values}, metrics equal={same_metrics}",
                  expected="identical grid and metrics on a second run")

    # ------------------------------------------------------------------ Data
    def _input_validity(self, manifest, scene: Scene, tr: ToolResult, has_result: bool) -> CheckResult:
        problems = [f"band '{b}' not in scene" for b in manifest.required_bands if b not in scene.band_names]
        if has_result:
            g = tr.grid
            if (g.rows, g.cols) != (self.settings.grid.rows, self.settings.grid.cols):
                problems.append(f"grid {g.rows}x{g.cols} != declared {self.settings.grid.rows}x{self.settings.grid.cols}")
            m = {x.name: x.value for x in tr.metrics}
            if m.get("valid_cells", -1) + m.get("nodata_cells", -1) != g.rows * g.cols:
                problems.append("valid_cells + nodata_cells does not equal the cell count")
        else:
            problems.append("no result")
        return _c("Input validity", "Data", True, not problems,
                  observed="; ".join(problems) or f"bands {manifest.required_bands} present; grid and nodata consistent",
                  expected="required bands present, declared grid size, nodata accounted for")

    @staticmethod
    def _value_ranges(manifest: CapabilityManifest, tr: ToolResult, has_result: bool) -> CheckResult:
        if not has_result:
            return _c("Value ranges", "Data", True, False, observed="no result")
        lo, hi, eps = manifest.value_min, manifest.value_max, 1e-6
        m = {x.name: x.value for x in tr.metrics}
        out = [f"{k}={m[k]}" for k in ("mean_value", "min_value", "max_value") if k in m and not lo - eps <= m[k] <= hi + eps]
        cells = [v for row in tr.grid.values for v in row if v is not None]
        if cells and (min(cells) < lo - eps or max(cells) > hi + eps):
            out.append(f"grid values span {min(cells):.3f}..{max(cells):.3f}")
        shares = sum(x.value for x in tr.metrics if x.name.endswith("_share_pct"))
        if m.get("valid_cells", 0) > 0 and abs(shares - 100) > 0.5:
            out.append(f"class shares sum to {shares:.2f}%")
        return _c("Value ranges", "Data", True, not out,
                  observed="; ".join(out) or f"all values within [{lo:g}, {hi:g}]; class shares sum to {shares:.2f}%",
                  expected=f"values within the declared scale [{lo:g}, {hi:g}]; shares sum to 100%")

    # ------------------------------------------------------------------ Analytical quality
    def _probes(self, cap: Path, manifest, source_hash: str, has_result: bool, work_dir: Path) -> CheckResult:
        if not has_result:
            return _c("Probe behaviour", "Analytical quality", True, False, observed="skipped: no result on the scene")
        probes = probe_scenes()
        notes, ok = [], True
        for name, (scene, path) in probes.items():
            if not path.exists():
                return _c("Probe behaviour", "Analytical quality", True, False,
                          observed=f"probe raster {path.name} missing; run scripts/prepare_assets.py")
            ctx = build_context(self.settings, scene, manifest, source_hash, "probe", "harness", f"probe-{name}",
                                work_dir / f"probe-{name}", scene_file=path)
            out = self.runtime.run(cap, ctx, work_dir / f"probe-{name}")
            if not out.ok:
                ok = False
                notes.append(f"{name}: run failed ({out.exit_reason})")
                continue
            ids = np.array(out.tool_result.grid.class_ids)
            if name == "constant":
                valid = ids[ids >= 0]
                good = valid.size == ids.size and len(np.unique(valid)) == 1
                notes.append(f"constant: {len(np.unique(valid))} class(es), {int((ids < 0).sum())} nodata cells")
            else:
                rows, cols = ids.shape
                pr, pc = masked_quadrant()
                r_edges = np.linspace(0, scene.height, rows + 1)
                c_edges = np.linspace(0, scene.width, cols + 1)
                inside = np.outer(r_edges[1:] <= pr, c_edges[1:] <= pc)
                outside = ~np.outer(r_edges[:-1] < pr, c_edges[:-1] < pc)
                good = bool((ids[inside] == -1).all() and (ids[outside] >= 0).all())
                notes.append(f"masked: {int((ids[inside] == -1).sum())}/{int(inside.sum())} masked cells are nodata,"
                             f" {int((ids[outside] >= 0).sum())}/{int(outside.sum())} unmasked cells have data")
            ok = ok and good
        return _c("Probe behaviour", "Analytical quality", True, ok, observed="; ".join(notes),
                  expected="constant image -> one class; masked quadrant -> nodata cells only there")

    def _class_spread(self, tr: ToolResult, has_result: bool) -> CheckResult:
        if not has_result:
            return _c("Class spread", "Analytical quality", False, False, observed="no result")
        shares = {x.name: x.value for x in tr.metrics if x.name.endswith("_share_pct")}
        top = max(shares.values()) if shares else 100.0
        limit = self.settings.harness.class_spread_warning * 100
        return _c("Class spread", "Analytical quality", False, top <= limit,
                  observed=f"largest class covers {top:g}% of cells", expected=f"no class above {limit:g}%",
                  score=1.0 if top <= limit else max(0.0, 1 - (top - limit) / (100 - limit + 1e-9)))

    # ------------------------------------------------------------------ Grounding
    @staticmethod
    def _numbers_traced(manifest: CapabilityManifest, scene: Scene, tr: ToolResult, has_result: bool) -> CheckResult:
        if not has_result:
            return _c("Numbers traced", "Grounding", True, False, observed="no result")
        allowed: list[float] = [x.value for x in tr.metrics]
        for z in tr.zones:
            allowed += [z.share_pct, z.mean_value, z.cell_count] + ([z.area_m2] if z.area_m2 is not None else [])
        allowed += [c.min for c in tr.color_map] + [c.max for c in tr.color_map]
        allowed += [manifest.value_min, manifest.value_max, tr.grid.rows, tr.grid.cols]
        strip = sorted({z.id for z in tr.zones} | {x.name for x in tr.metrics} | {scene.label, scene.date_text,
                        tr.grid.value_label} | {c.label for c in tr.color_map}, key=len, reverse=True)
        untraced = []
        for label, text in [("summary", tr.summary)] + [(f.id, f.statement) for f in tr.findings]:
            for token in strip:
                text = text.replace(token, " ")
            for mt in NUMBER.finditer(text):
                s = mt.group()
                x, d = float(s), _decimals(s)
                if not any(abs(round(v, d) - x) < 1e-9 or abs(v - x) < 1e-9 for v in allowed):
                    untraced.append(f"{label}: {s}")
        return _c("Numbers traced", "Grounding", True, not untraced,
                  observed="untraced: " + ", ".join(untraced) if untraced else "every number appears in metrics or zones",
                  expected="numbers in summary and findings come from metrics or zones")

    @staticmethod
    def _evidence_refs(tr: ToolResult, has_result: bool) -> CheckResult:
        if not has_result:
            return _c("Evidence references", "Grounding", True, False, observed="no result")
        known = {x.name for x in tr.metrics} | {z.id for z in tr.zones}
        bad = [f.id for f in tr.findings if not f.evidence or any(e not in known for e in f.evidence)]
        return _c("Evidence references", "Grounding", True, bool(tr.findings) and not bad,
                  observed=f"findings without valid evidence: {bad}" if bad else f"{len(tr.findings)} findings, all cite metrics or zones",
                  expected="every finding cites at least one existing metric or zone")

    @staticmethod
    def _no_prescriptions(tr: ToolResult) -> CheckResult:
        hits = []
        texts = [(f"next step {i + 1}", s.description) for i, s in enumerate(tr.next_steps)]
        texts += [(f.id, f.statement) for f in tr.findings]
        for label, text in texts:
            for pat in PRESCRIPTIVE:
                m = pat.search(text)
                if m:
                    hits.append(f"{label}: '{m.group()}'")
        typed = all(s.type in ("follow_up_analysis", "human_inspection") for s in tr.next_steps)
        return _c("No unsupported prescriptions", "Grounding", True, typed and not hits,
                  observed="prescriptive wording: " + ", ".join(hits) if hits else
                  f"{len(tr.next_steps)} next steps, all follow-up analysis or human inspection",
                  expected="next steps are follow-up analysis or human inspection, never prescriptions")

    # ------------------------------------------------------------------ User value
    @staticmethod
    def _answers_intent(intent, manifest, tr, has_result, judge) -> CheckResult:
        if not has_result:
            return _c("Answers the intent", "User value", False, False, observed="no result")
        if judge is None or intent is None:
            return _c("Answers the intent", "User value", False, False, score=0.5,
                      observed="not judged: no LLM judge available", expected="LLM-judged score of at least 0.6")
        try:
            verdict = judge(intent.question, manifest, tr)
        except Exception as exc:  # judge errors never block
            verdict = None
            log.warning(f"judge failed: {exc}")
        if verdict is None:
            return _c("Answers the intent", "User value", False, False, score=0.5,
                      observed="not judged: the judge call failed", expected="LLM-judged score of at least 0.6")
        score, reason = verdict
        score = min(1.0, max(0.0, float(score)))
        return _c("Answers the intent", "User value", False, score >= 0.6, score=score,
                  observed=f"judge score {score:.2f}: {reason}", expected="LLM-judged score of at least 0.6")

    def _readable_summary(self, scene: Scene, tr: ToolResult, has_result: bool) -> CheckResult:
        if not has_result:
            return _c("Readable summary", "User value", False, False, observed="no result")
        limit = self.settings.harness.summary_max_chars
        ok = len(tr.summary) <= limit and scene.label in tr.summary and scene.date_text in tr.summary
        return _c("Readable summary", "User value", False, ok,
                  observed=f"{len(tr.summary)} chars; names scene={scene.label in tr.summary}; names date={scene.date_text in tr.summary}",
                  expected=f"at most {limit} chars, naming the scene and its date")

    # ------------------------------------------------------------------ Governance
    @staticmethod
    def _not_duplicate(manifest: CapabilityManifest, snapshot: Registry) -> CheckResult:
        clash = [e for e in snapshot.capabilities
                 if e.id == manifest.id or manifest.analysis_key in (e.analysis_key, *e.aliases)]
        return _c("Not a duplicate", "Governance", True, not clash,
                  observed=f"clashes with {clash[0].id} {clash[0].version}" if clash else f"'{manifest.analysis_key}' is new",
                  expected="no committed capability with the same id or analysis key")

    @staticmethod
    def _provenance(tr: ToolResult, manifest, source_hash: str, scene: Scene, has_result: bool) -> CheckResult:
        if not has_result or tr.provenance is None:
            return _c("Provenance complete", "Governance", True, False, observed="no provenance")
        p = tr.provenance
        problems = []
        if (p.capability_id, p.capability_version) != (manifest.id, manifest.version):
            problems.append("capability id/version mismatch")
        if p.content_hash != source_hash:
            problems.append("content hash does not match the capability file")
        if p.scene_id != scene.id:
            problems.append("scene id mismatch")
        return _c("Provenance complete", "Governance", True, not problems,
                  observed="; ".join(problems) or f"{p.capability_id} {p.capability_version}, hash {p.content_hash[:12]}, scene {p.scene_id}",
                  expected="capability, version, content hash, scene and parameters recorded")
