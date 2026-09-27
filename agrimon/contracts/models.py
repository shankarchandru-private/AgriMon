"""All cross-component contracts for Evolution 1.

Every JSON record the app reads or writes is validated by one of these models.
ToolResult is the stable platform boundary: strict about schema and types, open about the
analysis itself (no universal value ranges, no mandatory classes, zones only when meaningful).
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "ANALYSIS_KEY_PATTERN",
    "COLOR_MAPS",
    "CONTRACT_TOOLRESULT",
    "CONTRACT_MANIFEST",
    "ColorMapName",
    "Aggregation",
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
    "GridSize",
    "Zone",
    "ClassDef",
    "ClassSummary",
    "Classification",
    "Finding",
    "NextStep",
    "Interpretation",
    "Provenance",
    "Message",
    "ToolResult",
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
    "GenerationOutput",
]

ANALYSIS_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
CONTRACT_TOOLRESULT = "toolresult/2"
CONTRACT_MANIFEST = "manifest/2"
CONTRACT_REPORT = "evaluation/1"

# The platform's allowed visualization color maps. The generator picks one; the platform renders it.
COLOR_MAPS = ("greens", "blues", "reds", "purples", "ylorrd")
ColorMapName = Literal["greens", "blues", "reds", "purples", "ylorrd"]
# How per-pixel values are reduced to matrix cells. "mode" is for categorical (classified) rasters.
Aggregation = Literal["mean", "median", "min", "max", "mode"]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite(v: float) -> float:
    if not math.isfinite(v):
        raise ValueError("must be a finite number")
    return v


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
    output: Literal["matrix"] = "matrix"


# --------------------------------------------------------------------------- context


class BandRef(Strict):
    name: str
    index: int
    scale: float


class Context(Strict):
    """What a capability receives: the selected asset, its bands and dimensions, and request metadata.

    No secrets and no paths other than the read-only asset and the run folder.
    """

    # request metadata
    request_id: str
    run_id: str
    mode: Literal["committed", "staged", "probe"]
    question: str = ""
    analysis_key: str = ""
    # selected asset
    asset_id: str
    asset_label: str
    asset_date: str
    asset_path: str
    asset_width: int = Field(gt=0)
    asset_height: int = Field(gt=0)
    bands: list[BandRef]  # available bands
    nodata: Optional[float] = None
    resolution_m: Optional[float] = None
    # platform settings
    grid_rows: int = Field(ge=8, le=512)
    grid_cols: int = Field(ge=8, le=512)
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_dir: str
    # provenance
    capability_id: str
    capability_version: str
    content_hash: str
    template_version: str
    config_version: str


# --------------------------------------------------------------------------- ToolResult v2


class Metric(Strict):
    name: str
    value: float
    unit: str = ""
    description: str = ""
    source: Literal["platform", "capability"]

    @field_validator("value")
    @classmethod
    def _finite_value(cls, v: float) -> float:
        return _finite(v)


class GridSize(Strict):
    rows: int = Field(ge=8, le=512)
    cols: int = Field(ge=8, le=512)
    cell_width_px: float = Field(gt=0)
    cell_height_px: float = Field(gt=0)
    cell_size_m: Optional[float] = None


class Zone(Strict):
    """A connected spatial region that the analysis itself defined (optional in ToolResult)."""

    id: str  # "<name>-<k>", largest first
    name: str  # the region type named by the capability, e.g. "green_dominant"
    cell_count: int = Field(ge=1)
    share_pct: float = Field(ge=0, le=100)
    mean_value: float
    area_m2: Optional[float] = None
    row_min: int
    row_max: int
    col_min: int
    col_max: int
    cells: list[tuple[int, int]]

    @field_validator("mean_value", "share_pct")
    @classmethod
    def _finite_value(cls, v: float) -> float:
        return _finite(v)


class ClassDef(Strict):
    id: int = Field(ge=0, le=255)
    label: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)


class ClassSummary(ClassDef):
    cell_count: int = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)


class Classification(Strict):
    classes: list[ClassSummary] = Field(min_length=2)


class Finding(Strict):
    id: str = Field(pattern=r"^F\d{1,2}$")
    statement: str = Field(min_length=5, max_length=500)
    evidence: list[str] = Field(min_length=1)  # metric names, zone ids or "class:<id>"


class NextStep(Strict):
    type: Literal["follow_up_analysis", "human_inspection"]
    description: str = Field(min_length=5, max_length=400)
    follows_from: str  # finding id


class Interpretation(Strict):
    """What the capability's interpret() returns."""

    summary: str = Field(min_length=10, max_length=1200)
    findings: list[Finding] = Field(min_length=1, max_length=8)
    next_steps: list[NextStep] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def _links(self) -> "Interpretation":
        ids = [f.id for f in self.findings]
        if len(set(ids)) != len(ids):
            raise ValueError("finding ids must be unique")
        for s in self.next_steps:
            if s.follows_from not in ids:
                raise ValueError(f"next step follows unknown finding '{s.follows_from}'")
        return self


class Provenance(Strict):
    capability_id: str
    capability_version: str
    content_hash: str
    template_version: str
    asset_id: str
    asset_file: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    config_version: str
    started_at: str
    finished_at: str


class Message(Strict):
    code: str
    message: str


class ToolResult(Strict):
    contract_version: Literal["toolresult/2"] = CONTRACT_TOOLRESULT
    status: Literal["success", "partial", "failed"]
    layer_name: str = ""
    description: str
    analysis_type: str = ""
    asset_id: str = ""
    metrics: list[Metric] = Field(default_factory=list)
    matrix: Optional[list[list[Optional[float]]]] = None  # the analytical raster; None = nodata cell
    grid_size: Optional[GridSize] = None
    color_map: Optional[ColorMapName] = None
    zones: Optional[list[Zone]] = None  # only when the analysis defines meaningful regions
    classification: Optional[Classification] = None  # only when classification is part of the analysis
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
            return self
        missing = [n for n in ("matrix", "grid_size", "color_map", "provenance") if getattr(self, n) is None]
        missing += [n for n in ("layer_name", "analysis_type", "asset_id", "summary") if not getattr(self, n)]
        if not self.findings:
            missing.append("findings")
        if missing:
            raise ValueError(f"a successful ToolResult must carry: {', '.join(missing)}")
        g = self.grid_size
        if len(self.matrix) != g.rows or any(len(r) != g.cols for r in self.matrix):
            raise ValueError(f"matrix must be {g.rows}x{g.cols} to match grid_size")
        for row in self.matrix:
            for v in row:
                if v is not None and not math.isfinite(v):
                    raise ValueError("matrix values must be finite numbers or null")
        if self.provenance.asset_id != self.asset_id:
            raise ValueError("provenance.asset_id must equal asset_id")
        ids = {f.id for f in self.findings}
        for s in self.next_steps:
            if s.follows_from not in ids:
                raise ValueError(f"next step follows unknown finding '{s.follows_from}'")
        return self

    @classmethod
    def failure(cls, code: str, message: str, description: str = "Capability run failed") -> "ToolResult":
        return cls(status="failed", description=description, errors=[Message(code=code, message=message[:2000])])


# --------------------------------------------------------------------------- manifest


class CapabilityManifest(Strict):
    manifest_version: Literal["manifest/2"] = CONTRACT_MANIFEST
    id: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    template_version: str
    analysis_key: str
    aliases: list[str] = Field(default_factory=list)
    name: str
    description: str
    analysis_type: str
    layer_name: str
    required_bands: list[str] = Field(min_length=1)
    value_label: str
    value_unit: str = ""
    aggregation: Aggregation = "mean"
    color_map: ColorMapName
    classification: Optional[list[ClassDef]] = None
    method: str
    citation: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
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
    contract: str = "toolresult/1"  # entries committed before toolresult/2 default to the legacy contract


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
    visualization: Optional[dict[str, Any]] = None  # platform-derived display statistics


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


class GenerationOutput(Strict):
    """What the generator LLM returns: the analytical computation and its analytical metadata only."""

    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=10, max_length=400)
    analysis_type: str = Field(min_length=3, max_length=60)
    layer_name: str = Field(min_length=3, max_length=80)
    method: str = Field(min_length=3, max_length=400)
    citation: str = Field(default="", max_length=300)
    required_bands: list[str] = Field(min_length=1)
    value_label: str = Field(min_length=1, max_length=80)
    value_unit: str = Field(default="", max_length=30)
    aggregation: Aggregation = "mean"
    color_map: ColorMapName
    classification: Optional[list[ClassDef]] = None
    compute_source: str = Field(min_length=20)
    interpret_source: str = Field(min_length=20)

    @model_validator(mode="after")
    def _classification_rules(self) -> "GenerationOutput":
        if self.classification is not None:
            if len(self.classification) < 2:
                raise ValueError("classification needs at least two classes")
            if len({c.id for c in self.classification}) != len(self.classification):
                raise ValueError("classification ids must be unique")
            if self.aggregation != "mode":
                raise ValueError("a classified raster must use aggregation 'mode'")
        return self
