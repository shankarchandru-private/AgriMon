"""Seven static admission rules, checked with ast before any candidate code runs.

The generated code may contain analytical logic only. It must not touch the filesystem, network,
credentials, processes, application state, the registry or committed capabilities.
"""

from __future__ import annotations

import ast

from agrimon.contracts import COLOR_MAPS, CapabilityManifest, Registry, Scene
from agrimon.evolution.templates import SLOT2_NAMES, expected_fixed_text, split

FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "getattr", "setattr",
                   "delattr", "input", "vars", "breakpoint", "exit", "quit", "help", "memoryview"}
FORBIDDEN_NAMES = {"os", "sys", "subprocess", "socket", "pathlib", "shutil", "importlib", "builtins", "sdk",
                   "requests", "urllib", "http", "ctypes", "pickle", "tempfile", "io", "glob", "threading",
                   "multiprocessing", "asyncio", "signal", "execute", "context"}
# NumPy entry points that read/write files, map memory, or are non-deterministic.
FORBIDDEN_ATTRS = {"save", "savez", "savez_compressed", "savetxt", "load", "loadtxt", "genfromtxt", "fromfile",
                   "tofile", "memmap", "DataSource", "ctypeslib", "lib", "random", "fromregex", "dump", "dumps",
                   "setflags", "system", "popen", "environ", "getenv"}
REQUIRED_FUNCTIONS = {"compute": ["bands", "params"], "interpret": ["evidence"]}


def _parse(body: str, slot: str, problems: list[str]) -> ast.Module | None:
    try:
        return ast.parse(body)
    except SyntaxError as exc:
        problems.append(f"rule 1: {slot} does not parse: {exc.msg} (line {exc.lineno})")
        return None


def admit(source: str, manifest: CapabilityManifest, scene: Scene, snapshot: Registry, max_bytes: int) -> list[str]:
    """Returns a list of violations; empty means admitted."""
    problems: list[str] = []

    # Rule 1: parses; fixed sections byte-identical to the template ------------------------
    if len(source.encode("utf-8")) > max_bytes:
        problems.append(f"rule 5: source is larger than {max_bytes} bytes")
    try:
        full = ast.parse(source)
        fixed, slots = split(source)
    except (SyntaxError, ValueError) as exc:
        return problems + [f"rule 1: capability does not parse or lacks slot markers: {exc}"]
    if fixed != expected_fixed_text():
        problems.append("rule 1: fixed template sections were modified")

    # Rule 2: SLOT 1 holds compute(bands, params), interpret(evidence) and private helpers only ---
    s1 = _parse(slots["SLOT 1"], "SLOT 1", problems)
    if s1 is not None:
        found: dict[str, ast.FunctionDef] = {}
        for node in s1.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue  # docstring or comment string
            if not isinstance(node, ast.FunctionDef):
                problems.append(f"rule 2: SLOT 1 may contain only function definitions (found {type(node).__name__})")
                continue
            if node.name in REQUIRED_FUNCTIONS:
                if node.name in found:
                    problems.append(f"rule 2: {node.name} is defined more than once")
                found[node.name] = node
            elif not node.name.startswith("_"):
                problems.append(f"rule 2: helper '{node.name}' must be private (start with '_')")
            if node.decorator_list:
                problems.append(f"rule 2: decorators are not allowed ({node.name})")
        for name, args in REQUIRED_FUNCTIONS.items():
            fn = found.get(name)
            if fn is None:
                problems.append(f"rule 2: SLOT 1 must define {name}({', '.join(args)})")
                continue
            a = fn.args
            if [x.arg for x in a.args] != args or a.vararg or a.kwarg or a.defaults or a.kwonlyargs or a.posonlyargs:
                problems.append(f"rule 2: {name} must have exactly the signature ({', '.join(args)})")

        # Rules 3 and 4: no imports, no forbidden operations ---------------------------------
        for node in ast.walk(s1):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                problems.append("rule 3: imports are not allowed in SLOT 1 (numpy as np and math are provided)")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                problems.append(f"rule 4: call to '{node.func.id}' is not allowed")
            elif isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
                problems.append(f"rule 4: name '{node.id}' is not allowed")
            elif isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in FORBIDDEN_ATTRS):
                problems.append(f"rule 4: attribute '{node.attr}' is not allowed")
            elif isinstance(node, (ast.Global, ast.Nonlocal, ast.ClassDef, ast.AsyncFunctionDef, ast.Await,
                                   ast.Yield, ast.YieldFrom, ast.With, ast.AsyncWith, ast.Delete)):
                problems.append(f"rule 4: {type(node).__name__} is not allowed")

    # Rule 5: SLOT 2 assigns literal metadata only --------------------------------------------
    literals: dict[str, object] = {}
    s2 = _parse(slots["SLOT 2"], "SLOT 2", problems)
    if s2 is not None:
        seen = []
        for node in s2.body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                problems.append("rule 5: SLOT 2 may only assign literal constants")
                continue
            try:
                literals[node.targets[0].id] = ast.literal_eval(node.value)
                seen.append(node.targets[0].id)
            except ValueError:
                problems.append(f"rule 5: SLOT 2 value of {node.targets[0].id} is not a literal")
        if sorted(seen) != sorted(SLOT2_NAMES):
            problems.append(f"rule 5: SLOT 2 must define exactly {', '.join(SLOT2_NAMES)}")
    if sum(isinstance(n, ast.FunctionDef) and n.name == "execute" for n in full.body) != 1:
        problems.append("rule 2: execute must be defined only by the template")

    # Rule 6: manifest consistent with the code and with the selected asset --------------------
    missing = [b for b in manifest.required_bands if b not in scene.band_names]
    if missing:
        problems.append(f"rule 6: required data missing: bands {missing} are not in asset {scene.id} ({scene.band_names})")
    checks = {
        "REQUIRED_BANDS": manifest.required_bands,
        "COLOR_MAP": manifest.color_map,
        "AGGREGATION": manifest.aggregation,
        "LAYER_NAME": manifest.layer_name,
        "ANALYSIS_TYPE": manifest.analysis_type,
        "CLASSIFICATION": [c.model_dump() for c in manifest.classification] if manifest.classification is not None else None,
    }
    for name, expected in checks.items():
        if name in literals and literals[name] != expected:
            problems.append(f"rule 6: {name} differs from the manifest")
    if literals.get("COLOR_MAP") not in (None, *COLOR_MAPS):
        problems.append(f"rule 6: color map must be one of {', '.join(COLOR_MAPS)}")
    if manifest.classification is not None and manifest.aggregation != "mode":
        problems.append("rule 6: a classified raster must use aggregation 'mode'")

    # Rule 7: not a duplicate of a committed capability -----------------------------------------
    for e in snapshot.capabilities:
        if e.id == manifest.id or manifest.analysis_key in (e.analysis_key, *e.aliases):
            problems.append(f"rule 7: '{manifest.analysis_key}' is already committed as {e.id} {e.version}")

    return list(dict.fromkeys(problems))
