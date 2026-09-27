"""Shared fixtures: a temporary copy of the project in its seed state, and a stub LLM."""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"


def make_project(tmp_path: Path, seed: bool = True) -> Path:
    """Copies config, assets, web and (optionally) the committed seed into a fresh project root."""
    root = tmp_path / "project"
    root.mkdir()
    shutil.copy2(REPO / "agrimon.toml", root / "agrimon.toml")
    shutil.copytree(REPO / "assets", root / "assets")
    shutil.copytree(REPO / "web", root / "web")
    if (REPO / "app_spec.json").exists():
        shutil.copy2(REPO / "app_spec.json", root / "app_spec.json")
    (root / "capabilities").mkdir()
    if seed:
        src = REPO / "capabilities"
        for item in src.iterdir():
            if item.is_dir():
                shutil.copytree(item, root / "capabilities" / item.name)
            elif item.name == "registry.json":
                shutil.copy2(item, root / "capabilities" / item.name)
    return root


class FakeLLM:
    """Returns canned JSON per role. Each entry may be a dict or an Exception to raise."""

    def __init__(self, intent=None, generation=None):
        self.responses = {"intent": list(intent or []), "generation": list(generation or [])}
        self.calls = {"intent": 0, "generation": 0}
        self.prompts: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def complete_json(self, role: str, system: str, user: str) -> dict:
        with self._lock:
            self.calls[role] += 1
            self.prompts.append((role, user))
            queue = self.responses[role]
            if not queue:
                raise AssertionError(f"FakeLLM: no canned {role} response left")
            item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            from agrimon.config.llm import LLMError

            raise LLMError(str(item))
        return json.loads(json.dumps(item))


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / "llm" / name).read_text())
