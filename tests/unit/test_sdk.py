"""The SDK and template execute capabilities on the real asset; the platform derives matrix, stats and zones."""

import types

import numpy as np
import pytest

from agrimon import sdk
from agrimon.catalog import load_catalog
from agrimon.config import load_settings
from agrimon.contracts import GenerationOutput, ToolResult
from agrimon.evolution.candidate import make_candidate, persist_source
from agrimon.evolution.templates import expected_fixed_text, split
from agrimon.evolution.templates.seed_rgb_overview import SEED, SEED_ANALYSIS_KEY, SEED_ID
from agrimon.runtime import build_context

from tests.conftest import REPO, fixture_json


def _run(tmp_path, gen, scene_id="eros_reservoir_farmland", overrides=None):
    settings = load_settings(REPO, overrides=overrides, read_env=False)
    scene = load_catalog(settings).scene(scene_id)
    source, manifest = make_candidate(gen, "k_cap", "k_cap", "generated")
    digest = persist_source(tmp_path / "capability.py", source)
    ctx = build_context(settings, scene, manifest, digest, "committed", "req", "run", tmp_path)
    mod = types.ModuleType("cap_under_test")
    exec(compile(source, "capability.py", "exec"), mod.__dict__)
    return ToolResult.model_validate(mod.execute(ctx).model_dump()), scene


@pytest.mark.parametrize("scene_id", ["eros_reservoir_farmland", "eros_forest_valley"])
def test_seed_produces_valid_48x48_result(tmp_path, scene_id):
    tr, scene = _run(tmp_path, SEED, scene_id)
    assert tr.status == "success" and (tr.grid_size.rows, tr.grid_size.cols) == (48, 48)
    assert tr.asset_id == scene_id and tr.color_map == "ylorrd" and tr.classification is None
    assert tr.summary.startswith(scene.label) and tr.findings and tr.zones


def test_matrix_derived_from_input_and_metrics_consistent(tmp_path):
    tr, _ = _run(tmp_path, SEED)
    m = np.array([[np.nan if v is None else v for v in row] for row in tr.matrix])
    stats = {x.name: x.value for x in tr.metrics if x.source == "platform"}
    assert stats["matrix_mean"] == pytest.approx(np.nanmean(m), abs=1e-4)
    assert stats["matrix_max"] == pytest.approx(np.nanmax(m), abs=1e-4)
    assert stats["valid_cells"] == np.isfinite(m).sum()
    assert np.nanstd(m) > 0.01  # a real, varied raster, not a constant


def test_continuous_ratio_above_one_without_zones_or_classes(tmp_path):
    tr, _ = _run(tmp_path, GenerationOutput.model_validate(fixture_json("generation_ratio.json")), "eros_forest_valley")
    values = [v for row in tr.matrix for v in row if v is not None]
    assert max(values) > 1 and tr.zones is None and tr.classification is None


def test_negative_values_and_optional_zones(tmp_path):
    tr, _ = _run(tmp_path, GenerationOutput.model_validate(fixture_json("generation_exg.json")))
    values = [v for row in tr.matrix for v in row if v is not None]
    assert min(values) < 0 and tr.zones and all(z.name == "green_dominant" for z in tr.zones)


def test_classification_only_when_requested(tmp_path):
    tr, _ = _run(tmp_path, GenerationOutput.model_validate(fixture_json("generation_classes.json")))
    assert tr.classification and abs(sum(c.share_pct for c in tr.classification.classes) - 100) < 0.1
    assert {v for row in tr.matrix for v in row if v is not None} <= {0.0, 1.0, 2.0}


def test_64x64_grid(tmp_path):
    tr, _ = _run(tmp_path, SEED, overrides={"grid": {"rows": 64, "cols": 64}})
    assert len(tr.matrix) == 64 and len(tr.matrix[0]) == 64


def test_aggregations_and_validation():
    values = np.arange(16, dtype=float).reshape(4, 4)
    nodata = np.zeros((4, 4), dtype=bool)
    nodata[0, 0] = True
    assert sdk.to_matrix(values, nodata, 2, 2, "mean")["matrix"][0, 0] == pytest.approx(np.mean([1, 4, 5]))
    assert sdk.to_matrix(values, nodata, 2, 2, "max")["matrix"][1, 1] == 15
    cls = np.array([[0, 0, 1, 1], [0, 1, 1, 1], [2, 2, 2, 2], [2, 2, 2, 2]], dtype=float)
    assert sdk.to_matrix(cls, np.zeros((4, 4), bool), 2, 2, "mode")["matrix"][0, 1] == 1
    with pytest.raises(ValueError):
        sdk.analysis_output(np.zeros((3, 3)), (4, 4))  # wrong shape
    with pytest.raises(ValueError):
        sdk.analysis_output({"values": np.zeros((4, 4)), "zones": {"Bad Name": np.zeros((4, 4))}}, (4, 4))
    with pytest.raises(ValueError):
        sdk.analysis_output({"values": np.zeros((4, 4)), "metrics": {"x": float("nan")}}, (4, 4))
    grid = sdk.to_matrix(cls, np.zeros((4, 4), bool), 2, 2, "mode")
    with pytest.raises(ValueError):
        sdk.class_summary(grid, [{"id": 0, "label": "a"}, {"id": 1, "label": "b"}])  # class 2 undeclared
    assert sdk.fmt(12.0) == "12" and sdk.fmt(0.1234) == "0.123"


def test_template_fixed_text_is_stable():
    source, _ = make_candidate(SEED, SEED_ID, SEED_ANALYSIS_KEY, "seed")
    fixed, slots = split(source)
    assert fixed == expected_fixed_text()
    assert "def compute" in slots["SLOT 1"] and "def interpret" in slots["SLOT 1"]
