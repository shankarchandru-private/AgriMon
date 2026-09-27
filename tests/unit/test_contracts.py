"""F1: contracts accept valid JSON and reject malformed JSON."""

import pytest
from pydantic import ValidationError

from agrimon.contracts import CapabilityManifest, IntentDraft, ToolResult
from agrimon.config import load_settings


def _grid(rows=4, cols=4):
    return {
        "rows": rows, "cols": cols, "cell_width_px": 2.0, "cell_height_px": 2.0,
        "value_label": "brightness", "class_ids": [[0] * cols for _ in range(rows)],
        "values": [[0.5] * cols for _ in range(rows)], "minimum": [[0.4] * cols for _ in range(rows)],
        "maximum": [[0.6] * cols for _ in range(rows)],
    }


def _prov():
    return {"capability_id": "rgb_overview", "capability_version": "1.0.0", "content_hash": "abc",
            "template_version": "1", "scene_id": "s", "asset_file": "a.jpg", "config_version": "x",
            "started_at": "t", "finished_at": "t"}


def test_valid_toolresult():
    tr = ToolResult.model_validate({"status": "success", "description": "d", "grid": _grid(), "provenance": _prov()})
    assert tr.contract_version == "toolresult/1"


def test_failed_toolresult_requires_errors():
    with pytest.raises(ValidationError):
        ToolResult.model_validate({"status": "failed", "description": "d"})
    assert ToolResult.failure("x", "boom").status == "failed"


def test_toolresult_rejects_unknown_field_and_bad_grid():
    with pytest.raises(ValidationError):
        ToolResult.model_validate({"status": "success", "description": "d", "grid": _grid(), "provenance": _prov(), "extra": 1})
    bad = _grid()
    bad["values"] = [[0.5] * 3 for _ in range(4)]
    with pytest.raises(ValidationError):
        ToolResult.model_validate({"status": "success", "description": "d", "grid": bad, "provenance": _prov()})


def test_intent_key_format():
    IntentDraft(analysis_key="vegetation_proxy_rgb", is_new_key=True, description="green areas", required_bands=["red"])
    with pytest.raises(ValidationError):
        IntentDraft(analysis_key="Vegetation Proxy", is_new_key=True, description="green areas", required_bands=["red"])


def test_manifest_requires_rules_and_valid_colors():
    base = dict(id="abc_key", version="1.0.0", template_version="1", analysis_key="abc_key", name="n", description="d",
                required_bands=["red"], value_label="v", value_unit="index", value_min=0, value_max=1,
                classes=[{"id": 0, "label": "a", "color": "#000000", "min": 0, "max": 0.5},
                         {"id": 1, "label": "b", "color": "#ffffff", "min": 0.5, "max": 1}],
                formula="f", finding_rules=[{"id": "F1", "template": "Mean is {metric.mean_value}."}], origin="seed")
    CapabilityManifest(**base)
    with pytest.raises(ValidationError):
        CapabilityManifest(**{**base, "finding_rules": []})
    with pytest.raises(ValidationError):
        CapabilityManifest(**{**base, "classes": [{"id": 0, "label": "a", "color": "red", "min": 0, "max": 1}] * 2})


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
