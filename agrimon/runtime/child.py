"""Entry point of the capability subprocess: python -m agrimon.runtime.child <capability.py> <context.json> <result.json>

Loads one capability file, calls execute(context) under an execution guard and writes a ToolResult.
Any exception becomes a failed ToolResult; the parent process never sees it.

The guard is a Python audit hook that blocks file writes, network access, process launches and
environment changes while capability code runs. It is a guardrail against faulty generated code,
not a security sandbox (that remains a production concern).
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

_BLOCKED_PREFIXES = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
                     "os.kill", "os.remove", "os.unlink", "os.rename", "os.replace", "os.rmdir", "os.mkdir",
                     "os.chmod", "os.chown", "os.truncate", "os.link", "os.symlink", "shutil.", "ctypes.", "urllib.", "http.client.", "ftplib.", "smtplib.", "winreg.", "msvcrt.",
                     "webbrowser.", "sqlite3.connect", "_winapi.")


def _install_guard(violations: list[str]):
    active = [False]

    def hook(event: str, args: tuple) -> None:
        if not active[0]:
            return
        blocked = event.startswith(_BLOCKED_PREFIXES)
        if event == "open" and len(args) > 1 and isinstance(args[1], str) and any(c in args[1] for c in "wax+"):
            blocked = True
        if blocked:
            violations.append(event)
            raise PermissionError(f"blocked by the AgriMon execution guard: {event}")

    sys.addaudithook(hook)
    return active


def main(argv: list[str]) -> int:
    cap_file, ctx_file, out_file = argv[1:4]
    from pydantic import ValidationError

    from agrimon.contracts import Context, ToolResult
    import agrimon.sdk  # noqa: F401  platform libraries load before the guard switches on
    import rasterio  # noqa: F401

    out = Path(out_file)
    violations: list[str] = []
    guard = _install_guard(violations)
    try:
        context = Context.model_validate_json(Path(ctx_file).read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("agrimon_capability", cap_file)
        module = importlib.util.module_from_spec(spec)
        guard[0] = True
        try:
            spec.loader.exec_module(module)
            result = module.execute(context)
        finally:
            guard[0] = False
        if violations:
            raise PermissionError(f"capability attempted blocked operations: {sorted(set(violations))}")
        if not isinstance(result, ToolResult):
            result = ToolResult.model_validate(result)
        out.write_text(result.model_dump_json(), encoding="utf-8")
        return 0
    except ValidationError as exc:
        failure = ToolResult.failure("malformed_result", f"result does not match ToolResult: {exc}")
    except PermissionError as exc:
        failure = ToolResult.failure("guardrail_violation", str(exc))
    except Exception as exc:  # noqa: BLE001 - any capability error becomes a failed ToolResult
        if violations:
            failure = ToolResult.failure("guardrail_violation", f"capability attempted blocked operations: {sorted(set(violations))}")
        else:
            tb = traceback.format_exc().strip().splitlines()[-4:]
            failure = ToolResult.failure("capability_error", f"{type(exc).__name__}: {exc} | {' | '.join(tb)}")
    out.write_text(failure.model_dump_json(), encoding="utf-8")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
