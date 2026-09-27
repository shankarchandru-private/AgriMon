"""ToolResult v2 is strict about schema and types, and open about the analysis itself."""

import math

import pytest
from pydantic import ValidationError

from agrimon.config import load_settings
from agrimon.contracts import GenerationOutput, IntentDraft, ToolResult

from tests.conftest import fixture_json


def _result(**over):
    n = 8
    base = {
        "status": "success", "layer_name": "Layer", "description": "d", "analysis_type": "band_ratio",
        "asset_id": "a1", "color_map": "purples",
        "matrix": [[1.5 if (r + c) % 2 else -0.25 for c in range(n)] for r in range(n)],
        "grid_size": {"rows": n, "cols": n, "cell_width_px": 2.0, "cell_height_px": 2.0},
        "metrics": [{"name": "matrix_mean", "value": 0.625, "unit": "ratio", "source": "platform"}],
        "summary": "Asset a1 summary.",
        "findings": [{"id": "F1", "statement": "Mean is 0.625.", "evidence": ["matrix_mean"]}],
        "next_steps": [{"type": "human_inspection", "description": "Inspect it closely.", "follows_from": "F1"}],
        "provenance": {"capability_id": "c", "capability_version": "1.0.0", "content_hash": "h", "template_version": "2",
                       "asset_id": "a1", "asset_file": "a.jpg", "config_version": "x", "started_at": "t", "finished_at": "t"},
    }
    base.update(over)
    return base


def test_continuous_result_without_bounds_classes_or_zones():
    tr = ToolResult.model_validate(_result())  # negative and >1 values, no zones, no classification
    assert tr.zones is None and tr.classification is None and tr.contract_version == "toolresult/2"


def test_nulls_allowed_but_not_nan():
    m = _result()["matrix"]
    m[0][0] = None
    ToolResult.model_validate(_result(matrix=m))
    m[0][1] = math.nan
    with pytest.raises(ValidationError):
        ToolResult.model_validate(_result(matrix=m))


@pytest.mark.parametrize("change", [
    {"color_map": "rainbow"},                                  # not an allowed color map
    {"matrix": [[1.0] * 7 for _ in range(8)]},                 # shape does not match grid_size
    {"asset_id": ""},                                          # asset required
    {"layer_name": ""},                                        # layer required
    {"findings": []},                                          # findings required
    {"extra_field": 1},                                        # unknown field
    {"next_steps": [{"type": "prescription", "description": "Apply it now.", "follows_from": "F1"}]},
    {"next_steps": [{"type": "human_inspection", "description": "Look again.", "follows_from": "F9"}]},
    {"metrics": [{"name": "m", "value": math.inf, "source": "capability"}]},
])
def test_invalid_toolresults_rejected(change):
    with pytest.raises(ValidationError):
        ToolResult.model_validate(_result(**change))


def test_failed_result_needs_errors():
    with pytest.raises(ValidationError):
        ToolResult.model_validate({"status": "failed", "description": "d"})
    assert ToolResult.failure("x", "boom").status == "failed"


def test_generation_output_rules():
    good = fixture_json("generation_ratio.json")
    GenerationOutput.model_validate(good)  # no classes, no bounds
    with pytest.raises(ValidationError):
        GenerationOutput.model_validate({**good, "color_map": "jet"})
    classes = fixture_json("generation_classes.json")
    GenerationOutput.model_validate(classes)
    with pytest.raises(ValidationError):  # classification requires mode aggregation
        GenerationOutput.model_validate({**classes, "aggregation": "mean"})


def test_intent_key_format():
    IntentDraft(analysis_key="vegetation_proxy_rgb", is_new_key=True, description="green areas", required_bands=["red"])
    with pytest.raises(ValidationError):
        IntentDraft(analysis_key="Vegetation Proxy", is_new_key=True, description="green areas", required_bands=["red"])


def test_settings_load_and_reject(tmp_path):
    (tmp_path / "agrimon.toml").write_text("[grid]\nrows = 48\ncols = 48\n")
    s = load_settings(tmp_path, read_env=False)
    assert s.grid.rows == 48 and s.openai_api_key is None
    (tmp_path / "agrimon.toml").write_text("[grid]\nrows = 2\n")
    with pytest.raises(ValidationError):
        load_settings(tmp_path, read_env=False)
    (tmp_path / "agrimon.toml").write_text("[unknown]\nx = 1\n")
    with pytest.raises(ValidationError):
        load_settings(tmp_path, read_env=False)
