"""Registry read, snapshot, verification and the atomic commit protocol.

Only this module writes under capabilities/. Committed capability folders are write-once;
registry.json is replaced whole, and that replace is the commit point.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import threading
from pathlib import Path

from agrimon.config import Settings
from agrimon.contracts import CapabilityManifest, EvaluationReport, Registry, RegistryEntry, utcnow
from agrimon.observability import audit, get_logger

log = get_logger("registry")


class CommitError(RuntimeError):
    def __init__(self, message: str, orphan: Path | None = None):
        super().__init__(message)
        self.orphan = orphan


class DuplicateCapability(CommitError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RegistryStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dir = settings.capabilities_dir
        self.path = settings.registry_path
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ read
    def load(self) -> Registry:
        if not self.path.exists():
            return Registry()
        return Registry.model_validate_json(self.path.read_text(encoding="utf-8"))

    def snapshot(self) -> Registry:
        """A pinned copy for one request; later commits do not change it."""
        return self.load().model_copy(deep=True)

    def entry_dir(self, entry: RegistryEntry) -> Path:
        return self.dir / entry.path

    def capability_file(self, entry: RegistryEntry) -> Path:
        return self.entry_dir(entry) / "capability.py"

    def read_manifest(self, entry: RegistryEntry) -> CapabilityManifest:
        return CapabilityManifest.model_validate_json((self.entry_dir(entry) / "manifest.json").read_text(encoding="utf-8"))

    def read_evaluation(self, entry: RegistryEntry) -> EvaluationReport:
        return EvaluationReport.model_validate_json((self.entry_dir(entry) / "evaluation.json").read_text(encoding="utf-8"))

    def find(self, cap_id: str, version: str) -> RegistryEntry | None:
        for e in self.load().capabilities:
            if e.id == cap_id and e.version == version:
                return e
        return None

    # ------------------------------------------------------------------ integrity
    def verify(self) -> list[str]:
        """Checks every indexed entry against its folder. Empty list means intact."""
        problems = []
        try:
            reg = self.load()
        except Exception as exc:
            return [f"registry.json unreadable: {exc}"]
        for e in reg.capabilities:
            folder = self.entry_dir(e)
            for name in ("capability.py", "manifest.json", "evaluation.json"):
                if not (folder / name).exists():
                    problems.append(f"{e.id} {e.version}: missing {name}")
            if (folder / "capability.py").exists() and _sha256(folder / "capability.py") != e.content_hash:
                problems.append(f"{e.id} {e.version}: content hash mismatch")
            if (folder / "manifest.json").exists():
                m = self.read_manifest(e)
                if (m.id, m.version, m.analysis_key) != (e.id, e.version, e.analysis_key):
                    problems.append(f"{e.id} {e.version}: manifest does not match index")
        return problems

    def find_orphans(self) -> list[Path]:
        """Folders under capabilities/ that registry.json does not list (including .pending-*)."""
        indexed = {e.path for e in self.load().capabilities}
        orphans = []
        if not self.dir.exists():
            return orphans
        for top in sorted(self.dir.iterdir()):
            if not top.is_dir():
                continue
            if top.name.startswith(".pending-"):
                orphans.append(top)
                continue
            for ver in sorted(p for p in top.iterdir() if p.is_dir()):
                if f"{top.name}/{ver.name}" not in indexed:
                    orphans.append(ver)
        return orphans

    def remove_stale_temp(self) -> bool:
        """A crash between writing and replacing the index can leave registry.json.tmp behind."""
        tmp = self.path.with_name("registry.json.tmp")
        if tmp.exists():
            tmp.unlink()
            return True
        return False

    def fingerprint(self) -> str:
        """Hash of every file under capabilities/: equal before and after any failed evolution."""
        h = hashlib.sha256()
        for p in sorted(self.dir.rglob("*")):
            if p.is_file():
                h.update(p.relative_to(self.dir).as_posix().encode())
                h.update(p.read_bytes())
        return h.hexdigest()

    # ------------------------------------------------------------------ commit
    def _write_index(self, registry: Registry) -> None:
        tmp = self.path.with_name("registry.json.tmp")
        try:
            tmp.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp, self.path)  # the commit point
        finally:
            if tmp.exists():
                tmp.unlink()

    def commit(
        self, candidate_dir: Path, manifest: CapabilityManifest, report: EvaluationReport, attempt_id: str
    ) -> RegistryEntry:
        """Copies a passing candidate into capabilities/<id>/<version>/ and atomically adds it to the index."""
        source = candidate_dir / "capability.py"
        with self._lock:
            reg = self.load()
            for e in reg.capabilities:
                keys = {e.analysis_key, *e.aliases}
                if e.id == manifest.id or manifest.analysis_key in keys:
                    raise DuplicateCapability(f"'{manifest.analysis_key}' is already committed as {e.id} {e.version}")
            if report.verdict != "pass":
                raise CommitError("evaluation verdict is not pass")
            chash = _sha256(source)
            if report.content_hash != chash:
                raise CommitError("evaluation report does not match the candidate's content hash")
            target = self.dir / manifest.id / manifest.version
            if target.exists():
                raise DuplicateCapability(f"{manifest.id} {manifest.version} folder already exists")

            pending = self.dir / f".pending-{attempt_id}"
            pending.mkdir(parents=True)
            shutil.copy2(source, pending / "capability.py")
            (pending / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            (pending / "evaluation.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(pending, target)
            for f in target.iterdir():
                os.chmod(f, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

            entry = RegistryEntry(
                id=manifest.id,
                version=manifest.version,
                analysis_key=manifest.analysis_key,
                aliases=manifest.aliases,
                name=manifest.name,
                description=manifest.description,
                required_bands=manifest.required_bands,
                origin=manifest.origin,
                committed_at=utcnow(),
                source_request_id=manifest.source_request_id,
                content_hash=chash,
                path=f"{manifest.id}/{manifest.version}",
                verdict="pass",
                overall_score=report.overall_score,
            )
            new = Registry(
                registry_version=reg.registry_version + 1,
                updated_at=utcnow(),
                capabilities=[*reg.capabilities, entry],
            )
            try:
                self._write_index(new)
            except Exception as exc:  # index unchanged; the copied folder is now an orphan
                raise CommitError(f"registry index write failed: {exc}", orphan=target) from exc
            audit({"event": "commit", "id": entry.id, "version": entry.version, "content_hash": chash,
                   "previous_registry_version": reg.registry_version, "registry_version": new.registry_version,
                   "attempt_id": attempt_id})
            log.info("capability committed", extra={"fields": {"capability": entry.id, "version": entry.version}})
            return entry


def make_writable(path: Path) -> None:
    """Used only by reset_demo and quarantine moves: committed files are read-only."""
    for p in [path, *path.rglob("*")] if path.is_dir() else [path]:
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD | (stat.S_IEXEC if p.is_dir() else 0))
        except OSError:
            pass
