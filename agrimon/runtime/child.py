"""Entry point of the capability subprocess: python -m agrimon.runtime.child <capability.py> <context.json> <result.json>

Loads one capability file, calls execute(context) and writes a ToolResult. Any exception
becomes a failed ToolResult; the parent process never sees it.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path


def main(argv: list[str]) -> int:
    cap_file, ctx_file, out_file = argv[1:4]
    from pydantic import ValidationError

    from agrimon.contracts import Context, ToolResult

    out = Path(out_file)
    try:
        context = Context.model_validate_json(Path(ctx_file).read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("agrimon_capability", cap_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.execute(context)
        if not isinstance(result, ToolResult):
            result = ToolResult.model_validate(result)
        out.write_text(result.model_dump_json(), encoding="utf-8")
        return 0
    except ValidationError as exc:
        failure = ToolResult.failure("malformed_result", f"result does not match ToolResult v1: {exc}")
    except Exception as exc:  # noqa: BLE001 - any capability error becomes a failed ToolResult
        tb = traceback.format_exc().strip().splitlines()[-4:]
        failure = ToolResult.failure("capability_error", f"{type(exc).__name__}: {exc} | {' | '.join(tb)}")
    out.write_text(failure.model_dump_json(), encoding="utf-8")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
