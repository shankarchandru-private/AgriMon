"""Runs a capability in a separate Python process and always returns a ToolResult.

A crash, exception, hang or malformed result ends only that subprocess. This protects
availability (the core invariant); it is not a security sandbox, which is deferred to production.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

import agrimon
from agrimon.config import Settings
from agrimon.contracts import Context, ToolResult
from agrimon.observability import get_logger

log = get_logger("runtime")

CODE_ROOT = Path(agrimon.__file__).resolve().parents[1]
# Environment variables a Python/GDAL subprocess needs; everything else (including the
# OpenAI key) is withheld from capability code.
_ENV_ALLOW = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG", "LC_ALL"}


@dataclass
class RunOutcome:
    run_id: str
    tool_result: ToolResult
    exit_reason: str  # ok | capability_error | malformed_result | timeout | crash
    duration_s: float
    run_dir: Path

    @property
    def ok(self) -> bool:
        return self.exit_reason == "ok" and self.tool_result.status != "failed"


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOW or k.startswith(("GDAL_", "PROJ_"))}
    env["PYTHONPATH"] = str(CODE_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, capability_file: Path, context: Context, run_dir: Path, timeout: float | None = None) -> RunOutcome:
        timeout = timeout or self.settings.runtime.timeout_seconds
        run_dir.mkdir(parents=True, exist_ok=True)
        ctx_path = run_dir / "context.json"
        result_path = run_dir / "toolresult.json"
        ctx_path.write_text(context.model_dump_json(indent=2), encoding="utf-8")
        if result_path.exists():
            result_path.unlink()
        cmd = [sys.executable, "-m", "agrimon.runtime.child", str(capability_file), str(ctx_path), str(result_path)]
        started = time.monotonic()
        stderr = ""
        try:
            proc = subprocess.run(
                cmd, cwd=run_dir, env=_child_env(), capture_output=True, text=True, timeout=timeout
            )
            stderr = proc.stderr or ""
            result, reason = self._read_result(result_path, proc.returncode, stderr)
        except subprocess.TimeoutExpired as exc:
            stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            result = ToolResult.failure("timeout", f"capability exceeded the {timeout:g}s timeout and was stopped")
            reason = "timeout"
        duration = time.monotonic() - started
        if stderr:
            (run_dir / "stderr.txt").write_text(stderr[-20000:], encoding="utf-8")
        result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        log.info("run finished", extra={"fields": {"run_id": context.run_id, "exit_reason": reason,
                                                  "duration_s": round(duration, 3), "mode": context.mode}})
        return RunOutcome(context.run_id, result, reason, duration, run_dir)

    @staticmethod
    def _read_result(path: Path, returncode: int, stderr: str) -> tuple[ToolResult, str]:
        if not path.exists():
            tail = stderr.strip().splitlines()[-3:] if stderr else []
            return ToolResult.failure("crash", f"capability process exited ({returncode}) without a result: {' | '.join(tail)}"), "crash"
        try:
            result = ToolResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, ValueError) as exc:
            return ToolResult.failure("malformed_result", f"result does not match ToolResult v1: {exc}"), "malformed_result"
        if result.status == "failed":
            code = result.errors[0].code if result.errors else "capability_error"
            return result, code if code in {"malformed_result", "capability_error"} else "capability_error"
        return result, "ok"
