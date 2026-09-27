"""Moves rejected candidates, orphans and interrupted attempts into workspace/quarantine/."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from agrimon.config import Settings
from agrimon.contracts import AttemptRecord, StateChange
from agrimon.observability import get_logger
from agrimon.registry.store import make_writable

log = get_logger("quarantine")


def _free(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return path.with_name(f"{path.name}-{stamp}")


def write_attempt(stage_dir: Path, record: AttemptRecord) -> None:
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "attempt.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")


def quarantine_attempt(settings: Settings, stage_dir: Path, record: AttemptRecord) -> Path:
    record.outcome = "quarantined"
    record.history.append(StateChange(state="quarantined", note=record.failure_reason or ""))
    write_attempt(stage_dir, record)
    dest = _free(settings.quarantine_dir / record.attempt_id)
    shutil.move(str(stage_dir), str(dest))
    log.info("attempt quarantined", extra={"fields": {"stage": record.failure_stage, "reason": record.failure_reason}})
    return dest


def move_orphan(settings: Settings, orphan: Path, into: Path | None = None) -> Path:
    """Moves a capability folder that registry.json does not list out of capabilities/."""
    make_writable(orphan)
    base = into or settings.quarantine_dir / f"orphan-{orphan.parent.name}-{orphan.name}".replace("/", "_")
    dest = _free(base if into is None else into / "orphan")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(orphan), str(dest))
    parent = orphan.parent
    if parent != settings.capabilities_dir and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
    log.warning("orphan moved to quarantine", extra={"fields": {"orphan": str(orphan), "dest": str(dest)}})
    return dest


def recover_staging(settings: Settings) -> list[Path]:
    """Attempts left in staging by a crash or restart are quarantined as interrupted."""
    moved = []
    for stage_dir in sorted(p for p in settings.staging_dir.iterdir() if p.is_dir()):
        att = stage_dir / "attempt.json"
        if att.exists():
            record = AttemptRecord.model_validate_json(att.read_text(encoding="utf-8"))
        else:
            record = AttemptRecord(attempt_id=stage_dir.name, request_id="unknown", candidate_number=0, analysis_key="unknown")
        record.failure_stage = record.failure_stage or "interrupted"
        record.failure_reason = record.failure_reason or "the app stopped before this attempt finished"
        moved.append(quarantine_attempt(settings, stage_dir, record))
    return moved
