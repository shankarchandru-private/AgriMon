"""The application service: startup checks, the request lifecycle, and read models for the UI.

Question -> Intent -> Match -> Execute existing / Generate new -> Validate -> Evaluate
-> Commit or Quarantine -> Answer + Visualize.
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from agrimon.answers import compose, evaluation_summary
from agrimon.catalog import load_catalog, scene_path, validate_catalog
from agrimon.config import Settings
from agrimon.config.llm import make_llm_client
from agrimon.contracts import (
    AttemptRecord,
    EvaluationReport,
    FailureContext,
    RequestRecord,
    StateChange,
    ToolResult,
)
from agrimon.evolution.candidate import file_hash
from agrimon.evolution.engine import EvolutionEngine
from agrimon.evolution.quarantine import move_orphan, recover_staging
from agrimon.harness import Harness
from agrimon.intent import IntentError, IntentResolver
from agrimon.matching import match
from agrimon.observability import bind, get_logger, setup_logging
from agrimon.registry import RegistryStore
from agrimon.runtime import Runtime, build_context

log = get_logger("service")


def _new_request_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


class AgriMonService:
    def __init__(self, settings: Settings, llm=None, use_default_llm: bool = True):
        self.settings = settings
        settings.ensure_runtime_dirs()
        setup_logging(settings.logs_dir)
        self.llm = llm if llm is not None else (make_llm_client(settings) if use_default_llm else None)
        self.catalog = load_catalog(settings)
        self.catalog_problems = validate_catalog(settings, self.catalog)
        self.registry = RegistryStore(settings)
        self.runtime = Runtime(settings)
        self.harness = Harness(settings, self.runtime)
        self.resolver = IntentResolver(self.llm)
        self.engine = EvolutionEngine(settings, self.llm, self.registry, self.runtime, self.harness)
        self.recovery = self._startup_recovery()
        self._records: dict[str, RequestRecord] = {}
        self._lock = threading.Lock()
        self._evolution_slot = threading.Semaphore(settings.requests.max_concurrent_evolutions)
        self._pool = ThreadPoolExecutor(max_workers=settings.requests.worker_threads, thread_name_prefix="request")

    # ------------------------------------------------------------------ startup
    def _startup_recovery(self) -> dict:
        self.registry.remove_stale_temp()
        orphans = [str(move_orphan(self.settings, p)) for p in self.registry.find_orphans()]
        interrupted = [str(p) for p in recover_staging(self.settings)]
        problems = self.registry.verify()
        if orphans or interrupted or problems:
            log.warning("startup recovery", extra={"fields": {"orphans": orphans, "interrupted": interrupted,
                                                              "registry_problems": problems}})
        return {"orphans_quarantined": orphans, "interrupted_attempts_quarantined": interrupted,
                "registry_problems": problems}

    def health(self) -> dict:
        reg = self.registry.load()
        spec = {}
        if self.settings.app_spec_path.exists():
            raw = json.loads(self.settings.app_spec_path.read_text(encoding="utf-8"))
            spec = {k: raw.get(k) for k in ("app", "version", "evolution_level", "mode")}
        return {
            "app_spec": spec,
            "ok": not self.catalog_problems and not self.recovery["registry_problems"],
            "config_version": self.settings.config_version,
            "llm_configured": self.llm is not None,
            "models": {"intent": self.settings.llm.intent_model, "generation": self.settings.llm.generation_model},
            "scenes": [{"id": s.id, "label": s.label, "bands": s.band_names} for s in self.catalog.scenes],
            "catalog_problems": self.catalog_problems,
            "registry_version": reg.registry_version,
            "capabilities": len(reg.capabilities),
            "recovery": self.recovery,
        }

    def scene_file(self, scene_id: str) -> Path:
        return scene_path(self.settings, self.catalog.scene(scene_id))

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)

    # ------------------------------------------------------------------ records
    def _save(self, rec: RequestRecord) -> None:
        path = self.settings.requests_dir / f"{rec.request_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def _state(self, rec: RequestRecord, state: str, note: str = "") -> None:
        with self._lock:
            rec.state = state
            rec.history.append(StateChange(state=state, note=note))
            self._save(rec)
        log.info(f"state -> {state}", extra={"fields": {"note": note}})

    def get_request(self, request_id: str) -> RequestRecord | None:
        with self._lock:
            if request_id in self._records:
                return self._records[request_id].model_copy(deep=True)
        path = self.settings.requests_dir / f"{request_id}.json"
        if path.exists() and path.parent == self.settings.requests_dir:
            return RequestRecord.model_validate_json(path.read_text(encoding="utf-8"))
        return None

    # ------------------------------------------------------------------ submit
    def submit(self, question: str, scene_id: str) -> str:
        self.catalog.scene(scene_id)  # KeyError for unknown scenes
        rec = RequestRecord(request_id=_new_request_id(), question=question.strip(), scene_id=scene_id, state="received")
        rec.history.append(StateChange(state="received"))
        with self._lock:
            self._records[rec.request_id] = rec
            self._save(rec)
        self._pool.submit(self._process, rec)
        return rec.request_id

    def run_sync(self, question: str, scene_id: str) -> RequestRecord:
        """Processes one request on the calling thread (scripts and tests)."""
        self.catalog.scene(scene_id)
        rec = RequestRecord(request_id=_new_request_id(), question=question.strip(), scene_id=scene_id, state="received")
        with self._lock:
            self._records[rec.request_id] = rec
        self._process(rec)
        return self.get_request(rec.request_id)

    def _fail(self, rec: RequestRecord, stage: str, reason: str, unchanged: bool | None = None, quarantined=None) -> None:
        rec.failure = FailureContext(stage=stage, reason=reason, committed_state_unchanged=unchanged,
                                     quarantined_attempts=quarantined or [])
        self._state(rec, "failed", f"{stage}: {reason}"[:300])

    # ------------------------------------------------------------------ the pipeline
    def _process(self, rec: RequestRecord) -> None:
        with bind(request_id=rec.request_id):
            try:
                self._pipeline(rec)
            except Exception as exc:  # last line of defence: a request never takes the service down
                log.exception("request crashed")
                self._fail(rec, rec.state, f"unexpected error: {type(exc).__name__}: {exc}")

    def _pipeline(self, rec: RequestRecord) -> None:
        scene = self.catalog.scene(rec.scene_id)
        snapshot = self.registry.snapshot()  # pinned for this request

        # Intent -----------------------------------------------------------------
        self._state(rec, "resolving_intent")
        try:
            rec.intent = self.resolver.resolve(rec.question, scene, snapshot)
        except IntentError as exc:
            self._fail(rec, "resolving_intent", str(exc))
            return

        # Match (deterministic) ------------------------------------------------------
        self._state(rec, "matching", f"analysis key '{rec.intent.analysis_key}'")
        rec.match = match(rec.intent, scene, snapshot)
        self._state(rec, "matched" if rec.match.matched else "no_match", f"{rec.match.rule}: {rec.match.reason}")

        if rec.match.matched:
            self._execute_existing(rec, scene, snapshot)
        else:
            self._generate_new(rec, scene, snapshot)

    def _execute_existing(self, rec, scene, snapshot) -> None:
        entry = next(e for e in snapshot.capabilities
                     if e.id == rec.match.capability_id and e.version == rec.match.capability_version)
        manifest = self.registry.read_manifest(entry)
        run_id = f"{rec.request_id}-run"
        run_dir = self.settings.runs_dir / run_id
        self._state(rec, "executing", f"{entry.id} {entry.version}")
        cap_file = self.registry.capability_file(entry)
        if not self.registry.integrity_ok(entry):  # persisted bytes must still hash to the registered value
            self._fail(rec, "executing", f"{entry.id} {entry.version} failed its integrity check: the committed file "
                       "no longer matches its registered content hash, so it was not run", unchanged=True)
            return
        ctx = build_context(self.settings, scene, manifest, file_hash(cap_file), "committed", rec.request_id,
                            run_id, run_dir, question=rec.question)
        with bind(run_id=run_id):
            run = self.runtime.run(cap_file, ctx, run_dir)
        if not run.ok:
            msg = "; ".join(f"{e.code}: {e.message}" for e in run.tool_result.errors) or run.exit_reason
            self._fail(rec, "executing", f"{entry.id} {entry.version} failed: {msg}", unchanged=True)
            return
        report = self.registry.read_evaluation(entry)
        rec.answer = compose("existing", entry.id, entry.version, run_id, run.tool_result, report,
                             f"cap:{entry.id}:{entry.version}")
        self._state(rec, "completed", f"answered by {entry.id} {entry.version}")

    def _generate_new(self, rec, scene, snapshot) -> None:
        if not self._evolution_slot.acquire(timeout=self.settings.runtime.timeout_seconds * 10):
            self._fail(rec, "generating", "another evolution is still running; try again shortly")
            return
        try:
            before = self.registry.fingerprint()
            outcome = self.engine.evolve(rec.request_id, rec.intent, scene, snapshot,
                                         on_state=lambda s, note: self._state(rec, s, note))
            rec.attempts = outcome.attempts
            if not outcome.committed:
                unchanged = self.registry.fingerprint() == before
                self._fail(rec, outcome.failure_stage or "generating", outcome.failure_reason or "no candidate passed",
                           unchanged=unchanged, quarantined=outcome.quarantined)
                return
            e = outcome.entry
            rec.answer = compose("new", e.id, e.version, outcome.run_id, outcome.tool_result, outcome.report,
                                 f"cap:{e.id}:{e.version}")
            self._state(rec, "completed", f"new capability {e.id} {e.version} committed and answered")
        finally:
            self._evolution_slot.release()

    # ------------------------------------------------------------------ read models
    def list_capabilities(self) -> dict:
        reg = self.registry.load()
        generated = [e for e in reg.capabilities if e.origin == "generated"]
        newest = max(generated, key=lambda e: e.committed_at).id if generated else None
        return {
            "registry_version": reg.registry_version,
            "capabilities": [{**e.model_dump(), "is_new": e.id == newest} for e in reg.capabilities],
        }

    def capability_detail(self, cap_id: str, version: str) -> dict | None:
        entry = self.registry.find(cap_id, version)
        if entry is None:
            return None
        report = self.registry.read_evaluation(entry)
        creating = None
        if entry.source_request_id:
            src = self.get_request(entry.source_request_id)
            if src and src.answer:
                creating = {"request_id": src.request_id, "question": src.question, "scene_id": src.scene_id,
                            "summary": src.answer.tool_result.summary}
        return {
            "entry": entry.model_dump(),
            "manifest": self.registry.read_manifest(entry).model_dump(),
            "evaluation": evaluation_summary(report, f"cap:{entry.id}:{entry.version}"),
            "source": self.registry.capability_file(entry).read_text(encoding="utf-8"),
            "creating_run": creating,
        }

    def get_run(self, run_id: str) -> dict | None:
        path = self.settings.runs_dir / run_id / "toolresult.json"
        if run_id != Path(run_id).name or not path.exists():
            return None
        return ToolResult.model_validate_json(path.read_text(encoding="utf-8")).model_dump()

    def list_evaluations(self) -> list[dict]:
        rows = []
        for e in self.registry.load().capabilities:
            r = self.registry.read_evaluation(e)
            rows.append({**evaluation_summary(r, None), "report_ref": f"cap:{e.id}:{e.version}", "kind": "committed",
                         "title": e.name, "capability_id": e.id, "version": e.version, "origin": e.origin,
                         "stage": "committed"})
        qdir = self.settings.quarantine_dir
        for d in sorted((p for p in qdir.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
            att = d / "attempt.json"
            if not att.exists():
                continue
            a = AttemptRecord.model_validate_json(att.read_text(encoding="utf-8"))
            row = {"report_ref": f"att:{d.name}", "kind": "quarantined", "title": f"{a.analysis_key} (candidate {a.candidate_number})",
                   "capability_id": a.analysis_key, "version": "-", "origin": "generated",
                   "stage": a.failure_stage, "reason": a.failure_reason, "verdict": "rejected"}
            ev = d / "evaluation.json"
            if ev.exists():
                row.update({k: v for k, v in evaluation_summary(EvaluationReport.model_validate_json(ev.read_text()), None).items()
                            if k not in ("verdict", "report_ref")})
                row["verdict"] = "fail"
            rows.append(row)
        return rows

    def get_evaluation(self, report_ref: str) -> dict | None:
        kind, _, rest = report_ref.partition(":")
        if kind == "cap":
            cap_id, _, version = rest.partition(":")
            entry = self.registry.find(cap_id, version)
            if entry is None:
                return None
            return {"kind": "committed", "report": self.registry.read_evaluation(entry).model_dump()}
        if kind == "att" and rest == Path(rest).name:
            d = self.settings.quarantine_dir / rest
            if not d.exists():
                return None
            att = json.loads((d / "attempt.json").read_text()) if (d / "attempt.json").exists() else None
            ev = d / "evaluation.json"
            report = EvaluationReport.model_validate_json(ev.read_text()).model_dump() if ev.exists() else None
            return {"kind": "quarantined", "attempt": att, "report": report}
        return None
