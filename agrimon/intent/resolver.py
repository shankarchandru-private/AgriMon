"""Turns a question into a structured Intent.

The LLM does the semantic step: it picks an existing analysis key or proposes a new one.
Whether a committed capability actually satisfies the intent is decided afterwards by
deterministic matching (agrimon.matching), never by the LLM.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from agrimon.contracts import Intent, IntentDraft, Registry, Scene
from agrimon.observability import get_logger

log = get_logger("intent")

SYSTEM_PROMPT = """You turn a user's analytical question about ONE raster image into a structured intent
for a geospatial analytics system. Reply with a JSON object only, with exactly these keys:
  "analysis_key": string, "is_new_key": boolean, "description": string,
  "required_bands": list of strings, "assumptions": list of strings

Rules:
1. required_bands must be a subset of the scene's bands.
2. If one of the existing analyses answers the question, return its key exactly and is_new_key=false.
3. Otherwise propose a new snake_case key naming the analysis (3-40 chars: a-z, 0-9, _; starts with a
   letter) and set is_new_key=true.
4. Never propose a multispectral index (NDVI, NDWI, NDRE, ...) that needs bands the scene lacks. Propose
   an RGB proxy instead, end its key with "_rgb" (for example "vegetation_proxy_rgb"), and state this in
   assumptions.
5. description: one sentence stating the per-pixel quantity to compute and summarize on a grid.
6. assumptions: short statements of any interpretation you made; an empty list if none.
"""


class IntentError(RuntimeError):
    pass


class IntentResolver:
    def __init__(self, llm):
        self.llm = llm

    def resolve(self, question: str, scene: Scene, snapshot: Registry) -> Intent:
        if self.llm is None:
            raise IntentError("no OpenAI key configured: add OPENAI_API_KEY to .env and restart")
        existing = [
            {"analysis_key": e.analysis_key, "aliases": e.aliases, "name": e.name,
             "description": e.description, "required_bands": e.required_bands}
            for e in snapshot.capabilities
        ]
        user = json.dumps({
            "question": question,
            "scene": {"id": scene.id, "label": scene.label, "sensor": scene.sensor, "bands": scene.band_names},
            "existing_analyses": existing,
        }, indent=2)
        last_error = ""
        for _ in range(2):
            prompt = user if not last_error else f"{user}\n\nYour previous reply was invalid: {last_error}. Fix it."
            try:
                raw = self.llm.complete_json("intent", SYSTEM_PROMPT, prompt)
                draft = IntentDraft.model_validate(raw)
            except ValidationError as exc:
                last_error = str(exc).splitlines()[0]
                continue
            except Exception as exc:  # LLMError: network, auth, bad JSON
                raise IntentError(f"intent resolution failed: {exc}") from exc
            bad = [b for b in draft.required_bands if b not in scene.band_names]
            if bad:
                last_error = f"required_bands {bad} are not in the scene bands {scene.band_names}"
                continue
            return self._normalize(draft, question, scene, snapshot)
        raise IntentError(f"intent resolution returned invalid output twice: {last_error}")

    @staticmethod
    def _normalize(draft: IntentDraft, question: str, scene: Scene, snapshot: Registry) -> Intent:
        """Deterministic consistency: is_new_key must agree with the registry."""
        known = {k for e in snapshot.capabilities for k in (e.analysis_key, *e.aliases)}
        data = draft.model_dump()
        data["is_new_key"] = draft.analysis_key not in known
        return Intent(**data, question=question, scene_id=scene.id)
