"""P6: the seven admission rules reject bad candidates before anything runs."""

import copy

import pytest

from agrimon.catalog import load_catalog
from agrimon.config import load_settings
from agrimon.contracts import GenerationOutput, Registry
from agrimon.evolution.admission import admit
from agrimon.evolution.candidate import make_candidate

from tests.conftest import REPO, fixture_json

SETTINGS = load_settings(REPO, read_env=False)
SCENE = load_catalog(SETTINGS).scene("eros_reservoir_farmland")


def _admit(gen: dict, source_edit=None, snapshot=None):
    source, manifest = make_candidate(GenerationOutput.model_validate(gen), "vegetation_proxy_rgb",
                                      "vegetation_proxy_rgb", "generated")
    if source_edit:
        source = source_edit(source)
    return admit(source, manifest, SCENE, snapshot or Registry(), 20000)


def _gen(**changes):
    g = copy.deepcopy(fixture_json("generation_exg.json"))
    g.update(changes)
    return g


def test_good_candidate_admitted():
    assert _admit(_gen()) == []


@pytest.mark.parametrize("body, rule", [
    ("import os\ndef compute_values(bands, params):\n    return bands['red']\n", "rule 3"),
    ("def compute_values(bands, params):\n    return open('x').read()\n", "rule 4"),
    ("def compute_values(bands, params):\n    return bands.__class__\n", "rule 4"),
    ("def compute_values(bands, params):\n    return eval('1')\n", "rule 4"),
    ("def compute_values(bands):\n    return bands['red']\n", "rule 2"),
    ("def helper():\n    pass\ndef compute_values(bands, params):\n    return bands['red']\n", "rule 2"),
])
def test_slot1_violations(body, rule):
    problems = _admit(_gen(compute_values_source=body))
    assert any(p.startswith(rule) for p in problems), problems


def test_fixed_section_tampering_rejected():
    problems = _admit(_gen(), source_edit=lambda s: s.replace("sdk.load_bands(context, REQUIRED_BANDS)", "{}, None"))
    assert any(p.startswith("rule 1") for p in problems)
    problems = _admit(_gen(), source_edit=lambda s: s + "\ndef execute(context):\n    return {}\n")
    assert any(p.startswith("rule 1") or p.startswith("rule 2") for p in problems)


def test_manifest_rules():
    gap = _gen()
    gap["classes"][1]["min"] = 0.01  # gap between classes 0 and 1
    assert any("gap or overlap" in p for p in _admit(gap))
    nir = _gen(required_bands=["red", "nir"])
    assert any("rule 6" in p and "nir" in p for p in _admit(nir))
    bad_ph = _gen(finding_rules=[{"id": "F1", "template": "Value {metric.secret_value}"}],
                  next_steps=[{"type": "human_inspection", "description": "Look at it closely.", "follows_from": "F1"}])
    assert any("unknown placeholder" in p for p in _admit(bad_ph))


def test_duplicate_key_rejected():
    from agrimon.contracts import RegistryEntry

    reg = Registry(capabilities=[RegistryEntry(
        id="other", version="1.0.0", analysis_key="x_key", aliases=["vegetation_proxy_rgb"], name="n", description="d",
        required_bands=["red"], origin="generated", committed_at="t", content_hash="h", path="other/1.0.0",
        verdict="pass", overall_score=1.0)])
    assert any(p.startswith("rule 7") for p in _admit(_gen(), snapshot=reg))
