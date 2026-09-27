"""Create path: no match -> generate -> admit -> stage -> evaluate -> commit -> answer; then reuse."""

import copy
import os
import stat

import pytest

from agrimon.config import load_settings
from agrimon.orchestrator.service import AgriMonService

from tests.conftest import FakeLLM, fixture_json, make_project

JUDGE = {"score": 0.9, "reason": "The result directly answers the question."}


def _service(tmp_path, generation, intent="intent_vegetation.json"):
    root = make_project(tmp_path)
    llm = FakeLLM(intent=[fixture_json(intent), JUDGE], generation=generation)
    return AgriMonService(load_settings(root, read_env=False), llm=llm), llm


def test_vegetation_question_creates_commits_and_reuses(tmp_path):
    svc, llm = _service(tmp_path, [fixture_json("generation_exg.json")])
    rec = svc.run_sync("Where does vegetation appear?", "eros_reservoir_farmland")
    assert rec.state == "completed", rec.failure
    states = [h.state for h in rec.history]
    for s in ["no_match", "generating", "admitting", "executing_staged", "evaluating", "committing", "completed"]:
        assert s in states
    ans = rec.answer
    assert ans.source == "new" and ans.capability_id == "vegetation_proxy_rgb"
    assert ans.evaluation["verdict"] == "pass" and ans.evaluation["blocking_passed"] == 18
    tr = ans.tool_result
    assert tr.layer_name == "Excess Green (ExG)" and tr.color_map == "greens" and tr.asset_id == "eros_reservoir_farmland"
    assert "RGB" in tr.description and "NDVI" not in tr.layer_name

    caps = svc.list_capabilities()
    assert caps["registry_version"] == 2
    new = next(c for c in caps["capabilities"] if c["id"] == "vegetation_proxy_rgb")
    assert new["is_new"] and new["origin"] == "generated" and new["contract"] == "toolresult/2"
    cap_file = svc.settings.capabilities_dir / "vegetation_proxy_rgb" / "1.0.0" / "capability.py"
    assert not os.stat(cap_file).st_mode & stat.S_IWUSR
    assert not any(svc.settings.staging_dir.iterdir())
    assert svc.capability_detail("vegetation_proxy_rgb", "1.0.0")["creating_run"]["question"] == "Where does vegetation appear?"

    # asking again reuses it deterministically: no generation call
    llm.responses["intent"] = [fixture_json("intent_vegetation.json")]
    calls = llm.calls["generation"]
    again = svc.run_sync("Where does vegetation appear?", "eros_forest_valley")
    assert again.state == "completed" and again.answer.source == "existing"
    assert again.match.capability_id == "vegetation_proxy_rgb" and llm.calls["generation"] == calls


@pytest.mark.parametrize("intent, generation, scene, zones, classes", [
    ("intent_ratio.json", "generation_ratio.json", "eros_forest_valley", False, False),
    ("intent_classes.json", "generation_classes.json", "eros_reservoir_farmland", False, True),
])
def test_other_analysis_shapes_commit(tmp_path, intent, generation, scene, zones, classes):
    svc, _ = _service(tmp_path, [fixture_json(generation)], intent=intent)
    rec = svc.run_sync("question", scene)
    assert rec.state == "completed", rec.failure
    tr = rec.answer.tool_result
    assert (tr.zones is not None) == zones and (tr.classification is not None) == classes
    assert rec.answer.visualization["categorical"] == classes


def test_forbidden_import_rejected_then_retry_succeeds(tmp_path):
    bad = copy.deepcopy(fixture_json("generation_exg.json"))
    bad["compute_source"] = "import os\n" + bad["compute_source"]
    svc, llm = _service(tmp_path, [bad, fixture_json("generation_exg.json")])
    rec = svc.run_sync("Where does vegetation appear?", "eros_reservoir_farmland")
    assert rec.state == "completed" and len(rec.attempts) == 2
    q = svc.settings.quarantine_dir / rec.attempts[0]
    assert q.exists() and "rule 3" in (q / "attempt.json").read_text()
    assert not (q / "run").exists()  # rejected before any execution
    assert any("previous candidate was rejected" in p for r, p in llm.prompts if r == "generation")


def test_evaluations_list_committed_and_quarantined(tmp_path):
    bad = copy.deepcopy(fixture_json("generation_exg.json"))
    bad["interpret_source"] = bad["interpret_source"].replace(
        "Inspect the largest green-dominant region in the source image to confirm it is vegetation rather than green-tinted water or shadow.",
        "Apply nitrogen fertilizer at 40 kg/ha to the green-dominant region.")
    svc, _ = _service(tmp_path, [bad, fixture_json("generation_exg.json")])
    rec = svc.run_sync("Where does vegetation appear?", "eros_reservoir_farmland")
    assert rec.state == "completed"
    rows = svc.list_evaluations()
    assert sorted(r["kind"] for r in rows) == ["committed", "committed", "quarantined"]
    quarantined = next(r for r in rows if r["kind"] == "quarantined")
    assert quarantined["stage"] == "evaluating"
    detail = svc.get_evaluation(quarantined["report_ref"])
    failed = [c["name"] for c in detail["report"]["checks"] if c["blocking"] and not c["passed"]]
    assert failed == ["No unsupported prescriptions"]
