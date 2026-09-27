"""The evaluation harness: the commit gate. Hand-written, trusted, and never shown to the generator.

It tests analytical behaviour, not just the presence of fields: it re-runs the candidate on the
same input (reproducibility), on a mirrored copy and on copies with one band inverted (the matrix
must be derived from, and respond to, the actual input), and on synthetic probes (uniform input,
masked input). It never imposes universal value ranges or mandatory classes.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from pydantic import ValidationError

from agrimon.catalog import scene_path
from agrimon.config import Settings
from agrimon.contracts import (
    COLOR_MAPS,
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
from agrimon.harness.probes import masked_quadrant, probe_scenes, write_variant
from agrimon.observability import get_logger
from agrimon.runtime import RunOutcome, Runtime, build_context

log = get_logger("harness")

HARNESS_VERSION = "2.0"
CATEGORIES = ["Contract", "Execution", "Data", "Analytical quality", "Grounding", "User value", "Governance"]
GRID_LIMITS = (32, 96)  # "approximately 48x48 or 64x64"
NUMBER = re.compile(r"(?<![A-Za-z_\d.])-?\d+(?:\.\d+)?(?![A-Za-z_\d])")
PRESCRIPTIVE = [
    re.compile(r"\b(apply|applying|spray|spraying|fertili[sz]e|fertili[sz]ing|irrigate|irrigating|treat|treating|"
               r"replant|re-?seed|harvest|till|plough|plow|drain|cull|prune)\b", re.I),
    re.compile(r"\b(herbicide|pesticide|fungicide|insecticide|fertili[sz]er|nitrogen|manure|lime)s?\b", re.I),
    re.compile(r"\b\d+(\.\d+)?\s*(kg|lb|lbs|litres?|liters?|gal|gallons?|mm|inches|tons?|t)\s*/\s*(ha|acre|ac)\b", re.I),
    re.compile(r"\b(you|farmers?|growers?) (should|must|need to)\b", re.I),
]

Judge = Callable[[str, CapabilityManifest, ToolResult], Optional[tuple[float, str]]]


def _c(name, category, blocking, passed, observed="", expected="", evidence="", score=None) -> CheckResult:
    return CheckResult(
        name=name, category=category, blocking=blocking, passed=bool(passed),
        score=float(score if score is not None else (1.0 if passed else 0.0)),
        observed=str(observed)[:600], expected=str(expected)[:300], evidence=str(evidence)[:500],
    )


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def _arr(tr: ToolResult) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in tr.matrix], dtype=float)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        committed_fingerprint: Callable[[], str] | None = None,
    ) -> EvaluationReport:
        start_hash = _sha(capability_file)
        start_fp = committed_fingerprint() if committed_fingerprint else None
        tr = first_run.tool_result
        ok = tr.status != "failed" and tr.matrix is not None
        base = _arr(tr) if ok else None
        checks: list[CheckResult] = []

        # Contract
        checks.append(self._schema(tr))
        checks.append(self._grid(tr, context, ok))
        checks.append(self._asset_colormap(tr, context, ok))
        # Execution
        checks.append(_c("Clean run", "Execution", True, first_run.ok,
                         observed=f"exit={first_run.exit_reason}, {first_run.duration_s:.2f}s",
                         expected=f"exit=ok within the {self.settings.runtime.timeout_seconds:g}s timeout",
                         evidence="; ".join(f"{e.code}: {e.message}" for e in tr.errors)))
        checks.append(self._reproducibility(capability_file, context, tr, ok, work_dir))
        # Data
        checks.append(self._data_available(manifest, scene, first_run))
        checks.append(self._input_dependence(capability_file, manifest, scene, context, base, work_dir))
        # Analytical quality
        checks.append(self._data_derived(capability_file, scene, context, base, work_dir))
        checks.append(self._probes(capability_file, manifest, start_hash, ok, work_dir))
        checks.append(self._metrics_consistent(tr, base))
        checks.append(self._zones_classes(tr, base))
        # Grounding
        checks.append(self._numbers_traced(scene, tr, ok))
        checks.append(self._evidence_refs(tr, ok))
        checks.append(self._no_prescriptions(tr))
        has_cite = len(manifest.citation.strip()) >= 10
        checks.append(_c("Methodology reference", "Grounding", False, has_cite, score=1.0 if has_cite else 0.5,
                         observed=f"method='{manifest.method}'; citation='{manifest.citation or 'none'}'",
                         expected="a citation or methodological reference when the method is not self-evident"))
        # User value
        checks.append(self._answers_intent(intent, manifest, tr, ok, judge))
        checks.append(self._useful(scene, tr, ok))
        # Governance
        checks.append(_c("Admission passed", "Governance", True, not admission_violations,
                         observed="; ".join(admission_violations) or "all 7 admission rules passed (no forbidden operations)",
                         expected="no admission violations"))
        checks.append(self._not_duplicate(manifest, snapshot))
        checks.append(self._provenance(capability_file, start_hash, context, tr, ok))
        end_fp = committed_fingerprint() if committed_fingerprint else None
        checks.append(_c("Committed state untouched", "Governance", True, start_fp == end_fp,
                         observed="capabilities/ byte-identical before and after all candidate runs" if start_fp == end_fp
                         else "capabilities/ changed while the candidate was being evaluated",
                         expected="evaluating a candidate never modifies committed capabilities or the registry"))
        return self._report(checks, manifest, start_hash, subject)

    # ------------------------------------------------------------------ scoring
    def _report(self, checks, manifest, source_hash, subject) -> EvaluationReport:
        cats = []
        for cat in CATEGORIES:
            items = [c for c in checks if c.category == cat]
            cats.append(CategoryScore(category=cat, score=round(sum(c.score for c in items) / len(items), 3),
                                      passed=all(c.passed for c in items if c.blocking)))
        blocking = [c for c in checks if c.blocking]
        return EvaluationReport(
            report_id=uuid.uuid4().hex[:12], subject=subject, capability_id=manifest.id,
            capability_version=manifest.version, content_hash=source_hash, harness_version=HARNESS_VERSION,
            config_version=self.settings.config_version, checks=checks, categories=cats,
            blocking_passed=sum(c.passed for c in blocking), blocking_total=len(blocking),
            warnings_raised=sum(not c.passed for c in checks if not c.blocking),
            overall_score=round(sum(c.score for c in checks) / len(checks), 3),
            verdict="pass" if all(c.passed for c in blocking) else "fail",
        )

    def _run_variant(self, cap: Path, ctx: Context, scene: Scene, path: Path, name: str, work_dir: Path) -> RunOutcome:
        vctx = ctx.model_copy(update={"run_id": f"{ctx.run_id}-{name}", "asset_path": str(path)})
        return self.runtime.run(cap, vctx, work_dir / name)

    # ------------------------------------------------------------------ Contract
    @staticmethod
    def _schema(tr: ToolResult) -> CheckResult:
        try:
            ToolResult.model_validate(tr.model_dump())
            ok = tr.status == "success"
            obs = f"valid {tr.contract_version}, status={tr.status}"
        except ValidationError as exc:
            ok, obs = False, str(exc).splitlines()[0]
        return _c("Schema conformance", "Contract", True, ok, observed=obs,
                  expected="a valid ToolResult (Pydantic) with status=success")

    def _grid(self, tr: ToolResult, ctx: Context, ok: bool) -> CheckResult:
        if not ok:
            return _c("Matrix and grid size", "Contract", True, False, observed="no matrix")
        g = tr.grid_size
        lo, hi = GRID_LIMITS
        problems = []
        if (g.rows, g.cols) != (ctx.grid_rows, ctx.grid_cols):
            problems.append(f"grid {g.rows}x{g.cols} differs from the requested {ctx.grid_rows}x{ctx.grid_cols}")
        if not (lo <= g.rows <= hi and lo <= g.cols <= hi):
            problems.append(f"grid {g.rows}x{g.cols} outside {lo}-{hi}")
        valid = sum(v is not None for row in tr.matrix for v in row)
        if valid == 0:
            problems.append("matrix has no valid cells")
        return _c("Matrix and grid size", "Contract", True, not problems,
                  observed="; ".join(problems) or f"{g.rows}x{g.cols} matrix, {valid} valid cells",
                  expected=f"a {ctx.grid_rows}x{ctx.grid_cols} JSON matrix of numbers or nulls")

    @staticmethod
    def _asset_colormap(tr: ToolResult, ctx: Context, ok: bool) -> CheckResult:
        if not ok:
            return _c("Asset and color map", "Contract", True, False, observed="no result")
        problems = []
        if tr.asset_id != ctx.asset_id:
            problems.append(f"asset_id '{tr.asset_id}' is not the selected asset '{ctx.asset_id}'")
        if tr.color_map not in COLOR_MAPS:
            problems.append(f"color map '{tr.color_map}' not allowed")
        if not tr.layer_name.strip() or not tr.analysis_type.strip():
            problems.append("layer_name and analysis_type must be set")
        return _c("Asset and color map", "Contract", True, not problems,
                  observed="; ".join(problems) or f"asset {tr.asset_id}, color map {tr.color_map}, layer '{tr.layer_name}'",
                  expected=f"asset_id of the selected asset; color map one of {', '.join(COLOR_MAPS)}")

    # ------------------------------------------------------------------ Execution
    def _reproducibility(self, cap, ctx, tr, ok, work_dir) -> CheckResult:
        if not ok:
            return _c("Reproducibility", "Execution", True, False, observed="no first result to compare")
        again = self.runtime.run(cap, ctx.model_copy(update={"run_id": ctx.run_id + "-repro"}), work_dir / "repro")
        if not again.ok:
            return _c("Reproducibility", "Execution", True, False, observed=f"second run failed: {again.exit_reason}")
        b = again.tool_result
        same = {
            "matrix": tr.matrix == b.matrix,
            "metrics": [(m.name, m.value) for m in tr.metrics] == [(m.name, m.value) for m in b.metrics],
            "zones": [z.model_dump() for z in (tr.zones or [])] == [z.model_dump() for z in (b.zones or [])],
            "text": (tr.summary, [f.statement for f in tr.findings]) == (b.summary, [f.statement for f in b.findings]),
        }
        return _c("Reproducibility", "Execution", True, all(same.values()),
                  observed=", ".join(f"{k} identical={v}" for k, v in same.items()),
                  expected="identical matrix, metrics, zones and text on a second run")

    # ------------------------------------------------------------------ Data
    @staticmethod
    def _data_available(manifest, scene: Scene, run: RunOutcome) -> CheckResult:
        missing = [b for b in manifest.required_bands if b not in scene.band_names]
        load_error = any("has no band" in e.message for e in run.tool_result.errors)
        ok = not missing and not load_error
        return _c("Required data available", "Data", True, ok,
                  observed=f"missing bands {missing}" if missing else ("band loading failed" if load_error else
                           f"bands {manifest.required_bands} available in asset {scene.id}"),
                  expected="every required band exists in the selected asset")

    def _input_dependence(self, cap, manifest, scene: Scene, ctx: Context, base, work_dir) -> CheckResult:
        """Invert each required band in turn: a capability that truly uses a band must respond to it."""
        if base is None:
            return _c("Input dependence", "Data", True, False, observed="no baseline matrix")
        src = scene_path(self.settings, scene)
        idx = {b.name: b.index for b in scene.bands}
        notes, unused = [], []
        for band in manifest.required_bands:
            if band not in idx:
                continue
            variant = write_variant(src, work_dir / "variants" / f"invert_{band}.tif", "invert", idx[band])
            out = self._run_variant(cap, ctx, scene, variant, f"invert-{band}", work_dir)
            if not out.ok:
                notes.append(f"{band}: run failed ({out.exit_reason})")
                unused.append(band)
                continue
            other = _arr(out.tool_result)
            both = np.isfinite(base) & np.isfinite(other)
            changed = (np.isfinite(base) != np.isfinite(other)).any() or (
                both.any() and np.nanmax(np.abs(base[both] - other[both])) > 1e-6)
            notes.append(f"{band}: {'responds' if changed else 'no effect'}")
            if not changed:
                unused.append(band)
        return _c("Input dependence", "Data", True, not unused, observed="; ".join(notes),
                  expected="the matrix changes when any declared input band changes (no unused or fabricated inputs)")

    # ------------------------------------------------------------------ Analytical quality
    def _data_derived(self, cap, scene: Scene, ctx: Context, base, work_dir) -> CheckResult:
        """The matrix varies with the data and follows its geometry: mirroring the input mirrors the matrix."""
        if base is None:
            return _c("Data-derived matrix", "Analytical quality", True, False, observed="no matrix")
        valid = np.isfinite(base)
        frac = valid.mean()
        distinct = len(np.unique(base[valid])) if valid.any() else 0
        problems = []
        if frac < 0.5:
            problems.append(f"only {frac:.0%} of cells have data")
        if distinct < 2:
            problems.append("matrix is constant on a varied input")
        corr = None
        if not problems:
            flipped = write_variant(scene_path(self.settings, scene), work_dir / "variants" / "flip.tif", "flip")
            out = self._run_variant(cap, ctx, scene, flipped, "flip", work_dir)
            if not out.ok:
                problems.append(f"mirrored-input run failed ({out.exit_reason})")
            else:
                mirrored = _arr(out.tool_result)[:, ::-1]
                both = np.isfinite(base) & np.isfinite(mirrored)
                if both.sum() > 10 and np.std(base[both]) > 0 and np.std(mirrored[both]) > 0:
                    corr = float(np.corrcoef(base[both], mirrored[both])[0, 1])
                    if abs(corr) < 0.9:
                        problems.append(f"mirroring the input does not mirror the matrix (r={corr:.2f})")
        observed = f"{distinct} distinct values over {frac:.0%} of cells"
        if corr is not None:
            observed += f"; mirrored input -> mirrored matrix (r={corr:.3f})"
        return _c("Data-derived matrix", "Analytical quality", True, not problems,
                  observed="; ".join(problems) or observed,
                  expected="a varied matrix that follows the input's geometry")

    def _probes(self, cap: Path, manifest, source_hash: str, ok: bool, work_dir: Path) -> CheckResult:
        if not ok:
            return _c("Probe behaviour", "Analytical quality", True, False, observed="skipped: no result on the asset")
        notes, good_all = [], True
        for name, (scene, path) in probe_scenes().items():
            if not path.exists():
                return _c("Probe behaviour", "Analytical quality", True, False,
                          observed=f"probe raster {path.name} missing; run scripts/prepare_assets.py")
            ctx = build_context(self.settings, scene, manifest, source_hash, "probe", "harness", f"probe-{name}",
                                work_dir / f"probe-{name}", scene_file=path)
            out = self.runtime.run(cap, ctx, work_dir / f"probe-{name}")
            if not out.ok:
                good_all = False
                notes.append(f"{name}: run failed ({out.exit_reason}: {out.tool_result.errors[0].message[:80]})")
                continue
            m = _arr(out.tool_result)
            if name == "constant":
                v = m[np.isfinite(m)]
                good = v.size == 0 or float(np.ptp(v)) <= 1e-6 * (1 + float(np.abs(v).max()))
                notes.append(f"uniform input -> {'uniform' if good else 'non-uniform'} matrix" + ("" if v.size else " (all nodata)"))
            else:
                rows, cols = m.shape
                pr, pc = masked_quadrant()
                re_, ce = np.linspace(0, scene.height, rows + 1), np.linspace(0, scene.width, cols + 1)
                inside = np.outer(re_[1:] <= pr, ce[1:] <= pc)
                outside = ~np.outer(re_[:-1] < pr, ce[:-1] < pc)
                masked_ok = bool(np.isnan(m[inside]).all())
                out_valid = float(np.isfinite(m[outside]).mean())
                good = masked_ok and out_valid >= 0.9
                notes.append(f"masked input -> {int(np.isnan(m[inside]).sum())}/{int(inside.sum())} masked cells null, "
                             f"{out_valid:.0%} of unmasked cells valid")
            good_all = good_all and good
        return _c("Probe behaviour", "Analytical quality", True, good_all, observed="; ".join(notes),
                  expected="uniform input -> uniform matrix; nodata input -> null cells only there")

    @staticmethod
    def _metrics_consistent(tr: ToolResult, base) -> CheckResult:
        if base is None:
            return _c("Metrics consistency", "Analytical quality", True, False, observed="no matrix")
        m = {x.name: x.value for x in tr.metrics if x.source == "platform"}
        v = base[np.isfinite(base)]
        expected = {"valid_cells": float(v.size), "nodata_cells": float(base.size - v.size)}
        if v.size:
            expected.update(matrix_mean=v.mean(), matrix_min=v.min(), matrix_max=v.max(), matrix_std=v.std())
        bad = [f"{k}={m.get(k)} vs {round(val, 4)}" for k, val in expected.items()
               if k not in m or abs(m[k] - val) > 1e-3 * (1 + abs(val))]
        names = [x.name for x in tr.metrics]
        if len(set(names)) != len(names):
            bad.append("duplicate metric names")
        return _c("Metrics consistency", "Analytical quality", True, not bad,
                  observed="; ".join(bad) or f"{len(tr.metrics)} metrics; platform statistics match the matrix",
                  expected="matrix statistics recompute from the returned matrix; metric names unique and finite")

    @staticmethod
    def _zones_classes(tr: ToolResult, base) -> CheckResult:
        if base is None:
            return _c("Zones and classes consistency", "Analytical quality", True, False, observed="no matrix")
        if tr.zones is None and tr.classification is None:
            return _c("Zones and classes consistency", "Analytical quality", True, True,
                      observed="not provided (both are optional for this analysis)",
                      expected="when provided, zones and classes agree with the matrix")
        problems, notes = [], []
        valid = int(np.isfinite(base).sum())
        rows, cols = base.shape
        if tr.zones is not None:
            ids = [z.id for z in tr.zones]
            if len(set(ids)) != len(ids):
                problems.append("zone ids are not unique")
            for z in tr.zones:
                cells = z.cells
                if len(cells) != z.cell_count or any(not (0 <= r < rows and 0 <= c < cols) for r, c in cells):
                    problems.append(f"{z.id}: cells do not match cell_count or grid")
                    continue
                vals = [base[r, c] for r, c in cells]
                if any(not np.isfinite(x) for x in vals):
                    problems.append(f"{z.id}: includes nodata cells")
                    continue
                if abs(np.mean(vals) - z.mean_value) > 1e-3 * (1 + abs(z.mean_value)):
                    problems.append(f"{z.id}: mean_value {z.mean_value} != {np.mean(vals):.4f}")
                if valid and abs(100 * len(cells) / valid - z.share_pct) > 0.01:
                    problems.append(f"{z.id}: share_pct inconsistent")
            notes.append(f"{len(tr.zones)} zones agree with the matrix" if not problems else "")
        if tr.classification is not None:
            classes = tr.classification.classes
            ids = {c.id for c in classes}
            vals = base[np.isfinite(base)]
            stray = {float(x) for x in np.unique(vals)} - {float(i) for i in ids}
            if stray:
                problems.append(f"matrix has values that are not class ids: {sorted(stray)[:5]}")
            for c in classes:
                if int((vals == c.id).sum()) != c.cell_count:
                    problems.append(f"class {c.id} cell_count does not match the matrix")
            if valid and abs(sum(c.share_pct for c in classes) - 100) > 0.1:
                problems.append("class shares do not sum to 100%")
            notes.append(f"{len(classes)} classes agree with the matrix")
        return _c("Zones and classes consistency", "Analytical quality", True, not problems,
                  observed="; ".join(problems) or "; ".join(n for n in notes if n),
                  expected="zone cells, means and shares and class counts recompute from the matrix")

    # ------------------------------------------------------------------ Grounding
    @staticmethod
    def _allowed_numbers(tr: ToolResult) -> list[float]:
        allowed: list[float] = [x.value for x in tr.metrics]
        for z in tr.zones or []:
            allowed += [z.share_pct, z.mean_value, z.cell_count] + ([z.area_m2] if z.area_m2 is not None else [])
        if tr.classification:
            for c in tr.classification.classes:
                allowed += [c.id, c.cell_count, c.share_pct]
        allowed += [tr.grid_size.rows, tr.grid_size.cols]
        return allowed

    def _numbers_traced(self, scene: Scene, tr: ToolResult, ok: bool) -> CheckResult:
        if not ok:
            return _c("Numbers traced", "Grounding", True, False, observed="no result")
        allowed = self._allowed_numbers(tr)
        strip = {scene.label, scene.date_text, tr.layer_name, tr.analysis_type, tr.asset_id}
        strip |= {x.name for x in tr.metrics}
        strip |= {z.id for z in tr.zones or []} | {z.name for z in tr.zones or []}
        strip |= {c.label for c in tr.classification.classes} if tr.classification else set()
        strip = sorted((s for s in strip if s), key=len, reverse=True)
        untraced = []
        for label, text in [("summary", tr.summary)] + [(f.id, f.statement) for f in tr.findings]:
            for token in strip:
                text = text.replace(token, " ")
            for mt in NUMBER.finditer(text):
                s = mt.group()
                x, d = float(s), _decimals(s)
                if not any(abs(round(v, d) - x) < 1e-9 or abs(v - x) < 1e-9 or abs(round(abs(v), d) - abs(x)) < 1e-9
                           for v in allowed):
                    untraced.append(f"{label}: {s}")
        return _c("Numbers traced", "Grounding", True, not untraced,
                  observed="untraced: " + ", ".join(untraced[:10]) if untraced else
                  "every number in the summary and findings appears in the returned metrics, zones or classes",
                  expected="numerical claims trace to the returned analytical result")

    @staticmethod
    def _evidence_refs(tr: ToolResult, ok: bool) -> CheckResult:
        if not ok:
            return _c("Evidence references", "Grounding", True, False, observed="no result")
        known = {x.name for x in tr.metrics} | {z.id for z in tr.zones or []}
        known |= {f"class:{c.id}" for c in tr.classification.classes} if tr.classification else set()
        bad = [f"{f.id}: {[e for e in f.evidence if e not in known]}" for f in tr.findings
               if not f.evidence or any(e not in known for e in f.evidence)]
        return _c("Evidence references", "Grounding", True, bool(tr.findings) and not bad,
                  observed=f"unsupported evidence: {bad}" if bad else f"{len(tr.findings)} findings, each citing returned metrics, zones or classes",
                  expected="every finding cites evidence present in the ToolResult")

    @staticmethod
    def _no_prescriptions(tr: ToolResult) -> CheckResult:
        hits = []
        texts = [("summary", tr.summary)] + [(f.id, f.statement) for f in tr.findings]
        texts += [(f"next step {i + 1}", s.description) for i, s in enumerate(tr.next_steps)]
        for label, text in texts:
            for pat in PRESCRIPTIVE:
                m = pat.search(text)
                if m:
                    hits.append(f"{label}: '{m.group()}'")
        return _c("No unsupported prescriptions", "Grounding", True, not hits,
                  observed="prescriptive wording: " + ", ".join(hits) if hits else
                  f"no prescriptions; {len(tr.next_steps)} next steps, all follow-up analysis or human inspection",
                  expected="no agronomic prescriptions; next steps are analysis follow-ups or human inspection")

    # ------------------------------------------------------------------ User value
    @staticmethod
    def _answers_intent(intent, manifest, tr, ok, judge) -> CheckResult:
        if not ok:
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

    def _useful(self, scene: Scene, tr: ToolResult, ok: bool) -> CheckResult:
        if not ok:
            return _c("Useful result", "User value", False, False, observed="no result")
        limit = self.settings.harness.summary_max_chars
        problems = []
        if len(tr.summary) > limit:
            problems.append(f"summary is {len(tr.summary)} chars (limit {limit})")
        if scene.label not in tr.summary:
            problems.append("summary does not name the asset")
        if not tr.next_steps:
            problems.append("no next steps")
        return _c("Useful result", "User value", False, not problems,
                  observed="; ".join(problems) or f"summary names the asset; {len(tr.findings)} findings; "
                                                  f"{len(tr.next_steps)} next steps; layer '{tr.layer_name}'",
                  expected=f"a summary of at most {limit} chars naming the asset, findings, next steps and a layer")

    # ------------------------------------------------------------------ Governance
    @staticmethod
    def _not_duplicate(manifest: CapabilityManifest, snapshot: Registry) -> CheckResult:
        clash = [e for e in snapshot.capabilities
                 if e.id == manifest.id or manifest.analysis_key in (e.analysis_key, *e.aliases)]
        return _c("Not a duplicate", "Governance", True, not clash,
                  observed=f"clashes with {clash[0].id} {clash[0].version}" if clash else f"'{manifest.analysis_key}' is new",
                  expected="no committed capability with the same id or analysis key")

    @staticmethod
    def _provenance(cap: Path, start_hash: str, ctx: Context, tr: ToolResult, ok: bool) -> CheckResult:
        """persisted file bytes -> SHA-256 -> Context -> ToolResult provenance -> EvaluationReport."""
        end_hash = _sha(cap)
        problems = []
        if end_hash != start_hash:
            problems.append("the capability file changed during evaluation")
        if ctx.content_hash != start_hash:
            problems.append("Context content_hash is not the SHA-256 of the persisted file bytes")
        if not ok or tr.provenance is None:
            problems.append("no ToolResult provenance")
        elif tr.provenance.content_hash != start_hash:
            problems.append("ToolResult provenance hash is not the SHA-256 of the persisted file bytes")
        elif (tr.provenance.capability_id, tr.provenance.capability_version, tr.provenance.asset_id) != (
                ctx.capability_id, ctx.capability_version, ctx.asset_id):
            problems.append("ToolResult provenance does not match the Context")
        return _c("Provenance chain", "Governance", True, not problems,
                  observed="; ".join(problems) or f"file bytes = Context = ToolResult = report: {start_hash[:16]}",
                  expected="persisted file SHA-256 carried unchanged through Context, ToolResult and report")
