"""Trust boundaries that the package layout makes testable."""

import ast
from pathlib import Path

from agrimon.evolution import generator
from agrimon.evolution.templates import HEADER
from agrimon.harness import harness

PKG = Path(__file__).resolve().parents[2] / "agrimon"


def _imports(path: Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def test_sdk_imports_only_contracts():
    for f in (PKG / "sdk").glob("*.py"):
        agrimon_imports = {m for m in _imports(f) if m.startswith("agrimon")}
        assert agrimon_imports <= {"agrimon.contracts", "agrimon.sdk.core"}, (f, agrimon_imports)


def test_template_header_imports_only_sdk_numpy_math():
    mods = _imports_from_text(HEADER)
    assert mods == {"math", "numpy", "agrimon"}


def _imports_from_text(text: str) -> set[str]:
    mods = set()
    for node in ast.parse(text).body:
        if isinstance(node, ast.ImportFrom):
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return mods


def test_generator_never_sees_the_harness():
    assert "harness" not in " ".join(_imports(Path(generator.__file__)))
    for check in ("Numbers traced", "Probe behaviour", "PRESCRIPTIVE", "probe"):
        assert check not in generator.SYSTEM_PROMPT
    assert harness.HARNESS_VERSION


def test_only_registry_writes_capabilities_and_only_config_reads_env():
    for f in PKG.rglob("*.py"):
        text = f.read_text()
        rel = f.relative_to(PKG).as_posix()
        if "OPENAI_API_KEY" in text:
            assert rel.startswith(("config/", "intent/", "evolution/generator")), rel
        if "capabilities_dir" in text and ("write_text" in text or "os.replace" in text or "shutil.move" in text):
            assert rel.startswith(("registry/", "evolution/quarantine", "config/")), rel
