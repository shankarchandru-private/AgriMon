"""F4 and P8 units: registry load, commit, duplicates, verification and orphans."""

import pytest

from agrimon.config import load_settings
from agrimon.contracts import EvaluationReport
from agrimon.evolution.candidate import content_hash, make_candidate
from agrimon.evolution.templates.seed_rgb_overview import SEED, SEED_ANALYSIS_KEY, SEED_ID
from agrimon.registry import DuplicateCapability, RegistryStore

from tests.conftest import make_project


def _stage(tmp_path, cap_id=SEED_ID, key=SEED_ANALYSIS_KEY):
    source, manifest = make_candidate(SEED, cap_id, key, "seed")
    d = tmp_path / f"cand-{cap_id}"
    d.mkdir()
    (d / "capability.py").write_text(source, encoding="utf-8")
    report = EvaluationReport(
        report_id="t", subject="candidate", capability_id=cap_id, capability_version="1.0.0",
        content_hash=content_hash(source), harness_version="t", config_version="t", checks=[], categories=[],
        blocking_passed=0, blocking_total=0, warnings_raised=0, overall_score=1.0, verdict="pass",
    )
    return d, manifest, report


def test_commit_and_list(tmp_path):
    root = make_project(tmp_path, seed=False)
    store = RegistryStore(load_settings(root, read_env=False))
    assert store.load().capabilities == []
    d, manifest, report = _stage(tmp_path)
    entry = store.commit(d, manifest, report, "a1")
    reg = store.load()
    assert reg.registry_version == 1 and [e.id for e in reg.capabilities] == [SEED_ID]
    assert store.verify() == [] and store.find_orphans() == []
    assert store.capability_file(entry).read_text() == (d / "capability.py").read_text()


def test_duplicate_rejected_and_state_unchanged(tmp_path):
    root = make_project(tmp_path, seed=False)
    store = RegistryStore(load_settings(root, read_env=False))
    d, manifest, report = _stage(tmp_path)
    store.commit(d, manifest, report, "a1")
    before = store.fingerprint()
    d2, m2, r2 = _stage(tmp_path, cap_id="other_id")
    with pytest.raises(DuplicateCapability):
        store.commit(d2, m2, r2, "a2")
    assert store.fingerprint() == before


def test_pending_folder_is_orphan(tmp_path):
    root = make_project(tmp_path, seed=False)
    store = RegistryStore(load_settings(root, read_env=False))
    (store.dir / ".pending-x").mkdir(parents=True)
    (store.dir / "ghost" / "1.0.0").mkdir(parents=True)
    names = sorted(p.name for p in store.find_orphans())
    assert names == [".pending-x", "1.0.0"]
