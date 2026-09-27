"""H1: the core invariant.

A failed capability generation, execution, evaluation, or persistence attempt cannot corrupt
committed capabilities or prevent subsequent requests from being processed.

Every test: fingerprint committed state -> inject the failure -> assert (a) fingerprint unchanged,
(b) a quarantine or failure record with the reason exists, (c) the next match-path request succeeds.
"""

import copy
import os
import threading

import pytest

from agrimon.config import load_settings
from agrimon.orchestrator.service import AgriMonService
from agrimon.registry import DuplicateCapability, RegistryStore

from tests.conftest import FakeLLM, fixture_json, make_project

FAST = {"evolution": {"max_retries": 0}}


class SimulatedCrash(BaseException):
    """Stands in for the process dying: not caught by any 'except Exception'."""


def exg(**changes):
    g = copy.deepcopy(fixture_json("generation_exg.json"))
    g.update(changes)
    return g


def service(tmp_path, generation, overrides=FAST):
    root = make_project(tmp_path)
    llm = FakeLLM(intent=[fixture_json("intent_vegetation.json")], generation=generation)
    return AgriMonService(load_settings(root, overrides=overrides, read_env=False), llm=llm)


def assert_invariant(svc, before):
    assert svc.registry.fingerprint() == before, "committed state changed"
    assert svc.registry.verify() == []
    svc.llm.responses["intent"] = [fixture_json("intent_brightness.json")]
    nxt = svc.run_sync("Give me a brightness overview", "eros_forest_valley")
    assert nxt.state == "completed" and nxt.answer.source == "existing", nxt.failure


def quarantined(svc):
    return sorted(p.name for p in svc.settings.quarantine_dir.iterdir())


def ask(svc):
    return svc.run_sync("Where does vegetation appear?", "eros_reservoir_farmland")


# 1 ---------------------------------------------------------------------------------------------
def test_generation_fails(tmp_path):
    svc = service(tmp_path, [RuntimeError("rate limited")], overrides={})  # default: 2 retries
    before = svc.registry.fingerprint()
    rec = ask(svc)
    assert rec.state == "failed" and rec.failure.stage == "generating" and "rate limited" in rec.failure.reason
    assert len(rec.attempts) == 3 and rec.failure.committed_state_unchanged is True
    assert len(quarantined(svc)) == 3
    assert_invariant(svc, before)


# 2 ---------------------------------------------------------------------------------------------
def test_admission_fails(tmp_path):
    bad = exg(compute_values_source="import os\n" + exg()["compute_values_source"])
    svc = service(tmp_path, [bad])
    before = svc.registry.fingerprint()
    rec = ask(svc)
    assert rec.failure.stage == "admitting" and "rule 3" in rec.failure.reason
    q = svc.settings.quarantine_dir / quarantined(svc)[0]
    assert not (q / "run").exists(), "a rejected candidate must never execute"
    assert_invariant(svc, before)


# 3 ---------------------------------------------------------------------------------------------
def test_execution_crashes(tmp_path):
    svc = service(tmp_path, [exg(compute_values_source="def compute_values(bands, params):\n    raise ValueError('boom')\n")])
    before = svc.registry.fingerprint()
    rec = ask(svc)
    assert rec.failure.stage == "executing_staged" and "boom" in rec.failure.reason
    assert_invariant(svc, before)


# 4 ---------------------------------------------------------------------------------------------
def test_execution_hangs(tmp_path):
    hang = exg(compute_values_source="def compute_values(bands, params):\n    while True:\n        pass\n")
    svc = service(tmp_path, [hang], overrides={**FAST, "runtime": {"timeout_seconds": 2}})
    before = svc.registry.fingerprint()
    rec = ask(svc)
    assert rec.failure.stage == "executing_staged" and "timeout" in rec.failure.reason
    assert_invariant(svc, before)


# 5 ---------------------------------------------------------------------------------------------
def test_malformed_toolresult(tmp_path, monkeypatch):
    """Simulates an admission gap: a candidate that bypasses the template's result structure."""
    import agrimon.evolution.engine as engine

    real = engine.make_candidate

    def tampered(*a, **k):
        source, manifest = real(*a, **k)
        return source + "\n\ndef execute(context):\n    return {'status': 'success', 'description': 'no grid'}\n", manifest

    monkeypatch.setattr(engine, "make_candidate", tampered)
    monkeypatch.setattr(engine, "admit", lambda *a, **k: [])
    svc = service(tmp_path, [exg()])
    before = svc.registry.fingerprint()
    rec = ask(svc)
    assert rec.failure.stage == "executing_staged" and "malformed_result" in rec.failure.reason
    assert_invariant(svc, before)


# 6 ---------------------------------------------------------------------------------------------
def test_evaluation_fails(tmp_path):
    rules = exg()["finding_rules"] + [{"id": "F4", "template": "About 42% of the field is healthy crop, mean {metric.mean_value}."}]
    svc = service(tmp_path, [exg(finding_rules=rules)])
    before = svc.registry.fingerprint()
    rec = ask(svc)
    assert rec.failure.stage == "evaluating" and "Numbers traced" in rec.failure.reason
    q = svc.settings.quarantine_dir / quarantined(svc)[0]
    assert (q / "evaluation.json").exists() and '"verdict": "fail"' in (q / "evaluation.json").read_text()
    assert_invariant(svc, before)


# 7 ---------------------------------------------------------------------------------------------
def test_persistence_fails_before_commit_point(tmp_path, monkeypatch):
    svc = service(tmp_path, [exg()])
    before = svc.registry.fingerprint()

    def crash(self, registry):
        raise SimulatedCrash()

    monkeypatch.setattr(RegistryStore, "_write_index", crash)
    with pytest.raises(SimulatedCrash):
        ask(svc)
    orphan = svc.settings.capabilities_dir / "vegetation_proxy_rgb" / "1.0.0"
    assert orphan.exists(), "the crash left a copied folder that the index does not list"
    monkeypatch.undo()

    restarted = AgriMonService(svc.settings, llm=svc.llm)  # restart runs recovery
    assert restarted.recovery["orphans_quarantined"] and restarted.recovery["interrupted_attempts_quarantined"]
    assert not orphan.exists()
    assert_invariant(restarted, before)


# 8 ---------------------------------------------------------------------------------------------
def test_persistence_fails_at_commit_point(tmp_path, monkeypatch):
    import agrimon.registry.store as store

    svc = service(tmp_path, [exg()])
    before = svc.registry.fingerprint()
    real_replace = os.replace

    def failing_replace(src, dst):
        if str(dst).endswith("registry.json"):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", failing_replace)
    rec = ask(svc)
    monkeypatch.undo()
    assert rec.failure.stage == "committing" and "disk full" in rec.failure.reason
    assert svc.registry.load().registry_version == 1
    q = svc.settings.quarantine_dir / quarantined(svc)[0]
    assert (q / "orphan" / "capability.py").exists()
    assert_invariant(svc, before)


# 9 ---------------------------------------------------------------------------------------------
def test_concurrent_duplicate_commits(tmp_path):
    from agrimon.contracts import EvaluationReport, GenerationOutput
    from agrimon.evolution.candidate import content_hash, make_candidate

    root = make_project(tmp_path)
    store = RegistryStore(load_settings(root, read_env=False))
    gen = GenerationOutput.model_validate(exg())
    staged = []
    for i in range(2):
        source, manifest = make_candidate(gen, "vegetation_proxy_rgb", "vegetation_proxy_rgb", "generated")
        d = tmp_path / f"cand{i}"
        d.mkdir()
        (d / "capability.py").write_text(source)
        report = EvaluationReport(report_id=f"r{i}", subject="candidate", capability_id=manifest.id,
                                  capability_version="1.0.0", content_hash=content_hash(source), harness_version="t",
                                  config_version="t", checks=[], categories=[], blocking_passed=13, blocking_total=13,
                                  warnings_raised=0, overall_score=1.0, verdict="pass")
        staged.append((d, manifest, report, f"att{i}"))
    barrier, results = threading.Barrier(2), []

    def commit(args):
        barrier.wait()
        try:
            results.append(store.commit(*args).id)
        except DuplicateCapability as exc:
            results.append(f"duplicate: {exc}")

    threads = [threading.Thread(target=commit, args=(s,)) for s in staged]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.startswith("duplicate") for r in results) == [False, True]
    reg = store.load()
    assert reg.registry_version == 2 and [e.id for e in reg.capabilities].count("vegetation_proxy_rgb") == 1
    assert store.verify() == [] and store.find_orphans() == []
