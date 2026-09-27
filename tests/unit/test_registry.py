"""Registry load, commit, duplicates, integrity, verification and orphans."""

import os
import stat

import pytest

from agrimon.config import load_settings
from agrimon.contracts import EvaluationReport
from agrimon.evolution.candidate import make_candidate, persist_source
from agrimon.evolution.templates.seed_rgb_overview import SEED, SEED_ANALYSIS_KEY, SEED_ID
from agrimon.registry import DuplicateCapability, RegistryStore

from tests.conftest import make_project


def _stage(tmp_path, cap_id=SEED_ID, key=SEED_ANALYSIS_KEY):
    source, manifest = make_candidate(SEED, cap_id, key, "seed")
    d = tmp_path / f"cand-{cap_id}"
    digest = persist_source(d / "capability.py", source)
    report = EvaluationReport(
        report_id="t", subject="candidate", capability_id=cap_id, capability_version="1.0.0",
        content_hash=digest, harness_version="t", config_version="t", checks=[], categories=[],
        blocking_passed=0, blocking_total=0, warnings_raised=0, overall_score=1.0, verdict="pass",
    )
    return d, manifest, report


def _store(tmp_path):
    return RegistryStore(load_settings(make_project(tmp_path, seed=False), read_env=False))


def test_commit_and_list(tmp_path):
    store = _store(tmp_path)
    assert store.load().capabilities == []
    d, manifest, report = _stage(tmp_path)
    entry = store.commit(d, manifest, report, "a1")
    reg = store.load()
    assert reg.registry_version == 1 and [e.id for e in reg.capabilities] == [SEED_ID]
    assert entry.contract == "toolresult/2" and store.integrity_ok(entry)
    assert store.verify() == [] and store.find_orphans() == []
    assert not os.stat(store.capability_file(entry)).st_mode & stat.S_IWUSR  # write-once


def test_report_hash_must_match_persisted_bytes(tmp_path):
    store = _store(tmp_path)
    d, manifest, report = _stage(tmp_path)
    (d / "capability.py").write_bytes((d / "capability.py").read_bytes() + b"\n# edited after evaluation\n")
    before = store.fingerprint()
    with pytest.raises(Exception, match="content hash"):
        store.commit(d, manifest, report, "a1")
    assert store.fingerprint() == before


def test_duplicate_rejected_and_state_unchanged(tmp_path):
    store = _store(tmp_path)
    d, manifest, report = _stage(tmp_path)
    store.commit(d, manifest, report, "a1")
    before = store.fingerprint()
    d2, m2, r2 = _stage(tmp_path, cap_id="other_id")
    with pytest.raises(DuplicateCapability):
        store.commit(d2, m2, r2, "a2")
    assert store.fingerprint() == before


def test_tampered_committed_file_fails_integrity(tmp_path):
    store = _store(tmp_path)
    d, manifest, report = _stage(tmp_path)
    entry = store.commit(d, manifest, report, "a1")
    f = store.capability_file(entry)
    os.chmod(f, stat.S_IWUSR | stat.S_IRUSR)
    f.write_bytes(f.read_bytes().replace(b"0.2126", b"0.3000"))
    assert not store.integrity_ok(entry) and store.verify()


def test_pending_folder_is_orphan(tmp_path):
    store = _store(tmp_path)
    (store.dir / ".pending-x").mkdir(parents=True)
    (store.dir / "ghost" / "1.0.0").mkdir(parents=True)
    assert sorted(p.name for p in store.find_orphans()) == [".pending-x", "1.0.0"]
