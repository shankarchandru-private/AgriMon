"""P5-P9: no match -> generate -> admit -> stage -> evaluate -> commit -> answer; then reuse."""

import copy
import os
import stat

from agrimon.config import load_settings
from agrimon.orchestrator.service import AgriMonService

from tests.conftest import FakeLLM, fixture_json, make_project

JUDGE = {"score": 0.9, "reason": "The ExG grid directly shows where green vegetation appears."}


def _service(tmp_path, generation, intents=None):
    root = make_project(tmp_path)
    llm = FakeLLM(intent=intents or [fixture_json("intent_vegetation.json"), JUDGE], generation=generation)
    return AgriMonService(load_settings(root, read_env=False), llm=llm), llm


def test_vegetation_question_creates_commits_and_reuses(tmp_path):
    svc, llm = _service(tmp_path, [fixture_json("generation_exg.json")])
    rec = svc.run_sync("Where does vegetation appear?", "eros_reservoir_farmland")
    assert rec.state == "completed", rec.failure
    states = [h.state for h in rec.history]
    for s in ["no_match", "generating", "admitting", "executing_staged", "evaluating", "committing", "completed"]:
        assert s in states
    assert rec.answer.source == "new" and rec.answer.capability_id == "vegetation_proxy_rgb"
    assert rec.answer.evaluation["verdict"] == "pass" and rec.answer.evaluation["blocking_passed"] == 13
    assert "RGB" in rec.answer.tool_result.description and "NDVI" not in rec.answer.tool_result.findings[0].statement

    # committed, discoverable, write-once, flagged New
    caps = svc.list_capabilities()
    assert caps["registry_version"] == 2
    new = next(c for c in caps["capabilities"] if c["id"] == "vegetation_proxy_rgb")
    assert new["is_new"] and new["origin"] == "generated"
    cap_file = svc.settings.capabilities_dir / "vegetation_proxy_rgb" / "1.0.0" / "capability.py"
    assert not os.stat(cap_file).st_mode & stat.S_IWUSR
    assert not any(svc.settings.staging_dir.iterdir())
    detail = svc.capability_detail("vegetation_proxy_rgb", "1.0.0")
    assert detail["creating_run"]["question"] == "Where does vegetation appear?"

    # asking again reuses it deterministically: no generation call
    llm.responses["intent"] = [fixture_json("intent_vegetation.json")]
    calls = llm.calls["generation"]
    again = svc.run_sync("Where does vegetation appear?", "eros_forest_valley")
    assert again.state == "completed" and again.answer.source == "existing"
    assert again.match.capability_id == "vegetation_proxy_rgb" and llm.calls["generation"] == calls


def test_forbidden_import_rejected_then_retry_succeeds(tmp_path):
    bad = copy.deepcopy(fixture_json("generation_exg.json"))
    bad["compute_values_source"] = "import os\n" + bad["compute_values_source"]
    svc, llm = _service(tmp_path, [bad, fixture_json("generation_exg.json")])
    rec = svc.run_sync("Where does vegetation appear?", "eros_reservoir_farmland")
    assert rec.state == "completed" and len(rec.attempts) == 2
    q = svc.settings.quarantine_dir / rec.attempts[0]
    assert q.exists() and "rule" in (q / "attempt.json").read_text()
    assert not (q / "run").exists()  # rejected before any execution
    assert "previous candidate was rejected" in llm.prompts[-1][1] or any(
        "previous candidate was rejected" in p for r, p in llm.prompts if r == "generation")


def test_evaluations_list_committed_and_quarantined(tmp_path):
    bad = copy.deepcopy(fixture_json("generation_exg.json"))
    bad["next_steps"][0]["description"] = "Apply nitrogen fertilizer at 40 kg/ha to the strong-green region."
    svc, _ = _service(tmp_path, [bad, fixture_json("generation_exg.json")])
    rec = svc.run_sync("Where does vegetation appear?", "eros_reservoir_farmland")
    assert rec.state == "completed"
    rows = svc.list_evaluations()
    kinds = sorted(r["kind"] for r in rows)
    assert kinds == ["committed", "committed", "quarantined"]
    quarantined = next(r for r in rows if r["kind"] == "quarantined")
    assert quarantined["stage"] == "evaluating"
    detail = svc.get_evaluation(quarantined["report_ref"])
    failed = [c["name"] for c in detail["report"]["checks"] if c["blocking"] and not c["passed"]]
    assert failed == ["No unsupported prescriptions"]
