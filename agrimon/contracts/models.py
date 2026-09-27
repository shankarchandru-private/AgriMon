"""All cross-component contracts for Evolution 1.

Every JSON record the app reads or writes is validated by one of these models.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "ANALYSIS_KEY_PATTERN",
    "utcnow",
    "Strict",
    "BandInfo",
    "Scene",
    "Catalog",
    "IntentDraft",
    "Intent",
    "BandRef",
    "Context",
    "Metric",
    "ColorClass",
    "Grid",
    "Zone",
    "Finding",
    "NextStep",
    "Provenance",
    "Message",
    "ToolResult",
    "FindingRule",
    "NextStepRule",
    "CapabilityManifest",
    "RegistryEntry",
    "Registry",
    "MatchDecision",
    "CheckResult",
    "CategoryScore",
    "EvaluationReport",
    "AttemptRecord",
    "StateChange",
    "FailureContext",
    "Answer",
    "RequestRecord",
    "GenerationClass",
    "GenerationOutput",
]

ANALYSIS_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
CONTRACT_TOOLRESULT = "toolresult/1"
CONTRACT_MANIFEST = "manifest/1"
CONTRACT_REPORT = "evaluation/1"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Strict(BaseModel):
    """Base model: unknown fields are rejected so malformed JSON fails loudly."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- catalog


class BandInfo(Strict):
    name: str  # e.g. "red"
    index: int = Field(ge=1)  # 1-based raster band index
    scale: float = Field(gt=0)  # multiply raw value by scale to get 0-1


class Scene(Strict):
    id: str
    label: str
    file: str  # relative to assets/
    sensor: str
    source: str
    acquisition_date: Optional[str] = None  # ISO date, or None when not recorded
    crs: Optional[str] = None  # None = not georeferenced
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    resolution_m: Optional[float] = None
    dtype: str
    nodata: Optional[float] = None
    bands: list[BandInfo]

    @property
    def band_names(self) -> list[str]:
        return [b.name for b in self.bands]

    @property
    def date_text(self) -> str:
        return self.acquisition_date or "date not recorded"


class Catalog(Strict):
    catalog_version: Literal["catalog/1"] = "catalog/1"
    scenes: list[Scene]

    def scene(self, scene_id: str) -> Scene:
        for s in self.scenes:
            if s.id == scene_id:
                return s
        raise KeyError(f"unknown scene: {scene_id}")


# --------------------------------------------------------------------------- intent


class IntentDraft(Strict):
    """What the LLM returns; the resolver adds question and scene."""

    analysis_key: str
    is_new_key: bool
    description: str = Field(min_length=3, max_length=400)
    required_bands: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("analysis_key")
    @classmethod
    def _key_format(cls, v: str) -> str:
        if not ANALYSIS_KEY_PATTERN.match(v):
            raise ValueError("analysis_key must be snake_case, 3-40 chars, starting with a letter")
        return v


class Intent(IntentDraft):
    question: str
    scene_id: str
    output: Literal["grid"] = "grid"


# --------------------------------------------------------------------------- context


class BandRef(Strict):
    name: str
    index: int
    scale: float


class Context(Strict):
    """What a capability receives. No secrets, no paths outside read-only inputs and its run folder."""

    request_id: str
    run_id: str
    mode: Literal["committed", "staged", "probe"]
    scene_id: str
    scene_label: str
    scene_date: str
    scene_path: str
    bands: list[BandRef]
    nodata: Optional[float] = None
    resolution_m: Optional[float] = None
    grid_rows: int = Field(ge=4, le=512)
    grid_cols: int = Field(ge=4, le=512)
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_dir: str
    capability_id: str
    capability_version: str
    content_hash: str
    template_version: str
    config_version: str


# --------------------------------------------------------------------------- ToolResult v1


class Metric(Strict):
    name: str
    value: float
    unit: str
    description: str = ""


class ColorClass(Strict):
    id: int = Field(ge=0)
    label: str
    color: str
    min: float
    max: float

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise ValueError("color must be #RRGGBB")
        return v


class Grid(Strict):
    rows: int
    cols: int
    cell_width_px: float
    cell_height_px: float
    cell_size_m: Optional[float] = None
    value_label: str
    class_ids: list[list[int]]  # -1 = nodata cell
    values: list[list[Optional[float]]]  # per-cell mean
    minimum: list[list[Optional[float]]]
    maximum: list[list[Optional[float]]]

    @model_validator(mode="after")
    def _shape(self) -> "Grid":
        for name in ("class_ids", "values", "minimum", "maximum"):
            arr = getattr(self, name)
            if len(arr) != self.rows or any(len(r) != self.cols for r in arr):
                raise ValueError(f"grid.{name} must be {self.rows}x{self.cols}")
        return self


class Zone(Strict):
    id: str
    class_id: int
    label: str
    cell_count: int
    share_pct: float
    area_m2: Optional[float] = None
    mean_value: float
    row_min: int
    row_max: int
    col_min: int
    col_max: int


class Finding(Strict):
    id: str
    statement: str
    evidence: list[str]  # metric names or zone ids


class NextStep(Strict):
    type: Literal["follow_up_analysis", "human_inspection"]
    description: str
    follows_from: str  # finding id


class Provenance(Strict):
    capability_id: str
    capability_version: str
    content_hash: str
    template_version: str
    scene_id: str
    asset_file: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    config_version: str
    started_at: str
    finished_at: str


class Message(Strict):
    code: str
    message: str


class ToolResult(Strict):
    contract_version: Literal["toolresult/1"] = CONTRACT_TOOLRESULT
    status: Literal["success", "partial", "failed"]
    description: str
    metrics: list[Metric] = Field(default_factory=list)
    grid: Optional[Grid] = None
    color_map: list[ColorClass] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    next_steps: list[NextStep] = Field(default_factory=list)
    provenance: Optional[Provenance] = None
    warnings: list[Message] = Field(default_factory=list)
    errors: list[Message] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_rules(self) -> "ToolResult":
        if self.status == "failed":
            if not self.errors:
                raise ValueError("a failed ToolResult must carry errors")
            if self.findings:
                raise ValueError("a failed ToolResult must not carry findings")
        else:
            if self.grid is None:
                raise ValueError("a successful ToolResult must carry a grid")
            if self.provenance is None:
                raise ValueError("a successful ToolResult must carry provenance")
        return self

    @classmethod
    def failure(cls, code: str, message: str, description: str = "Capability run failed") -> "ToolResult":
        return cls(status="failed", description=description, errors=[Message(code=code, message=message[:2000])])


# --------------------------------------------------------------------------- manifest


class FindingRule(Strict):
    id: str = Field(pattern=r"^F\d{1,2}$")
    template: str = Field(min_length=5, max_length=300)


class NextStepRule(Strict):
    type: Literal["follow_up_analysis", "human_inspection"]
    description: str = Field(min_length=5, max_length=300)
    follows_from: str = Field(pattern=r"^F\d{1,2}$")


class CapabilityManifest(Strict):
    manifest_version: Literal["manifest/1"] = CONTRACT_MANIFEST
    id: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    template_version: str
    analysis_key: str
    aliases: list[str] = Field(default_factory=list)
    name: str
    description: str
    required_bands: list[str] = Field(min_length=1)
    value_label: str
    value_unit: str
    value_min: float
    value_max: float
    classes: list[ColorClass] = Field(min_length=2, max_length=8)
    formula: str
    citation: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    finding_rules: list[FindingRule] = Field(min_length=1)
    next_steps: list[NextStepRule] = Field(default_factory=list)
    origin: Literal["seed", "generated"]
    source_request_id: Optional[str] = None
    created_at: str = Field(default_factory=utcnow)

    @field_validator("id", "analysis_key")
    @classmethod
    def _key_format(cls, v: str) -> str:
        if not ANALYSIS_KEY_PATTERN.match(v):
            raise ValueError("must be snake_case, 3-40 chars, starting with a letter")
        return v


# --------------------------------------------------------------------------- registry


class RegistryEntry(Strict):
    id: str
    version: str
    analysis_key: str
    aliases: list[str] = Field(default_factory=list)
    name: str
    description: str
    required_bands: list[str]
    origin: Literal["seed", "generated"]
    committed_at: str
    source_request_id: Optional[str] = None
    content_hash: str
    path: str  # relative to capabilities/
    verdict: Literal["pass"]
    overall_score: float


class Registry(Strict):
    registry_version: int = 0
    updated_at: str = Field(default_factory=utcnow)
    capabilities: list[RegistryEntry] = Field(default_factory=list)


class MatchDecision(Strict):
    matched: bool
    capability_id: Optional[str] = None
    capability_version: Optional[str] = None
    rule: str  # which rule decided
    reason: str
    candidates_after_filter: list[str] = Field(default_factory=list)
    registry_version: int


# --------------------------------------------------------------------------- evaluation


class CheckResult(Strict):
    name: str
    category: Literal[
        "Contract", "Execution", "Data", "Analytical quality", "Grounding", "User value", "Governance"
    ]
    blocking: bool
    passed: bool
    score: float = Field(ge=0, le=1)
    observed: str = ""
    expected: str = ""
    evidence: str = ""


class CategoryScore(Strict):
    category: str
    score: float
    passed: bool


class EvaluationReport(Strict):
    report_version: Literal["evaluation/1"] = CONTRACT_REPORT
    report_id: str
    subject: Literal["committed", "candidate"]
    capability_id: str
    capability_version: str
    content_hash: str
    harness_version: str
    config_version: str
    checks: list[CheckResult]
    categories: list[CategoryScore]
    blocking_passed: int
    blocking_total: int
    warnings_raised: int
    overall_score: float
    verdict: Literal["pass", "fail"]
    created_at: str = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- records


class StateChange(Strict):
    state: str
    at: str = Field(default_factory=utcnow)
    note: str = ""


class AttemptRecord(Strict):
    attempt_id: str
    request_id: str
    candidate_number: int
    analysis_key: str
    history: list[StateChange] = Field(default_factory=list)
    admission_violations: list[str] = Field(default_factory=list)
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None
    run_id: Optional[str] = None
    content_hash: Optional[str] = None
    verdict: Optional[str] = None
    outcome: Literal["in_progress", "committed", "quarantined"] = "in_progress"


class FailureContext(Strict):
    stage: str
    reason: str
    committed_state_unchanged: Optional[bool] = None
    quarantined_attempts: list[str] = Field(default_factory=list)


class Answer(Strict):
    source: Literal["existing", "new"]
    capability_id: str
    capability_version: str
    run_id: str
    tool_result: ToolResult
    evaluation: Optional[dict[str, Any]] = None


class RequestRecord(Strict):
    request_id: str
    question: str
    scene_id: str
    state: str
    history: list[StateChange] = Field(default_factory=list)
    intent: Optional[Intent] = None
    match: Optional[MatchDecision] = None
    attempts: list[str] = Field(default_factory=list)
    answer: Optional[Answer] = None
    failure: Optional[FailureContext] = None
    created_at: str = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- generation


class GenerationClass(ColorClass):
    pass


class GenerationOutput(Strict):
    """What the generator LLM must return: analytical logic and declarations only."""

    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=10, max_length=400)
    formula: str = Field(min_length=3, max_length=300)
    citation: str = Field(default="", max_length=300)
    required_bands: list[str] = Field(min_length=1)
    value_label: str
    value_unit: str
    value_min: float
    value_max: float
    classes: list[GenerationClass] = Field(min_length=2, max_length=8)
    compute_values_source: str = Field(min_length=20)
    finding_rules: list[FindingRule] = Field(min_length=1, max_length=6)
    next_steps: list[NextStepRule] = Field(min_length=1, max_length=4)
