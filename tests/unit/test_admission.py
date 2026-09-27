"""The seven admission rules reject bad candidates before anything runs."""

import copy

import pytest

from agrimon.catalog import load_catalog
from agrimon.config import load_settings
from agrimon.contracts import GenerationOutput, Registry, RegistryEntry
from agrimon.evolution.admission import admit
from agrimon.evolution.candidate import make_candidate

from tests.conftest import REPO, fixture_json

SETTINGS = load_settings(REPO, read_env=False)
SCENE = load_catalog(SETTINGS).scene("eros_reservoir_farmland")
INTERPRET = fixture_json("generation_ratio.json")["interpret_source"]


def _admit(gen: dict, source_edit=None, snapshot=None):
    source, manifest = make_candidate(GenerationOutput.model_validate(gen), "cand_key", "cand_key", "generated")
    if source_edit:
        source = source_edit(source)
    return admit(source, manifest, SCENE, snapshot or Registry(), 20000)


def _gen(**changes):
    g = copy.deepcopy(fixture_json("generation_exg.json"))
    g.update(changes)
    return g


def test_good_candidates_admitted():
    assert _admit(_gen()) == []
    assert _admit(fixture_json("generation_ratio.json")) == []
    assert _admit(fixture_json("generation_classes.json")) == []


@pytest.mark.parametrize("body, rule", [
    ("import os\ndef compute(bands, params):\n    return bands['red']\n", "rule 3"),
    ("def compute(bands, params):\n    return open('x').read()\n", "rule 4"),                    # filesystem
    ("def compute(bands, params):\n    return bands.__class__\n", "rule 4"),                     # internals
    ("def compute(bands, params):\n    return eval('1')\n", "rule 4"),
    ("def compute(bands, params):\n    np.save('x.npy', bands['red'])\n    return bands['red']\n", "rule 4"),  # numpy I/O
    ("def compute(bands, params):\n    return np.random.rand(*bands['red'].shape)\n", "rule 4"),   # nondeterminism
    ("def compute(bands, params):\n    return sdk.load_bands(None, [])\n", "rule 4"),             # platform access
    ("def compute(bands):\n    return bands['red']\n", "rule 2"),                                # signature
    ("def helper():\n    pass\ndef compute(bands, params):\n    return bands['red']\n", "rule 2"),  # public helper
    ("X = 3\ndef compute(bands, params):\n    return bands['red']\n", "rule 2"),                 # state outside functions
])
def test_compute_violations(body, rule):
    problems = _admit(_gen(compute_source=body, interpret_source=INTERPRET))
    assert any(p.startswith(rule) for p in problems), problems


def test_private_helper_allowed():
    body = "def _ratio(a, b):\n    return a / np.where(b > 0, b, np.nan)\n\ndef compute(bands, params):\n    return _ratio(bands['green'], bands['red'])\n"
    assert _admit(fixture_json("generation_ratio.json") | {"compute_source": body}) == []


def test_missing_interpret_or_tampered_template_rejected():
    problems = _admit(_gen(), source_edit=lambda s: s.replace("def interpret(evidence):", "def summarize(evidence):"))
    assert any("interpret(evidence)" in p for p in problems)
    problems = _admit(_gen(), source_edit=lambda s: s.replace("sdk.load_bands(context, REQUIRED_BANDS)", "({}, None)"))
    assert any(p.startswith("rule 1") for p in problems)


def test_missing_required_data_rejected():
    problems = _admit(_gen(required_bands=["red", "nir"]))
    assert any(p.startswith("rule 6") and "nir" in p for p in problems)


def test_duplicate_key_rejected():
    reg = Registry(capabilities=[RegistryEntry(
        id="other", version="1.0.0", analysis_key="x_key", aliases=["cand_key"], name="n", description="d",
        required_bands=["red"], origin="generated", committed_at="t", content_hash="h", path="other/1.0.0",
        verdict="pass", overall_score=1.0, contract="toolresult/2")])
    assert any(p.startswith("rule 7") for p in _admit(_gen(), snapshot=reg))
