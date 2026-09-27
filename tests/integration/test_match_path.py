"""P1-P4: a question flows through intent, deterministic match and execution to an answer, via the API."""

import time

from fastapi.testclient import TestClient

from agrimon.api.app import create_app
from agrimon.config import load_settings

from tests.conftest import FakeLLM, fixture_json, make_project


def wait(client, rid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        rec = client.get(f"/api/requests/{rid}").json()
        if rec["state"] in ("completed", "failed"):
            return rec
        time.sleep(0.2)
    raise AssertionError("request did not finish")


def test_brightness_question_end_to_end(tmp_path):
    root = make_project(tmp_path)
    llm = FakeLLM(intent=[fixture_json("intent_brightness.json")])
    client = TestClient(create_app(load_settings(root, read_env=False), llm=llm))

    health = client.get("/api/health").json()
    assert health["ok"] and health["capabilities"] == 1

    rid = client.post("/api/requests", json={"question": "Give me a brightness overview", "scene_id": "eros_reservoir_farmland"}).json()["request_id"]
    rec = wait(client, rid)
    assert rec["state"] == "completed", rec.get("failure")
    states = [h["state"] for h in rec["history"]]
    assert states[:4] == ["received", "resolving_intent", "matching", "matched"]
    assert "generating" not in states and llm.calls["generation"] == 0
    assert rec["match"]["rule"] == "rule 2: key match"
    ans = rec["answer"]
    assert ans["source"] == "existing" and ans["capability_id"] == "rgb_overview"
    assert ans["tool_result"]["grid"]["rows"] == 48 and ans["evaluation"]["verdict"] == "pass"
    run = client.get(f"/api/runs/{ans['run_id']}").json()
    assert run["summary"] == ans["tool_result"]["summary"]

    caps = client.get("/api/capabilities").json()["capabilities"]
    detail = client.get(f"/api/capabilities/{caps[0]['id']}/{caps[0]['version']}").json()
    assert detail["manifest"]["analysis_key"] == "brightness_overview" and "def execute" in detail["source"]
    assert client.get("/").status_code == 200 and client.get("/harness.html").status_code == 200


def test_alias_matches_and_unknown_scene_rejected(tmp_path):
    root = make_project(tmp_path)
    intent = {**fixture_json("intent_brightness.json"), "analysis_key": "true_color_overview"}
    client = TestClient(create_app(load_settings(root, read_env=False), llm=FakeLLM(intent=[intent])))
    rid = client.post("/api/requests", json={"question": "true colour overview", "scene_id": "eros_forest_valley"}).json()["request_id"]
    assert wait(client, rid)["answer"]["capability_id"] == "rgb_overview"
    assert client.post("/api/requests", json={"question": "anything", "scene_id": "nope"}).status_code == 404


def test_no_key_fails_cleanly(tmp_path):
    root = make_project(tmp_path)
    settings = load_settings(root, read_env=False)
    from agrimon.orchestrator.service import AgriMonService

    svc = AgriMonService(settings, llm=None, use_default_llm=False)
    rec = svc.run_sync("brightness", "eros_forest_valley")
    assert rec.state == "failed" and "OPENAI_API_KEY" in rec.failure.reason
