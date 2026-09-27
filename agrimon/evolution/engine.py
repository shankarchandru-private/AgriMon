"""The create path: Generate -> Admit -> Stage and execute -> Evaluate -> Commit or Quarantine.

Everything happens under workspace/staging/<attempt_id>/ until the registry's atomic commit.
A failed candidate is quarantined and the next one is generated with the failure as feedback.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from agrimon.config import Settings
from agrimon.contracts import (
    AttemptRecord,
    CapabilityManifest,
    EvaluationReport,
    Intent,
    Registry,
    RegistryEntry,
    Scene,
    StateChange,
    ToolResult,
)
from agrimon.evolution.admission import admit
from agrimon.evolution.candidate import content_hash, make_candidate
from agrimon.evolution.generator import GenerationError, Generator
from agrimon.evolution.quarantine import move_orphan, quarantine_attempt, write_attempt
from agrimon.harness import Harness
from agrimon.observability import bind, get_logger
from agrimon.registry import CommitError, DuplicateCapability, RegistryStore
from agrimon.runtime import Runtime, build_context

log = get_logger("evolution")

JUDGE_PROMPT = """You rate how well an analysis output answers a user's question about a raster image.
Reply with JSON only: {"score": number between 0 and 1, "reason": one short sentence}.
Judge relevance of the computed analysis to the question, not writing style."""


@dataclass
class EvolutionOutcome:
    committed: bool
    attempts: list[str] = field(default_factory=list)
    entry: Optional[RegistryEntry] = None
    manifest: Optional[CapabilityManifest] = None
    report: Optional[EvaluationReport] = None
    run_id: Optional[str] = None
    tool_result: Optional[ToolResult] = None
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None
    quarantined: list[str] = field(default_factory=list)


class EvolutionEngine:
    def __init__(self, settings: Settings, llm, registry: RegistryStore, runtime: Runtime, harness: Harness):
        self.settings = settings
        self.llm = llm
        self.registry = registry
        self.runtime = runtime
        self.harness = harness
        self.generator = Generator(llm)

    # ------------------------------------------------------------------ judge for "Answers the intent"
    def _judge(self, question: str, manifest: CapabilityManifest, tr: ToolResult):
        if self.llm is None:
            return None
        payload = {"question": question, "analysis": manifest.name, "description": manifest.description,
                   "summary": tr.summary, "findings": [f.statement for f in tr.findings]}
        raw = self.llm.complete_json("intent", JUDGE_PROMPT, json.dumps(payload))
        return float(raw.get("score", 0)), str(raw.get("reason", ""))[:200]

    # ------------------------------------------------------------------ main loop
    def evolve(
        self, request_id: str, intent: Intent, scene: Scene, snapshot: Registry, on_state: Callable[[str, str], None]
    ) -> EvolutionOutcome:
        outcome = EvolutionOutcome(committed=False)
        feedback: str | None = None
        for n in range(1, self.settings.evolution.max_retries + 2):
            attempt_id = f"{request_id}-c{n}"
            outcome.attempts.append(attempt_id)
            stage_dir = self.settings.staging_dir / attempt_id
            record = AttemptRecord(attempt_id=attempt_id, request_id=request_id, candidate_number=n,
                                   analysis_key=intent.analysis_key)
            with bind(attempt_id=attempt_id):
                try:
                    result = self._attempt(n, record, stage_dir, intent, scene, snapshot, feedback, on_state, outcome)
                except Exception as exc:  # an internal error ends this attempt only
                    log.exception("attempt crashed")
                    self._fail(outcome, record, stage_dir, record.failure_stage or "internal",
                               f"internal error: {type(exc).__name__}: {exc}")
                    result = "stop"
            if result == "committed":
                return outcome
            if result == "stop":
                break
            feedback = f"stage '{record.failure_stage}': {record.failure_reason}"
        return outcome

    def _fail(self, outcome: EvolutionOutcome, record: AttemptRecord, stage_dir: Path, stage: str, reason: str) -> None:
        record.failure_stage, record.failure_reason = stage, reason
        outcome.failure_stage, outcome.failure_reason = stage, reason
        dest = quarantine_attempt(self.settings, stage_dir, record)
        outcome.quarantined.append(dest.name)

    def _attempt(self, n, record, stage_dir, intent, scene, snapshot, feedback, on_state, outcome) -> str:
        def state(name: str, note: str = "") -> None:
            record.history.append(StateChange(state=name, note=note))
            write_attempt(stage_dir, record)
            on_state(name, f"candidate {n}" + (f": {note}" if note else ""))

        # Generate --------------------------------------------------------------
        state("generating")
        try:
            gen = self.generator.generate(intent, scene, feedback)
        except GenerationError as exc:
            self._fail(outcome, record, stage_dir, "generating", str(exc))
            return "retry"
        try:
            source, manifest = make_candidate(gen, intent.analysis_key, intent.analysis_key, "generated",
                                              source_request_id=record.request_id)
        except ValueError as exc:  # manifest validation
            self._fail(outcome, record, stage_dir, "generating", f"candidate manifest invalid: {exc}")
            return "retry"
        cand_dir = stage_dir / "candidate"
        cand_dir.mkdir(parents=True, exist_ok=True)
        cap_file = cand_dir / "capability.py"
        cap_file.write_text(source, encoding="utf-8")
        (cand_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        record.content_hash = content_hash(source)

        # Validate: admission ------------------------------------------------------
        state("admitting")
        violations = admit(source, manifest, scene, snapshot, self.settings.evolution.max_source_bytes)
        record.admission_violations = violations
        if violations:
            self._fail(outcome, record, stage_dir, "admitting", "; ".join(violations))
            return "stop" if any(v.startswith("rule 7") for v in violations) else "retry"

        # Validate: staged execution ------------------------------------------------
        state("executing_staged")
        run_id = f"{record.attempt_id}-run"
        record.run_id = run_id
        ctx = build_context(self.settings, scene, manifest, record.content_hash, "staged", record.request_id,
                            run_id, stage_dir / "run")
        run = self.runtime.run(cap_file, ctx, stage_dir / "run")
        if not run.ok:
            msg = "; ".join(f"{e.code}: {e.message}" for e in run.tool_result.errors) or run.exit_reason
            self._fail(outcome, record, stage_dir, "executing_staged", msg)
            return "retry"

        # Evaluate ------------------------------------------------------------------
        state("evaluating")
        report = self.harness.evaluate(
            capability_file=cap_file, manifest=manifest, first_run=run, context=ctx, scene=scene, snapshot=snapshot,
            admission_violations=violations, intent=intent, work_dir=stage_dir / "harness", subject="candidate",
            judge=self._judge,
        )
        (stage_dir / "evaluation.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        record.verdict = report.verdict
        outcome.report, outcome.manifest, outcome.run_id, outcome.tool_result = report, manifest, run_id, run.tool_result
        if report.verdict != "pass":
            failed = [f"{c.name} ({c.observed})" for c in report.checks if c.blocking and not c.passed]
            self._fail(outcome, record, stage_dir, "evaluating", "blocking checks failed: " + "; ".join(failed))
            return "retry"

        # Commit ------------------------------------------------------------------------
        state("committing")
        try:
            entry = self.registry.commit(cand_dir, manifest, report, record.attempt_id)
        except DuplicateCapability as exc:
            self._fail(outcome, record, stage_dir, "committing", str(exc))
            return "stop"
        except CommitError as exc:
            if exc.orphan is not None and exc.orphan.exists():
                move_orphan(self.settings, exc.orphan, into=stage_dir)
            self._fail(outcome, record, stage_dir, "committing", str(exc))
            return "stop"
        record.outcome = "committed"
        record.history.append(StateChange(state="committed", note=f"{entry.id} {entry.version}"))
        outcome.committed, outcome.entry = True, entry
        outcome.failure_stage = outcome.failure_reason = None
        shutil.rmtree(stage_dir, ignore_errors=True)
        log.info("evolution committed", extra={"fields": {"capability": entry.id, "candidate": n}})
        return "committed"
