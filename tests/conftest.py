"""Shared fixtures: a temporary copy of the project in its seed state, and a stub LLM."""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"


def make_project(tmp_path: Path, seed: bool = True) -> Path:
    """Copies config, assets, web and (optionally) the committed seed into a fresh project root."""
    root = tmp_path / "project"
    root.mkdir()
    shutil.copy2(REPO / "agrimon.toml", root / "agrimon.toml")
    shutil.copytree(REPO / "assets", root / "assets")
    shutil.copytree(REPO / "web", root / "web")
    if (REPO / "app_spec.json").exists():
        shutil.copy2(REPO / "app_spec.json", root / "app_spec.json")
    (root / "capabilities").mkdir()
    if seed:
        src = REPO / "capabilities"
        for item in src.iterdir():
            if item.is_dir():
                shutil.copytree(item, root / "capabilities" / item.name)
            elif item.name == "registry.json":
                shutil.copy2(item, root / "capabilities" / item.name)
    return root


class FakeLLM:
    """Returns canned JSON per role. Each entry may be a dict or an Exception to raise."""

    def __init__(self, intent=None, generation=None):
        self.responses = {"intent": list(intent or []), "generation": list(generation or [])}
        self.calls = {"intent": 0, "generation": 0}
        self.prompts: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def complete_json(self, role: str, system: str, user: str) -> dict:
        with self._lock:
            self.calls[role] += 1
            self.prompts.append((role, user))
            queue = self.responses[role]
            if not queue:
                raise AssertionError(f"FakeLLM: no canned {role} response left")
            item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            from agrimon.config.llm import LLMError

            raise LLMError(str(item))
        return json.loads(json.dumps(item))


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / "llm" / name).read_text())


def evaluate_candidate(tmp_path: Path, gen: dict, scene_id: str = "eros_reservoir_farmland", *, raw_source=None,
                       context_hash=None, after_context=None, fingerprint=None, capability_id="candidate_key"):
    """Persists a candidate, runs it once and evaluates it with the real harness (admission not applied).

    raw_source: bytes to persist instead of the assembled source (for example CRLF line endings).
    context_hash: override the hash put in the Context (to test the provenance chain).
    after_context: callable(cap_file) run after the Context is built (for example to tamper with the file).
    Returns (report, run_outcome).
    """
    from agrimon.catalog import load_catalog
    from agrimon.config import load_settings
    from agrimon.contracts import GenerationOutput, Registry
    from agrimon.evolution.candidate import file_hash, make_candidate
    from agrimon.harness import Harness
    from agrimon.runtime import Runtime, build_context

    root = make_project(tmp_path, seed=False)
    settings = load_settings(root, read_env=False)
    scene = load_catalog(settings).scene(scene_id)
    source, manifest = make_candidate(GenerationOutput.model_validate(gen), capability_id, capability_id, "generated")
    cap = tmp_path / "cand" / "capability.py"
    cap.parent.mkdir(parents=True, exist_ok=True)
    cap.write_bytes(raw_source if raw_source is not None else source.encode("utf-8"))
    ctx = build_context(settings, scene, manifest, context_hash or file_hash(cap), "staged", "req", "run",
                        tmp_path / "run", question="test question")
    if after_context:
        after_context(cap)
    runtime = Runtime(settings)
    run = runtime.run(cap, ctx, tmp_path / "run")
    report = Harness(settings, runtime).evaluate(
        capability_file=cap, manifest=manifest, first_run=run, context=ctx, scene=scene, snapshot=Registry(),
        admission_violations=[], intent=None, work_dir=tmp_path / "harness", committed_fingerprint=fingerprint)
    return report, run


def failed_checks(report) -> list[str]:
    return [c.name for c in report.checks if c.blocking and not c.passed]


def gen_fixture(name: str, **changes) -> dict:
    g = fixture_json(name)
    g.update(changes)
    return g
