"""The OpenAI client, configured here so only agrimon.config touches the key.

Intent resolution and capability generation receive a client from this module;
nothing else in the app sees the key, and it is never passed to capability subprocesses.
"""

from __future__ import annotations

import json
from typing import Protocol

from agrimon.config.settings import Settings


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def complete_json(self, role: str, system: str, user: str) -> dict: ...


class OpenAIJsonClient:
    """Calls chat completions in JSON mode; callers validate the result with Pydantic."""

    def __init__(self, settings: Settings):
        from openai import OpenAI  # imported lazily so tests never need the SDK configured

        if settings.openai_api_key is None:
            raise LLMError("OPENAI_API_KEY is not set in .env")
        self._client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm.request_timeout_seconds,
        )
        self._models = {"intent": settings.llm.intent_model, "generation": settings.llm.generation_model}
        self._temperature = settings.llm.temperature

    def complete_json(self, role: str, system: str, user: str) -> dict:
        try:
            resp = self._client.chat.completions.create(
                model=self._models[role],
                temperature=self._temperature,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            text = resp.choices[0].message.content or ""
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"model returned invalid JSON: {exc}") from exc
        except Exception as exc:  # network, auth, rate limit
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc


def make_llm_client(settings: Settings) -> LLMClient | None:
    """Returns a client, or None when no key is configured (the app still starts)."""
    if settings.openai_api_key is None:
        return None
    return OpenAIJsonClient(settings)
