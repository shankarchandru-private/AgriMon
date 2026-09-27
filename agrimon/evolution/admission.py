"""Seven static admission rules, checked with ast before any candidate code runs."""

from __future__ import annotations

import ast
import re

from agrimon.contracts import CapabilityManifest, Registry, Scene
from agrimon.evolution.templates import SLOT2_NAMES, SLOT3_NAMES, expected_fixed_text, split

FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "getattr", "setattr",
                   "delattr", "input", "vars", "breakpoint", "exit", "quit"}
FORBIDDEN_NAMES = {"os", "sys", "subprocess", "socket", "pathlib", "shutil", "importlib", "builtins", "sdk"}
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
VALID_PLACEHOLDER = re.compile(
    r"^(metric\.(mean_value|min_value|max_value|valid_cells|nodata_cells|class_\d+_share_pct)"
    r"|zone\.(high|low)-[1-3](\.(label|share_pct|mean_value|cell_count|area_m2))?"
    r"|class\.\d+)$"
)


def _slot_tree(body: str, slot: str, problems: list[str]) -> ast.Module | None:
    try:
        return ast.parse(body)
    except SyntaxError as exc:
        problems.append(f"rule 1: {slot} does not parse: {exc.msg} (line {exc.lineno})")
        return None


def admit(
    source: str, manifest: CapabilityManifest, scene: Scene, snapshot: Registry, max_bytes: int
) -> list[str]:
    """Returns a list of violations; empty means admitted."""
    problems: list[str] = []

    # Rule 1: parses; fixed sections byte-identical to the template ------------------------
    if len(source.encode("utf-8")) > max_bytes:
        problems.append(f"rule 5: source is larger than {max_bytes} bytes")
    try:
        ast.parse(source)
        fixed, slots = split(source)
    except (SyntaxError, ValueError) as exc:
        return problems + [f"rule 1: capability does not parse or lacks slot markers: {exc}"]
    if fixed != expected_fixed_text():
        problems.append("rule 1: fixed template sections were modified")

    # Rule 2: slots have the required shape; execute not redefined -------------------------
    s1 = _slot_tree(slots["SLOT 1"], "SLOT 1", problems)
    if s1 is not None:
        defs = [n for n in s1.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        if len(defs) != 1 or not isinstance(defs[0], ast.FunctionDef) or defs[0].name != "compute_values":
            problems.append("rule 2: SLOT 1 must contain exactly one function, compute_values")
        else:
            args = defs[0].args
            if [a.arg for a in args.args] != ["bands", "params"] or args.vararg or args.kwarg or args.defaults \
                    or args.kwonlyargs or args.posonlyargs or defs[0].decorator_list:
                problems.append("rule 2: compute_values must have exactly the signature (bands, params)")
        # Rules 3 and 4: no imports, no forbidden calls or names ---------------------------
        for node in ast.walk(s1):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                problems.append("rule 3: imports are not allowed in SLOT 1 (numpy and math are provided)")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                problems.append(f"rule 4: call to '{node.func.id}' is not allowed")
            elif isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
                problems.append(f"rule 4: name '{node.id}' is not allowed")
            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                problems.append(f"rule 4: attribute '{node.attr}' is not allowed")
            elif isinstance(node, (ast.Global, ast.Nonlocal, ast.Lambda, ast.ClassDef, ast.AsyncFunctionDef)):
                problems.append(f"rule 4: {type(node).__name__} is not allowed")

    literals: dict[str, object] = {}
    for slot, names in (("SLOT 2", SLOT2_NAMES), ("SLOT 3", SLOT3_NAMES)):
        tree = _slot_tree(slots[slot], slot, problems)
        if tree is None:
            continue
        seen = []
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                problems.append(f"rule 5: {slot} may only assign literal constants")
                continue
            try:
                literals[node.targets[0].id] = ast.literal_eval(node.value)
                seen.append(node.targets[0].id)
            except ValueError:
                problems.append(f"rule 5: {slot} value of {node.targets[0].id} is not a literal")
        if sorted(seen) != sorted(names):
            problems.append(f"rule 5: {slot} must define exactly {', '.join(names)}")

    full = ast.parse(source)
    if sum(isinstance(n, ast.FunctionDef) and n.name == "execute" for n in full.body) != 1:
        problems.append("rule 2: execute must be defined only by the template")

    # Rule 6: manifest consistent with the code and the scene -------------------------------
    missing = [b for b in manifest.required_bands if b not in scene.band_names]
    if missing:
        problems.append(f"rule 6: required bands {missing} are not in scene {scene.id} ({scene.band_names})")
    if literals.get("REQUIRED_BANDS") not in (None, manifest.required_bands):
        problems.append("rule 6: REQUIRED_BANDS differs from the manifest")
    classes = sorted([c.model_dump() for c in manifest.classes], key=lambda c: c["min"])
    if literals.get("CLASSES") not in (None, classes):
        problems.append("rule 6: CLASSES differ from the manifest")
    if manifest.value_min >= manifest.value_max:
        problems.append("rule 6: value_min must be below value_max")
    ids = [c["id"] for c in classes]
    if len(set(ids)) != len(ids):
        problems.append("rule 6: class ids must be unique")
    if classes and (abs(classes[0]["min"] - manifest.value_min) > 1e-9 or abs(classes[-1]["max"] - manifest.value_max) > 1e-9):
        problems.append("rule 6: classes must start at value_min and end at value_max")
    for a, b in zip(classes, classes[1:]):
        if abs(a["max"] - b["min"]) > 1e-9:
            problems.append(f"rule 6: gap or overlap between classes {a['id']} and {b['id']}")
    for c in classes:
        if c["min"] >= c["max"]:
            problems.append(f"rule 6: class {c['id']} has min >= max")
    rule_ids = {r.id for r in manifest.finding_rules}
    for step in manifest.next_steps:
        if step.follows_from not in rule_ids:
            problems.append(f"rule 6: next step follows unknown finding '{step.follows_from}'")
    for rule in manifest.finding_rules:
        for ph in PLACEHOLDER.findall(rule.template):
            if not VALID_PLACEHOLDER.match(ph):
                problems.append(f"rule 6: finding {rule.id} uses unknown placeholder '{{{ph}}}'")
            m = re.match(r"^metric\.class_(\d+)_share_pct$", ph)
            if m and int(m.group(1)) not in ids:
                problems.append(f"rule 6: finding {rule.id} references class {m.group(1)}, which does not exist")

    # Rule 7: not a duplicate of a committed capability -------------------------------------
    for e in snapshot.capabilities:
        if e.id == manifest.id or manifest.analysis_key in (e.analysis_key, *e.aliases):
            problems.append(f"rule 7: '{manifest.analysis_key}' is already committed as {e.id} {e.version}")

    return list(dict.fromkeys(problems))
