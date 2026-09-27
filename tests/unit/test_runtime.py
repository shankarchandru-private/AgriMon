"""F5: capabilities run in a subprocess; hangs, crashes and malformed results become failed ToolResults."""

from agrimon.catalog import load_catalog
from agrimon.config import load_settings
from agrimon.evolution.candidate import content_hash, make_candidate
from agrimon.evolution.templates.seed_rgb_overview import SEED, SEED_ANALYSIS_KEY, SEED_ID
from agrimon.runtime import Runtime, build_context

from tests.conftest import make_project


def _setup(tmp_path, body=None):
    root = make_project(tmp_path, seed=False)
    settings = load_settings(root, read_env=False)
    source, manifest = make_candidate(SEED, SEED_ID, SEED_ANALYSIS_KEY, "seed")
    if body is not None:
        source = body
    cap = tmp_path / "capability.py"
    cap.write_text(source)
    scene = load_catalog(settings).scene("eros_reservoir_farmland")
    ctx = build_context(settings, scene, manifest, content_hash(source), "committed", "req", "run1", tmp_path / "run")
    return Runtime(settings), cap, ctx


def test_seed_runs_in_subprocess(tmp_path):
    rt, cap, ctx = _setup(tmp_path)
    out = rt.run(cap, ctx, tmp_path / "run")
    assert out.ok, out.tool_result.errors
    assert out.tool_result.grid.rows == 48
    assert (tmp_path / "run" / "toolresult.json").exists()


def test_hang_is_stopped_at_timeout(tmp_path):
    rt, cap, ctx = _setup(tmp_path, body="def execute(context):\n    while True:\n        pass\n")
    out = rt.run(cap, ctx, tmp_path / "run", timeout=2)
    assert out.exit_reason == "timeout" and out.tool_result.status == "failed"
    assert out.duration_s < 10


def test_exception_and_malformed_result(tmp_path):
    rt, cap, ctx = _setup(tmp_path, body="def execute(context):\n    raise RuntimeError('boom')\n")
    out = rt.run(cap, ctx, tmp_path / "run")
    assert out.exit_reason == "capability_error" and "boom" in out.tool_result.errors[0].message
    cap.write_text("def execute(context):\n    return {'status': 'success'}\n")
    out = rt.run(cap, ctx, tmp_path / "run2")
    assert out.exit_reason == "malformed_result"


def test_secret_not_passed_to_subprocess(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    body = ("import os\nfrom agrimon.contracts import ToolResult\n"
            "def execute(context):\n    return ToolResult.failure('env', str('OPENAI_API_KEY' in os.environ))\n")
    rt, cap, ctx = _setup(tmp_path, body=body)
    out = rt.run(cap, ctx, tmp_path / "run")
    assert out.tool_result.errors[0].message == "False"
