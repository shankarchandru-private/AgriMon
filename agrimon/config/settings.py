"""Loads and validates agrimon.toml and .env at startup. Invalid configuration stops the app."""

from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerSettings(_S):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class LLMSettings(_S):
    intent_model: str = "gpt-4o-mini"
    generation_model: str = "gpt-4o-mini"
    temperature: float = Field(default=0.0, ge=0, le=2)
    request_timeout_seconds: float = Field(default=60, gt=0)


class RuntimeSettings(_S):
    timeout_seconds: float = Field(default=60, gt=0, le=600)


class EvolutionSettings(_S):
    max_retries: int = Field(default=2, ge=0, le=5)
    max_source_bytes: int = Field(default=20000, ge=1000)


class GridSettings(_S):
    rows: int = Field(default=48, ge=4, le=512)
    cols: int = Field(default=48, ge=4, le=512)


class HarnessSettings(_S):
    summary_max_chars: int = Field(default=600, ge=100)


class RequestSettings(_S):
    max_concurrent_evolutions: int = Field(default=1, ge=1, le=1)
    worker_threads: int = Field(default=4, ge=1, le=16)


class PathSettings(_S):
    assets: str = "assets"
    capabilities: str = "capabilities"
    workspace: str = "workspace"
    var: str = "var"
    web: str = "web"


class Settings(_S):
    root: Path
    server: ServerSettings = ServerSettings()
    llm: LLMSettings = LLMSettings()
    runtime: RuntimeSettings = RuntimeSettings()
    evolution: EvolutionSettings = EvolutionSettings()
    grid: GridSettings = GridSettings()
    harness: HarnessSettings = HarnessSettings()
    requests: RequestSettings = RequestSettings()
    paths: PathSettings = PathSettings()
    openai_api_key: Optional[SecretStr] = None
    config_version: str = "unversioned"

    # Resolved directories -------------------------------------------------
    @property
    def assets_dir(self) -> Path:
        return self.root / self.paths.assets

    @property
    def capabilities_dir(self) -> Path:
        return self.root / self.paths.capabilities

    @property
    def workspace_dir(self) -> Path:
        return self.root / self.paths.workspace

    @property
    def staging_dir(self) -> Path:
        return self.workspace_dir / "staging"

    @property
    def quarantine_dir(self) -> Path:
        return self.workspace_dir / "quarantine"

    @property
    def var_dir(self) -> Path:
        return self.root / self.paths.var

    @property
    def requests_dir(self) -> Path:
        return self.var_dir / "requests"

    @property
    def runs_dir(self) -> Path:
        return self.var_dir / "runs"

    @property
    def logs_dir(self) -> Path:
        return self.var_dir / "logs"

    @property
    def web_dir(self) -> Path:
        return self.root / self.paths.web

    @property
    def registry_path(self) -> Path:
        return self.capabilities_dir / "registry.json"

    @property
    def catalog_path(self) -> Path:
        return self.assets_dir / "catalog.json"

    @property
    def app_spec_path(self) -> Path:
        return self.root / "app_spec.json"

    def ensure_runtime_dirs(self) -> None:
        for d in (self.staging_dir, self.quarantine_dir, self.requests_dir, self.runs_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def load_settings(root: Path | str, overrides: Optional[dict] = None, read_env: bool = True) -> Settings:
    """Read agrimon.toml and .env under root. Raises on any invalid value."""
    root = Path(root).resolve()
    toml_path = root / "agrimon.toml"
    raw_bytes = toml_path.read_bytes() if toml_path.exists() else b""
    data = tomllib.loads(raw_bytes.decode("utf-8")) if raw_bytes else {}
    for section, values in (overrides or {}).items():
        data.setdefault(section, {}).update(values)

    key: Optional[str] = None
    if read_env:
        key = _read_env_file(root / ".env").get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    version = hashlib.sha256(raw_bytes + repr(sorted((overrides or {}).items())).encode()).hexdigest()[:12]
    return Settings(root=root, openai_api_key=key or None, config_version=version, **data)
