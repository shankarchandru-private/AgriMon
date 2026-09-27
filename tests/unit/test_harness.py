"""The harness tests analytical behaviour, grounding and provenance, not just field presence."""

import copy

import pytest

from agrimon.contracts import ToolResult
from agrimon.harness.harness import Harness

from tests.conftest import evaluate_candidate, failed_checks, fixture_json, gen_fixture

RATIO_INTERPRET = fixture_json("generation_ratio.json")["interpret_source"]


def _with_compute(body, **extra):
    return gen_fixture("generation_ratio.json", compute_source=body, **extra)


# ---------------------------------------------------------------------------- analysis freedom
@pytest.mark.parametrize("fixture, scene", [
    ("generation_exg.json", "eros_reservoir_farmland"),      # negative values, optional zones present
    ("generation_ratio.json", "eros_forest_valley"),         # values > 1, no zones, no classes, no bounds
    ("generation_classes.json", "eros_reservoir_farmland"),  # classification because the question asks for it
])
def test_valid_analyses_pass_without_imposed_bounds(tmp_path, fixture, scene):
    report, _ = evaluate_candidate(tmp_path, fixture_json(fixture), scene)
    assert report.verdict == "pass", failed_checks(report)
    assert report.blocking_total == 18


# ---------------------------------------------------------------------------- data-derived matrix
def test_fabricated_constant_matrix_fails(tmp_path):
    report, _ = evaluate_candidate(tmp_path, _with_compute(
        "def compute(bands, params):\n    return np.zeros_like(bands['red']) + 0.5 * bands['green'].mean() * 0 + 1.0\n"))
    assert {"Input dependence", "Data-derived matrix"} <= set(failed_checks(report))


def test_fabricated_pattern_ignoring_input_fails(tmp_path):
    body = ("def compute(bands, params):\n    h, w = bands['red'].shape\n"
            "    return np.tile(np.linspace(0.0, 1.0, w), (h, 1)) + 0 * bands['green']\n")
    report, _ = evaluate_candidate(tmp_path, _with_compute(body))
    assert "Input dependence" in failed_checks(report)


def test_declared_but_unused_band_fails(tmp_path):
    gen = _with_compute("def compute(bands, params):\n    return bands['green'] / np.where(bands['red'] > 0, bands['red'], np.nan)\n",
                        required_bands=["red", "green", "blue"])
    report, _ = evaluate_candidate(tmp_path, gen)
    dep = next(c for c in report.checks if c.name == "Input dependence")
    assert not dep.passed and "blue: no effect" in dep.observed


def test_output_changes_when_input_changes(tmp_path):
    report, _ = evaluate_candidate(tmp_path, fixture_json("generation_exg.json"))
    dep = next(c for c in report.checks if c.name == "Input dependence")
    assert dep.passed and dep.observed.count("responds") == 3
    derived = next(c for c in report.checks if c.name == "Data-derived matrix")
    assert derived.passed and "mirrored" in derived.observed


# ---------------------------------------------------------------------------- execution
def test_nondeterministic_capability_fails_reproducibility(tmp_path):
    body = ("def compute(bands, params):\n    rng = np.random.default_rng()\n"
            "    return bands['green'] / np.where(bands['red'] > 0, bands['red'], np.nan) + rng.random(bands['red'].shape) * 0.01\n")
    report, _ = evaluate_candidate(tmp_path, _with_compute(body))  # admission (which forbids np.random) is bypassed here
    assert "Reproducibility" in failed_checks(report)


def test_capability_error_fails_execution_and_contract(tmp_path):
    report, run = evaluate_candidate(tmp_path, _with_compute("def compute(bands, params):\n    return bands['swir']\n"))
    assert run.exit_reason == "capability_error"
    assert {"Schema conformance", "Clean run"} <= set(failed_checks(report))


# ---------------------------------------------------------------------------- grounding
def test_invented_number_in_finding_fails(tmp_path):
    interp = RATIO_INTERPRET.replace("(standard deviation {m['matrix_std']:.3f})", "(about 42% of the field is healthy)")
    report, _ = evaluate_candidate(tmp_path, gen_fixture("generation_ratio.json", interpret_source=interp), "eros_forest_valley")
    traced = next(c for c in report.checks if c.name == "Numbers traced")
    assert not traced.passed and "42" in traced.observed


def test_unsupported_evidence_reference_fails(tmp_path):
    interp = RATIO_INTERPRET.replace('"evidence": ["matrix_min", "matrix_max", "matrix_std"]', '"evidence": ["crop_health_index"]')
    report, _ = evaluate_candidate(tmp_path, gen_fixture("generation_ratio.json", interpret_source=interp), "eros_forest_valley")
    assert "Evidence references" in failed_checks(report)


def test_agronomic_prescription_fails(tmp_path):
    interp = RATIO_INTERPRET.replace(
        "Inspect cells with the highest ratio in the source image to see which surfaces they correspond to.",
        "Apply nitrogen fertilizer to the low-ratio cells to improve crop health.")
    report, _ = evaluate_candidate(tmp_path, gen_fixture("generation_ratio.json", interpret_source=interp), "eros_forest_valley")
    assert failed_checks(report) == ["No unsupported prescriptions"]


def test_missing_citation_is_only_a_warning(tmp_path):
    report, _ = evaluate_candidate(tmp_path, fixture_json("generation_ratio.json"), "eros_forest_valley")
    cite = next(c for c in report.checks if c.name == "Methodology reference")
    assert not cite.passed and not cite.blocking and report.verdict == "pass"


# ---------------------------------------------------------------------------- consistency (tampered results)
def _passing_result(tmp_path):
    report, run = evaluate_candidate(tmp_path, fixture_json("generation_exg.json"))
    import numpy as np

    tr = run.tool_result
    base = np.array([[np.nan if v is None else v for v in row] for row in tr.matrix], dtype=float)
    return tr, base


def test_metrics_inconsistent_with_matrix_detected(tmp_path):
    tr, base = _passing_result(tmp_path)
    assert Harness._metrics_consistent(tr, base).passed
    data = tr.model_dump()
    next(m for m in data["metrics"] if m["name"] == "matrix_mean")["value"] += 0.5
    assert not Harness._metrics_consistent(ToolResult.model_validate(data), base).passed


def test_zones_inconsistent_with_matrix_detected(tmp_path):
    tr, base = _passing_result(tmp_path)
    assert Harness._zones_classes(tr, base).passed
    data = copy.deepcopy(tr.model_dump())
    data["zones"][0]["mean_value"] += 1.0
    assert not Harness._zones_classes(ToolResult.model_validate(data), base).passed


# ---------------------------------------------------------------------------- provenance from persisted bytes
def test_crlf_persisted_file_keeps_provenance(tmp_path):
    """Regression: on Windows text mode writes CRLF. The chain must hash the persisted bytes."""
    from agrimon.contracts import GenerationOutput
    from agrimon.evolution.candidate import make_candidate

    source, _ = make_candidate(GenerationOutput.model_validate(fixture_json("generation_exg.json")),
                               "candidate_key", "candidate_key", "generated")
    crlf = source.replace("\n", "\r\n").encode("utf-8")
    report, _ = evaluate_candidate(tmp_path, fixture_json("generation_exg.json"), raw_source=crlf)
    prov = next(c for c in report.checks if c.name == "Provenance chain")
    assert prov.passed and report.verdict == "pass", failed_checks(report)


def test_in_memory_hash_breaks_provenance(tmp_path):
    """The old defect: hashing the in-memory string instead of the persisted (CRLF) bytes must be caught."""
    import hashlib

    from agrimon.contracts import GenerationOutput
    from agrimon.evolution.candidate import make_candidate

    source, _ = make_candidate(GenerationOutput.model_validate(fixture_json("generation_exg.json")),
                               "candidate_key", "candidate_key", "generated")
    report, _ = evaluate_candidate(tmp_path, fixture_json("generation_exg.json"),
                                   raw_source=source.replace("\n", "\r\n").encode(),
                                   context_hash=hashlib.sha256(source.encode()).hexdigest())
    assert "Provenance chain" in failed_checks(report)


def test_file_changed_after_context_breaks_provenance(tmp_path):
    def tamper(cap):
        cap.write_bytes(cap.read_bytes() + b"\n# modified after hashing\n")

    report, _ = evaluate_candidate(tmp_path, fixture_json("generation_exg.json"), after_context=tamper)
    assert "Provenance chain" in failed_checks(report)


def test_committed_state_change_during_evaluation_detected(tmp_path):
    states = iter(["before", "after"])
    report, _ = evaluate_candidate(tmp_path, fixture_json("generation_exg.json"), fingerprint=lambda: next(states))
    assert "Committed state untouched" in failed_checks(report)
