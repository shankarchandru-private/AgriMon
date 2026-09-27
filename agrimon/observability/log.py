"""Structured logging. Every line carries the current request, attempt and run ids."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

_request_id = contextvars.ContextVar("request_id", default=None)
_attempt_id = contextvars.ContextVar("attempt_id", default=None)
_run_id = contextvars.ContextVar("run_id", default=None)
_audit_lock = threading.Lock()
_audit_path: Path | None = None


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": _request_id.get(),
            "attempt_id": _attempt_id.get(),
            "run_id": _run_id.get(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            entry.update(extra)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps({k: v for k, v in entry.items() if v is not None}, default=str)


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    global _audit_path
    logs_dir.mkdir(parents=True, exist_ok=True)
    _audit_path = logs_dir / "registry_audit.jsonl"
    root = logging.getLogger("agrimon")
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    file_handler = logging.FileHandler(logs_dir / "agrimon.jsonl", encoding="utf-8")
    file_handler.setFormatter(JsonLineFormatter())
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(file_handler)
    root.addHandler(console)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"agrimon.{name}")


@contextlib.contextmanager
def bind(request_id: str | None = None, attempt_id: str | None = None, run_id: str | None = None):
    tokens = []
    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))
    if attempt_id is not None:
        tokens.append((_attempt_id, _attempt_id.set(attempt_id)))
    if run_id is not None:
        tokens.append((_run_id, _run_id.set(run_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def audit(entry: dict) -> None:
    """Append one line to registry_audit.jsonl. Append-only; never rewritten."""
    if _audit_path is None:
        return
    line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}, default=str)
    with _audit_lock, open(_audit_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
