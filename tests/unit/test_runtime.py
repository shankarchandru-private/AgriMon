"""Capabilities run in a guarded subprocess: hangs, crashes, malformed results and forbidden operations
become failed ToolResults, and the platform keeps running."""

import os

import pytest

from agrimon.catalog import load_catalog
from agrimon.config import load_settings
from agrimon.evolution.candidate import make_candidate, persist_source
from agrimon.evolution.templates.seed_rgb_overview import SEED, SEED_ANALYSIS_KEY, SEED_ID
from agrimon.runtime import Runtime, build_context

from tests.conftest import make_project


def _setup(tmp_path, edit=None, body=None):
    root = make_project(tmp_path, seed=False)
    settings = load_settings(root, read_env=False)
    source, manifest = make_candidate(SEED, SEED_ID, SEED_ANALYSIS_KEY, "seed")
    if edit:
        source = edit(source)
    if body is not None:
        source = body
    cap = tmp_path / "capability.py"
    digest = persist_source(cap, source)
    scene = load_catalog(settings).scene("eros_reservoir_farmland")
    ctx = build_context(settings, scene, manifest, digest, "committed", "req", "run1", tmp_path / "run")
    return Runtime(settings), cap, ctx


def _inject(code):
    return lambda s: s.replace("    luma = 0.2126", f"    {code}\n    luma = 0.2126")


def test_seed_runs_in_subprocess(tmp_path):
    rt, cap, ctx = _setup(tmp_path)
    out = rt.run(cap, ctx, tmp_path / "run")
    assert out.ok, out.tool_result.errors
    assert len(out.tool_result.matrix) == 48


def test_hang_is_stopped_at_timeout(tmp_path):
    rt, cap, ctx = _setup(tmp_path, body="def execute(context):\n    while True:\n        pass\n")
    out = rt.run(cap, ctx, tmp_path / "run", timeout=2)
    assert out.exit_reason == "timeout" and out.tool_result.status == "failed" and out.duration_s < 10


def test_exception_and_malformed_result(tmp_path):
    rt, cap, ctx = _setup(tmp_path, body="def execute(context):\n    raise RuntimeError('boom')\n")
    out = rt.run(cap, ctx, tmp_path / "run")
    assert out.exit_reason == "capability_error" and "boom" in out.tool_result.errors[0].message
    cap.write_text("def execute(context):\n    return {'status': 'success', 'matrix': [[1]]}\n")
    assert rt.run(cap, ctx, tmp_path / "run2").exit_reason == "malformed_result"


@pytest.mark.parametrize("code, marker", [
    ("open('GUARD_PROBE_FILE', 'w').write('x')", "open"),                                     # filesystem write
    ("__import__('socket').create_connection(('example.com', 80), 1)", "socket"),             # network
    ("__import__('subprocess').run(['echo', 'x'])", "subprocess"),                            # process launch
    ("__import__('shutil').rmtree('/nonexistent-dir')", "shutil"),                             # file management
    ("exec(\"try:\\n    open('GUARD_PROBE_FILE', 'w')\\nexcept Exception:\\n    pass\")", "open"),  # swallowed attempt
])
def test_execution_guard_blocks_side_effects(tmp_path, code, marker):
    rt, cap, ctx = _setup(tmp_path, edit=_inject(code))
    out = rt.run(cap, ctx, tmp_path / "run")
    assert out.exit_reason == "guardrail_violation", out.tool_result.errors
    assert marker in out.tool_result.errors[0].message
    assert not (tmp_path / "run" / "GUARD_PROBE_FILE").exists()


def test_secret_not_passed_to_subprocess(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    body = ("import os\nfrom agrimon.contracts import ToolResult\n"
            "def execute(context):\n    return ToolResult.failure('env', str('OPENAI_API_KEY' in os.environ))\n")
    rt, cap, ctx = _setup(tmp_path, body=body)
    assert rt.run(cap, ctx, tmp_path / "run").tool_result.errors[0].message == "False"
    assert os.environ["OPENAI_API_KEY"] == "sk-should-not-leak"
