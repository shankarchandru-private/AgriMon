"""F3: the SDK and template execute the seed against the real scene into a valid 48x48 ToolResult."""

import types

import numpy as np
import pytest

from agrimon import sdk
from agrimon.catalog import load_catalog
from agrimon.config import load_settings
from agrimon.contracts import ToolResult
from agrimon.evolution.candidate import content_hash, make_candidate
from agrimon.evolution.templates import expected_fixed_text, split
from agrimon.evolution.templates.seed_rgb_overview import SEED, SEED_ANALYSIS_KEY, SEED_ID
from agrimon.runtime import build_context

from tests.conftest import REPO


def _load_module(source: str):
    mod = types.ModuleType("cap_under_test")
    exec(compile(source, "capability.py", "exec"), mod.__dict__)
    return mod


@pytest.mark.parametrize("scene_id", ["eros_reservoir_farmland", "eros_forest_valley"])
def test_seed_executes_in_process(tmp_path, scene_id):
    settings = load_settings(REPO, read_env=False)
    scene = load_catalog(settings).scene(scene_id)
    source, manifest = make_candidate(SEED, SEED_ID, SEED_ANALYSIS_KEY, "seed")
    ctx = build_context(settings, scene, manifest, content_hash(source), "committed", "req", "run", tmp_path)
    result = _load_module(source).execute(ctx)
    tr = ToolResult.model_validate(result.model_dump())  # round-trips through JSON shape
    assert tr.status == "success"
    assert (tr.grid.rows, tr.grid.cols) == (48, 48)
    names = {m.name for m in tr.metrics}
    assert {"mean_value", "min_value", "max_value", "valid_cells", "nodata_cells"} <= names
    assert tr.zones and {z.id for z in tr.zones} >= {"high-1", "low-1"}
    assert tr.summary.startswith(scene.label)
    assert tr.findings and all(f.evidence for f in tr.findings)
    assert all(s.follows_from in {f.id for f in tr.findings} for s in tr.next_steps)
    shares = sum(m.value for m in tr.metrics if m.name.endswith("_share_pct"))
    assert abs(shares - 100) <= 0.5


def test_template_fixed_text_is_stable():
    source, _ = make_candidate(SEED, SEED_ID, SEED_ANALYSIS_KEY, "seed")
    fixed, slots = split(source)
    assert fixed == expected_fixed_text()
    assert "def compute_values" in slots["SLOT 1"]


def test_grid_classify_and_zones():
    values = np.zeros((10, 10))
    values[:5, :5] = 0.9
    nodata = np.zeros((10, 10), dtype=bool)
    nodata[9, 9] = True
    grid = sdk.to_grid(values, nodata, 5, 5)
    classes = [{"id": 0, "label": "low", "color": "#000000", "min": 0.0, "max": 0.5},
               {"id": 1, "label": "high", "color": "#ffffff", "min": 0.5, "max": 1.0}]
    cg = sdk.classify(grid["mean"], classes)
    assert cg[0, 0] == 1 and cg[4, 4] == 0
    assert sdk.fmt(12.0) == "12" and sdk.fmt(0.1234) == "0.123"
