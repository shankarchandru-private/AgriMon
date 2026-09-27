# AgriMon — Evolution 1 Project Design Specification

Sep 26, 2026 · @Shankar

## Scope

Evolution 1 builds a match-or-create analytics system on real imagery. It splits into ten components with one writer for committed state and out-of-process execution for all capability code. This spec is implementation-ready: it fixes boundaries, stack, repository, contracts, API, build order and acceptance criteria. It contains no implementation code. It derives from the [AgriMon Product & Architecture Spec](https://claude.ai/code/artifact/b75a73c6-6f0f-4e03-89f8-08a8661ca337).

**Revision (contract v2).** After the first real run, the capability contract was revised: the platform owns execution, data access, validation, visualization, persistence, evaluation and provenance, and a generated capability owns only its analysis. ToolResult v2 carries a free-form analytical matrix with no required value ranges or classes, the harness grew to 21 behavioural checks, provenance hashes the persisted file bytes, and a runtime guard blocks I/O, network and process launches. The sections below reflect v2.

**In scope**

- Natural-language questions resolved to a structured intent
- A capability registry seeded with one hand-written foundational capability
- Match against the registry; on no match, generate a new Python capability
- Execute(Context) entry point and a structured ToolResult for every capability
- A small fixed catalog of real imagery with at least one RGB-compatible scene
- A typed evaluation report, opened from the answer in a separate UI tab
- Persistence of passing capabilities to the registry and project folder, with the UI updated without a restart

**Out of scope (Evolution 2 and later)**

- Composition: capabilities calling capabilities, pinned dependencies, trust propagation
- Promotion from Provisional to Trusted, and revocation cascades
- Qualitative review as a blocking gate
- Multi-tenant sharing of capabilities; live imagery ingestion

## Core invariant

> A failed capability generation, execution, evaluation, or persistence attempt cannot corrupt committed capabilities or prevent subsequent requests from being processed.

Seven boundary rules enforce it. Every component specification below must be read against them.

1. **Single writer.** Only the registry's commit operation writes committed state, and only the evolution engine may request a commit.
2. **Committed state holds only passing capabilities.** Anything uncommitted lives in staging or quarantine, which the matcher never reads.
3. **Atomic commit.** A capability's code, manifest and evaluation report become visible together, or not at all.
4. **Out-of-process execution.** Capability code never runs inside the backend, evolution engine or harness. The runtime always returns a ToolResult, including on failure; it never propagates an exception to its caller.
5. **Per-request isolation.** Each request pins a registry snapshot and has its own timeout, staging workspace and failure scope.
6. **Trusted evaluators.** The harness and the foundational capability are hand-written. Generated code cannot change them or see the harness's reference cases.
7. **Read-only inputs.** Assets and committed code are mounted read-only to every execution. Execution receives no secrets. Network blocking is deferred to production.

## System context

The backend is the only entry point. Committed and staged capabilities both execute in the capability runtime, and only the evolution engine can write to the registry.

&#91;embedded content: Evolution 1 system context · 10 components\]

The runtime loads committed code from the registry by content hash (not drawn). Persistence, configuration and observability serve every component, each under the access rules in its specification.

## Component specifications

Each component is defined by five things: responsibility, what it owns, what it consumes, what it produces, and who it talks to. "Owns" means it is the only component allowed to change that thing.

### 1. Frontend application

| Aspect | Definition |
| --- | --- |
| Responsibility | The user's only surface: ask questions, follow request progress, view answers, open a capability's evaluation report in a separate tab, browse the capability list |
| Owns | UI state and views; no persistent client state. No business logic and no direct access to data, registry or runtime |
| Consumes | From the backend, by polling: request status, answers (matrix, color map, visualization stats, metrics, zones, findings), capability cards, evaluation reports, registry listing |
| Produces | Questions with the selected scene; requests to open reports |
| Talks to | Backend only |

**UI layout: three panels, plus a harness page**

| Panel | Contents |
| --- | --- |
| Left | Data assets with catalog metadata; the capability list, each item clickable, the newest generated one marked New; a link that opens the evaluation harness page in a new tab |
| Middle | The question box and request stage status; the analysis matrix (default 48×48) drawn from the ToolResult matrix and color map: continuous layers scaled to the 2nd–98th percentile with a gradient legend, classified layers with a class legend, cell values on hover and any zones outlined |
| Right | Summary, findings with their evidence references, metrics, next steps, the evaluation verdict and category scores, and the raw ToolResult JSON in an expandable section |
| Harness page | One row per capability, with checks grouped by category: score, pass or fail, blocking or warning, evidence |

### 2. Backend application

| Aspect | Definition |
| --- | --- |
| Responsibility | The single entry point and orchestrator. Resolves intent, pins a registry snapshot, matches, dispatches to the runtime (match) or the evolution engine (no match), and composes the answer. Narrative text may cite only values present in a ToolResult |
| Owns | Request records and their state machine (Received → Intent resolved → Matched or No match → Executing or Evolving → Completed or Failed); intent resolution; matching logic; answer composition; the public API. Internal modules: Intent resolver, Matcher, Orchestrator, Answer composer |
| Consumes | Questions from the frontend; registry snapshots (read); the asset catalog (read); LLM service via configuration; ToolResults from the runtime; attempt outcomes from the evolution engine |
| Produces | Intent; match decisions with score and reason; Context objects; execution and evolution requests; answers; status events; request records |
| Talks to | Frontend, registry (read), data layer (catalog), runtime, evolution engine, persistence (request log), configuration, observability |
| Never | Runs capability code in its own process, or writes to the registry |

### 3. Capability runtime

| Aspect | Definition |
| --- | --- |
| Responsibility | Execute exactly one capability version against a Context in an isolated, resource-limited environment and return a validated ToolResult. The same runtime serves committed capabilities (match path) and staged ones (create path), distinguished by execution mode |
| Owns | The subprocess boundary, its configurable timeout and the guardrail audit hook (blocks file writes, network and process launches); the Execute(Context) invocation protocol; ToolResult schema validation; a per-run scratch workspace that is destroyed after the run |
| Consumes | Execution requests (capability reference by id, version and content hash, or staged artifact reference, plus a Context); capability code (read-only); normalized assets (read-only); limits from configuration |
| Produces | A ToolResult on every run, including structured errors for exceptions, timeouts, limit breaches and malformed output; output artifacts written to a per-run output area; run telemetry (duration, peak memory, exit reason) |
| Talks to | Backend and evolution engine (callers), evaluation harness (reruns), registry (reads code), data layer (reads assets), persistence (run outputs), observability |
| Never | Receives secrets, or writes to the registry, staging, quarantine or assets (network blocking deferred to production) |

### 4. Capability registry

| Aspect | Definition |
| --- | --- |
| Responsibility | System of record for committed capabilities: manifests, code artifacts, evaluation report references and versions. Serves lookups for matching and performs atomic commits |
| Owns | The registry index and version counter; committed code artifacts (write-once, addressed by content hash); the commit protocol; the seeded foundational capability |
| Consumes | Commit requests from the evolution engine only, each carrying a staged artifact, a manifest and a passing evaluation report; read requests from the backend and runtime |
| Produces | Immutable versioned snapshots; lookup results; the committed capability folders under capabilities/ |
| Talks to | Evolution engine (sole writer), backend (reads), runtime (code reads), persistence (registry store), observability (audit log) |
| Evolution 1 states | Seeded and Committed only. Staged and Quarantined candidates never enter the registry |

### 5. Evolution engine

| Aspect | Definition |
| --- | --- |
| Responsibility | On no match, produce a new capability and take it through Generate → Admit → Stage → Execute (via runtime) → Evaluate (via harness) → Commit (via registry) or Quarantine. Retries generation a bounded number of times with failure feedback |
| Owns | Generation prompts and the capability scaffold (Execute(Context) in, ToolResult out); admission rules (entry-point signature, no imports, forbidden calls, names and attributes, manifest completeness, duplicate check); per-attempt staging workspaces; the quarantine store; attempt records and their state machine |
| Consumes | Evolution requests (Intent, no-match reason, request id); a registry snapshot for duplicate checks; asset catalog metadata (bands, sensors, dates); LLM service via configuration; ToolResults; evaluation reports; retry limits and allowlists from configuration |
| Produces | Candidate code and manifest; admission report; the staged run's ToolResult, which becomes the answer for this request; a commit request, or a quarantine record with failure context; attempt events |
| Talks to | Backend (caller), runtime, evaluation harness, registry (commit), persistence (staging, quarantine), configuration, observability |
| Never | Executes candidate code itself, sees the harness's checks, probes or thresholds, or writes the registry except through commit |

### 6. Evaluation harness

| Aspect | Definition |
| --- | --- |
| Responsibility | Independently judge a candidate and produce a typed EvaluationReport with a result per check and an overall verdict. Hand-written and trusted; never generated |
| Owns | The check catalog; probe rasters and input variants (inverted bands, mirrored scene), hidden from the generator; blocking-versus-warning classification; the EvaluationReport schema |
| Consumes | Candidate manifest and ToolResult; additional runs requested through the runtime; its own probe rasters and the catalog's RGB scene; thresholds from configuration |
| Produces | EvaluationReport and verdict, stored for display in the UI |
| Talks to | Evolution engine (caller), runtime (reruns), data layer (reference assets), persistence (reports), observability |

**Evolution 1 evaluation categories.** The report tab shows this as a table grouped by category. Each check is scored from 0 to 1, a category's score is the mean of its checks, and the verdict passes only when every blocking check passes.

| Category | Check | Blocking | Passes when |
| --- | --- | --- | --- |
| Contract | Schema conformance | Yes | ToolResult v2 validates against its Pydantic model with status success |
| Contract | Matrix and grid size | Yes | Matrix is JSON numbers or null, 32–96 per side, and equals the requested grid |
| Contract | Asset and color map | Yes | `asset_id` is the selected asset; color map is one of the five allowed |
| Execution | Clean run | Yes | Finished within the timeout, no exception, no guardrail violation |
| Execution | Reproducibility | Yes | A second run gives an identical matrix, metrics, zones and text |
| Data | Required data available | Yes | Every declared band exists in the asset |
| Data | Input dependence | Yes | Inverting any declared band changes the matrix (no unused or fabricated inputs) |
| Analytical quality | Data-derived matrix | Yes | At least half the cells valid, varied values, and a mirrored input gives a mirrored matrix (r ≥ 0.9) |
| Analytical quality | Probe behaviour | Yes | Uniform input gives a uniform matrix; a masked area gives null cells only there |
| Analytical quality | Metrics consistency | Yes | Platform statistics recompute from the matrix; metric names unique and finite |
| Analytical quality | Zones and classes consistency | Yes | Zone cells, means, shares and class counts recompute from the matrix (passes when neither is returned) |
| Grounding | Numbers traced | Yes | Every number in the summary and findings appears in metrics, zones or classes |
| Grounding | Evidence references | Yes | Every finding cites a returned metric, zone or class |
| Grounding | No unsupported prescriptions | Yes | No treatments, rates, spraying, irrigation or fertilizer in summary, findings or next steps |
| Grounding | Methodology reference | Warning | A citation is recorded when the method is not self-evident; absence is never a failure |
| User value | Answers the intent | Warning | LLM-judged score of at least 0.6 |
| User value | Useful result | Warning | Summary names the asset, with findings, next steps and a layer name |
| Governance | Admission passed | Yes | All seven ast rules passed before execution |
| Governance | Not a duplicate | Yes | No committed capability with the same id or analysis key |
| Governance | Provenance chain | Yes | SHA-256 of the persisted file bytes equals the Context, ToolResult and report hash |
| Governance | Committed state untouched | Yes | `capabilities/` is byte-identical before and after all candidate runs |

No check imposes a universal value range, min/max bounds or classes.

### 7. Imagery/data layer

| Aspect | Definition |
| --- | --- |
| Responsibility | Provide validated, read-only imagery from a small fixed catalog. Validation runs at startup, not per request |
| Owns | Scenes in assets/scenes/; assets/catalog.json (id, sensor, bands with scale factors, acquisition date, CRS, dimensions, resolution, nodata); source validation rules |
| Consumes | Static imagery and field boundaries provided at deployment; normalization targets from configuration |
| Produces | The asset catalog; read-only normalized assets; validation reports (rejected assets with reasons) |
| Talks to | Backend (catalog), evolution engine (catalog metadata only), runtime (asset reads), harness (scene metadata), observability |

### 8. Persistence

Persistence is a set of separate stores, each with exactly one writer. No store is shared between committed and uncommitted state.

| Store | Writer | Readers | Rule |
| --- | --- | --- | --- |
| Registry store (incl. project-folder capability files) | Registry | Backend, runtime | Write-once; atomic commit |
| Staging store | Evolution engine | Runtime | Per attempt; disposable |
| Quarantine store | Evolution engine | Backend, observability | Append-only; kept for diagnosis |
| Run outputs store | Runtime | Backend, harness, frontend via backend | Per run; retention policy |
| Evaluation reports store | Harness | Engine, registry, frontend via backend | Append-only |
| Request log | Backend | Backend, observability | Append-only records |
| Asset store | Data layer (load time only) | Runtime, harness | Read-only at run time |

**Recovery on restart:** in-flight attempts are marked failed, staging workspaces are cleared, the registry index is verified against its artifacts.

### 9. Configuration/secrets

| Aspect | Definition |
| --- | --- |
| Responsibility | Provide validated configuration at startup and hand secrets only to the components that need them. Startup fails fast on invalid configuration |
| Owns | LLM credentials and model selection per role (intent resolution, generation); runtime limits; request timeout; generation retry limit; matching threshold; harness thresholds and blocking classification; import allowlist; asset paths and normalization targets |
| Consumes | Deployment environment inputs |
| Produces | Typed configuration per component; a configuration version stamped on every request record and evaluation report |
| Talks to | Backend and evolution engine (including secrets); runtime and harness (limits and thresholds only); data layer (asset settings) |
| Never | Passes secrets to the runtime or into generated code |

### 10. Observability

| Aspect | Definition |
| --- | --- |
| Responsibility | Make every request, attempt, run and commit traceable, and supply the failure context shown to users |
| Owns | Structured logs; traces linked by one correlation chain (request → attempt → run → evaluation report → capability version); the append-only audit log of registry commits |
| Consumes | Events from every component |
| Produces | Traces; the audit trail; failure summaries that the backend turns into user-facing explanations |
| Talks to | All components (inbound events); backend (failure-context queries) |

**Evolution 1 signals** come from logs and request records; there is no metrics endpoint. Signals: match rate, generation success rate, admission and evaluation pass rates, quarantine reasons, latency per stage, timeouts, and requests completed after a prior failure (the invariant's own health signal).

## Request flows

Both paths share the first three steps and end with the same answer shape. The create path adds generation, staging, evaluation and commit or quarantine.

**Shared start**

1. The frontend submits a question. The backend creates a request record in state Received.
2. The backend resolves the question into a structured Intent, using the LLM and the asset catalog. If the question is ambiguous, the Intent records the assumptions made, and the UI shows them.
3. The backend pins the current registry snapshot for this request and matches the Intent against capability manifests. The result is a match or no match, with a score and a reason.

**Match path**

4. The backend builds a Context (asset references, area, time window, parameters) and asks the runtime to execute the matched capability version.
5. The runtime returns a ToolResult. The backend composes the answer; the narrative cites only ToolResult values.
6. The frontend shows the answer. The capability card links to the capability's stored evaluation report.

**Create path**

4. The backend sends the Intent to the evolution engine, which opens an attempt record.
5. The engine generates code and a manifest, then runs admission checks. On failure it regenerates with feedback up to the retry limit, then quarantines.
6. The engine stages the candidate in a per-attempt workspace. The runtime executes it in staged mode against the request's Context.
7. The harness evaluates the candidate, requesting a repeat run, band-inverted and mirrored runs and probe runs through the runtime, and produces an EvaluationReport.
8. On pass, the engine requests a commit. The registry commits atomically, replaces registry.json; the new capability appears in the UI on its next poll. On fail, the candidate is quarantined with its report.
9. The backend composes the answer from the staged ToolResult, marked as produced by a new capability, with the capability card and a link to its report. On failure, it returns the failure context and confirms nothing committed was affected.

## Cross-component contracts

Six contracts cross component boundaries. Their exact schemas are part of the formal specification; the contents below are the minimum each must carry.

| Contract | Produced by | Consumed by | Minimum contents |
| --- | --- | --- | --- |
| Intent | Backend | Backend (matcher), evolution engine | Original question; analysis type and metric; area (field ids); time window; output form; stated assumptions; an existing analysis key or a proposed new one |
| Context | Backend | Runtime, then the capability | Request and run ids; question and analysis key; the selected asset (id, path, size, bands, nodata, resolution); grid size; parameters; output location; capability id, version and content hash of the persisted file. No secrets and no paths outside read-only mounts |
| ToolResult | Capability, validated by runtime | Backend, harness | See ToolResult v2 below |
| CapabilityManifest | Evolution engine, or hand-written for the seed | Registry, matcher | Id; version; content hash; name; description; intent signature for matching; parameter schema; required inputs (sensors, bands); layer name and analysis type; value label and unit; aggregation; color map; classification only when requested; method and citation; contract version; originating request id |
| EvaluationReport | Harness | Evolution engine, registry, frontend | Per check: name, category, blocking or warning, pass or fail, observed versus expected, evidence. Overall verdict; harness version; configuration version; timestamps |
| AttemptRecord | Evolution engine | Backend, observability | State transitions; admission results; retries; failure stage and reason; links to staged artifact, ToolResult and report |

### ToolResult v2 (revised)

The platform owns execution orchestration, data access, validation, visualization, persistence, evaluation and provenance. A generated capability owns only the analytical computation (`compute`) and its interpretation (`interpret`). Visualization no longer shapes the contract: no universal value range, no required min/max bounds, zones optional, classification only when the question asks for it. v1 capabilities stay on disk but are never matched.

| Field | Content |
| --- | --- |
| `status` | `success`, `partial` or `failed` (failed carries errors and no findings) |
| `layer_name`, `description`, `analysis_type` | What the layer is and how it was computed |
| `asset_id` | The asset analysed; must equal `provenance.asset_id` |
| `metrics` | Platform matrix statistics (`matrix_mean/min/max/std`, `valid_cells`, `nodata_cells`) plus capability metrics, each tagged with its source |
| `matrix` | JSON rows × cols (48×48 default) of numbers or null, derived from the input |
| `grid_size` | Rows, cols, cell size in pixels (and metres when georeferenced) |
| `color_map` | One of `greens`, `blues`, `reds`, `purples`, `ylorrd`, chosen by the generator |
| `zones` | Optional: connected regions from capability masks, with cells, share and mean |
| `classification` | Optional: classes with counts and shares (aggregation `mode`) |
| `summary`, `findings`, `next_steps` | Written from evidence only; findings cite metrics, zones or classes; next steps are follow-up analysis or human inspection |
| `provenance` | Capability id, version, content hash of the persisted file, asset, parameters, config, timestamps |

The platform derives display statistics (observed range, 2nd–98th percentile display range, histogram) from the matrix for the UI.

### Seed capability: true-color overview (rgb\_overview 1.0.0)

Evolution 1 starts with an RGB brightness overview. It proves the loop on real imagery without needing spectral bands the catalog may not have. Multispectral indices such as NDVI are added only once the catalog holds the bands they need.

| Aspect | Definition |
| --- | --- |
| Input | One RGB-compatible scene, with red, green and blue bands declared in the catalog |
| Computation | Per-pixel brightness as a luminance-weighted mean of red, green and blue (Rec. 709 weights: 0.2126, 0.7152, 0.0722), scaled to 0–1 using the catalog's scale; aggregated to a 48×48 matrix by cell mean |
| Classes | None. Brightness is continuous, so there are no fixed ranges or classes |
| Zones | The brightest and darkest regions: connected areas at or above the scene's 90th percentile and at or below its 10th percentile |
| Metrics | Platform matrix statistics (mean, minimum, maximum, standard deviation, valid and nodata cells) plus brightness\_p10 and brightness\_p90 |
| Findings | Statements such as the darkest region's share of cells and mean brightness, each citing its metric or zone |
| Next steps | Human inspection of the darkest and brightest regions (shadow, water, bare soil or wet ground cannot be told apart from brightness alone); follow-up analysis once spectral bands are available |

A natural first create-path demo: *"Where does vegetation appear in this image?"* No committed capability matches. The generator produces an RGB vegetation proxy, Excess Green (ExG = 2g − r − b on normalized chromatic coordinates), within the fixed template. It is always labelled an RGB vegetation proxy, never NDVI.

## Failure containment

Every failure stops inside one request or one attempt. In every row, committed capabilities are untouched and the next request is processed normally.

| Failure | Contained by | Effect on state | User sees |
| --- | --- | --- | --- |
| Generation fails (LLM error, invalid code, timeout) | Evolution engine attempt scope | Attempt quarantined after retries | "Couldn't build a method for this" with the reason |
| Admission fails | Evolution engine admission gate | Attempt quarantined after retries; code never executed | Which checks failed |
| Execution fails (exception, timeout, guardrail violation, malformed output) | Runtime isolation; error ToolResult | Run environment discarded; candidate quarantined | Failing step and reason |
| Evaluation fails | Harness verdict | Candidate quarantined with its report | The report, with failing checks highlighted |
| Persistence fails during commit | Atomic commit | Registry version unchanged; no partial capability visible | Answer shown, marked "not saved", with the reason |
| Backend crashes mid-request | Restart recovery | Request marked failed; staging cleared; registry verified | Request failed; safe to ask again |
| A committed capability fails on the match path | Runtime isolation; error ToolResult | Committed artifact unchanged; failure counted for review | Failing step and reason |
| Runtime repeatedly failing or hanging | Circuit breaker per capability | Other capabilities keep serving | That capability is temporarily unavailable |
| Two requests generate for the same intent concurrently | Pinned snapshots; serialized commits with a duplicate check | At most one of the duplicates is committed | Both get answers; one capability is saved |

## Technology stack

Evolution 1 runs as one local Python process that stores everything as JSON files and serves a web page with no build step. Each generated capability runs in its own Python subprocess with a timeout, so a crash or hang ends only that run. Security isolation is a production concern, deferred beyond Evolution 1.

| Layer | Selection | Rationale | Requirement satisfied |
| --- | --- | --- | --- |
| Language | Python 3.12 for backend, capabilities, runtime and harness | One language across orchestration, generated code and the imagery stack; LLMs generate Python reliably | Generation of Python capabilities |
| Backend framework | FastAPI, served by Uvicorn | Pydantic models are its native types; async suits long-running jobs; also serves the static frontend | Backend application; structured contracts |
| API | JSON over HTTP; the frontend polls request status | Polling is the simplest way to show stage progress; no streaming layer | Natural-language requests; stage status; new capabilities appear on the next poll |
| Frontend | Static HTML, hand-written CSS, vanilla JavaScript; the result grid drawn on an HTML canvas from the ToolResult's grid and color map | A few panels need no framework; a 48×48 grid is simple to draw client-side, so no map library | Frontend; result display; evaluation report tab |
| Imagery processing | rasterio (bundles GDAL) and NumPy | rasterio reads the GeoTIFF bands and metadata; NumPy computes indices and aggregates pixels into grid cells. Both install as pip wheels | Execution against real imagery; source normalization |
| Imagery | A small fixed catalog of real raster scenes in assets/, at least one RGB-compatible (e.g. a Sentinel-2 true-color clip); multispectral Sentinel-2 bands added later | Static and small; RGB supports the brightness overview and the Excess Green proxy; multispectral indices wait until their bands are in the catalog | Real imagery as static assets |
| LLM integration | Official OpenAI Python SDK; JSON-mode responses validated by Pydantic models; model configurable per role (intent resolution, generation) | Returns valid Intent, manifests and code directly; matching itself is deterministic; no agent framework needed | Natural-language requests; capability generation |
| Capability execution | One Python subprocess per run via a trusted runner, with a configurable timeout, a per-run folder and a guardrail audit hook; the OpenAI key is not passed in | A crash, hang or exception ends only that subprocess, which is what the core invariant needs | Failed execution cannot stop later requests |
| Capability SDK | A small trusted module called only by the fixed template footer: loads bands, aggregates the matrix, computes platform metrics, zones and class summaries, and builds the ToolResult | Shrinks generated code and keeps outputs contract-shaped | Execute(Context) and ToolResult contracts |
| Admission | Python's built-in ast module | Fixed sections unchanged, no imports, and no forbidden calls, names or attributes, with no extra dependency | Capability validation before execution |
| Schemas | Pydantic v2, with pydantic-settings for configuration | One definition gives validation, validation of every LLM response, and API docs | Intent, Context, ToolResult, manifest, EvaluationReport |
| Persistence | JSON files in the project folder: registry.json, a manifest per capability, request and attempt records, evaluation reports, and an app\_spec file; committed capability folders treated as read-only | Inspectable and zippable; an atomic file replace on one volume gives all-or-nothing commits | Persistent registry; atomic commit; quarantine |
| Evaluation | Pydantic check models grouped by category, shown as a table in the report tab | Scores and pass/fail per check map directly to the UI; no evaluation library needed | Evaluation before commit; report in UI |
| Observability | Standard-library logging with a JSON-lines formatter; correlation ids via contextvars; append-only commit audit log | No infrastructure; one file answers "what happened to request X" | Observability; failure context |
| Configuration/secrets | .env for the OpenAI key (never zipped; .env.example shipped); agrimon.toml for settings, read with the built-in TOML parser; both validated at startup | The key stays out of subprocesses and out of the shared zip | Configuration/secrets |
| Local environment | venv with pinned requirements.txt; run.ps1 and run.sh; one command starts the app on localhost | Unzip, install, run; nothing else to install | Shareable local prototype |

### Deliberately excluded

| Excluded | Why Evolution 1 doesn't need it |
| --- | --- |
| Database (SQLite, Postgres) | Records are few and file-shaped; an atomic file replace gives all-or-nothing commits |
| Task queue (Celery, Redis) | One process with async tasks and a concurrency limit; capability work already runs in subprocesses |
| Containers and OS-level sandboxing (Docker, network namespaces, memory watchdogs) | The prototype is single-user and local; a subprocess with a timeout, admission rules and an audit-hook guard protect later requests and committed state |
| Map library (Leaflet) and basemaps | Results are shown as a 48×48 matrix, not a map |
| Frontend framework, build tools | A handful of panels |
| WebSockets, SSE, UI caching, metrics endpoint | Request-status polling covers progress |
| Agent frameworks (e.g. LangChain) | A few direct, structured LLM calls |
| geopandas, xarray, Shapely | The grid approach needs only rasterio and NumPy |
| OpenTelemetry, Prometheus | JSON logs and request records are enough locally |
| Conda | pip wheels cover rasterio on all three operating systems |

### Deferred to production

These are known gaps, accepted for the prototype and recorded so the production design addresses them.

- **Security isolation.** The subprocess, admission rules and audit-hook guard are defence in depth, not a security boundary. Production needs sandboxed execution (containers or equivalent), network blocking and enforced memory limits.
- **Tamper-proof registry.** The prototype marks committed files read-only and re-checks the content hash at commit and before every run, refusing a mismatch. Production needs enforced immutability such as signed artifacts on protected storage.
- **Dynamic imagery.** The prototype reuses one or two static clips. Production needs ingestion, cloud masking and normalization across scenes and dates.
- **Georeferenced display.** The prototype shows a grid. Production likely needs a map view with the grid overlaid on its true location.

## Repository design

The repository has five trust zones, each in its own top-level folder: trusted code (agrimon/, web/), trusted data (assets/), committed capabilities (capabilities/), untrusted artifacts (workspace/), and runtime records (var/). Discovery reads only capabilities/registry.json, so nothing outside it can ever be matched or executed as a normal capability.

### Layout

```text
agrimon/                     trusted application package
  api/                       HTTP endpoints, request status
  orchestrator/              request lifecycle, match-or-create dispatch
  intent/                    LLM intent resolution into a structured Intent
  matching/                  deterministic matching against manifests and contracts
  answers/                   answer assembly from the ToolResult
  evolution/                 generation, admission, staging, commit request, quarantine
    templates/               the fixed capability template and generation prompts
  harness/                   evaluation checks and report builder (never exposed to the generator)
    probes/                  synthetic probe rasters and their expected behaviour
  runtime/                   subprocess runner, configurable timeout, ToolResult validation
  registry/                  index, snapshots, atomic commit, startup recovery
  catalog/                   asset catalog loading and source validation
  contracts/                 Pydantic models: Intent, Context, ToolResult, Manifest, EvaluationReport, AttemptRecord
  sdk/                       the only package generated code may import
  config/                    settings from agrimon.toml and .env
  observability/             JSON-lines logging, correlation ids, commit audit log
web/                         index.html (three panels), harness.html (evaluation table), css/, js/
capabilities/                committed capabilities only
  registry.json              the index; the only source of discovery
  rgb_overview/1.0.0/        seed: capability.py, manifest.json, evaluation.json
  <id>/<version>/            generated capabilities that passed the harness gate
assets/                      fixed raster catalog
  catalog.json               bands, CRS, dimensions, date and sensor per scene
  scenes/                    at least one RGB-compatible GeoTIFF
workspace/                   untrusted; never discoverable
  staging/<attempt_id>/      candidate code, manifest, staged run output
  quarantine/<attempt_id>/   rejected candidates with failure reason and evaluation report
var/                         runtime records
  requests/                  one JSON record per request
  runs/<run_id>/             ToolResult JSON from match-path runs
  logs/                      agrimon.jsonl, registry_audit.jsonl
tests/                       unit/, integration/, evolution/, failure/, fixtures/
docs/                        applicationOverview.md, architecture.md, evolution.md, capability-contract.md
scripts/                     prepare_assets, reset_demo
README.md  app_spec.json  agrimon.toml  .env.example  requirements.txt  run.ps1  run.sh
```

### Ownership, trust and lifecycle

| Path | Written by | Trust level | Lifecycle | Modifiable after creation |
| --- | --- | --- | --- | --- |
| agrimon/, web/, scripts/ | Developers | Trusted code | Versioned source | Developers only; never by the running app |
| agrimon/harness/ | Developers | Trusted; hidden from the generator | Versioned source | Developers only; never in a prompt; not importable by capabilities |
| agrimon/evolution/templates/ | Developers | Trusted | Versioned source | Developers only; the LLM fills the analytical body, never the interface |
| assets/ | Developers (catalog.json built by prepare\_assets) | Trusted data | Fixed for Evolution 1 | No; read-only at run time |
| capabilities/registry.json | Registry commit only | Index of committed capabilities | Replaced atomically on each commit | Replaced whole; never edited in place |
| capabilities/\<id>/\<version>/ | Registry commit only (seed written by developers) | Committed | Created at commit; permanent | No; write-once |
| workspace/staging/\<attempt\_id>/ | Evolution engine | Untrusted | One attempt; promoted on pass, moved to quarantine on fail, cleared at startup | Only during its own attempt |
| workspace/quarantine/\<attempt\_id>/ | Evolution engine | Untrusted, rejected | Kept for diagnosis; cleared only by reset\_demo | No |
| var/requests/ | Backend | Runtime record | One file per request | Updated until the request completes, then frozen |
| var/runs/\<run\_id>/ | Runtime | Runtime record | One per match-path run | No |
| var/logs/ | Observability | Runtime record | Append-only | Append only |
| app\_spec.json | Developers | Trusted description of the app | Versioned; read at startup | Developers only |
| agrimon.toml | Developers | Trusted configuration | Versioned | Developers only |
| docs/, tests/, README.md | Developers | Reference | Versioned | Developers only |
| .env | The user, locally | Secret | Local only; never zipped | By the user |

**app\_spec.json** describes what the app is: evolution level, contract versions, the capability template version, the SDK import allowlist, the harness check list with blocking flags, grid defaults and the asset catalog path. **agrimon.toml** describes how it runs locally: paths, timeouts, models, retry limits.

**docs/** holds four files: applicationOverview.md (what AgriMon does and how to use it), architecture.md (components and trust zones), evolution.md (the match-or-create lifecycle and commit gate), capability-contract.md (the template, Context, ToolResult and grounding rules).

### Package boundaries and import rules

The backend is one Python package, agrimon, with one subpackage per responsibility. This adds no scope: it is the same code split along the component boundaries, and it makes the trust boundaries testable.

- Generated code imports nothing. The fixed template header provides NumPy (np), math and agrimon.sdk, and only the fixed footer calls the SDK; all raster access goes through it. Admission rejects any import and any reference to sdk or context in generated code.
- agrimon.sdk imports only agrimon.contracts. It never imports evolution, harness, registry or config.
- The evolution engine calls the harness as a function, but harness source, probes and thresholds never appear in a generation prompt.
- Only agrimon.registry writes under capabilities/. Only agrimon.evolution writes under workspace/.
- agrimon.matching reads registry snapshots and has no write path. It uses no LLM.
- Only agrimon.config reads .env, and the key is passed only to intent and evolution.

### Commit protocol

The harness is the commit gate: a candidate is committed automatically when all 18 blocking checks pass, with no user approval.

1. The registry copies the staged candidate to capabilities/.pending-\<attempt\_id>/ on the same volume.
2. It renames that folder to \<id>/\<version>/, marks its files read-only and re-hashes capability.py; a hash that differs from the evaluation report stops the commit.
3. It writes a new registry.json to a temporary file and atomically replaces the old one. **This replace is the commit point.**
4. It appends an audit entry and deletes the staging folder.

**Startup recovery:** any folder under capabilities/ that registry.json doesn't list, including .pending-\* folders, moves to workspace/quarantine/ as an orphan. Staging is cleared, and every indexed manifest is checked against its folder.

### Tests

Tests are written by developers and ship with the repository; the app does not generate them. Generating a regression test for each committed capability is a candidate for a later evolution. Every test runs in a temporary copy of the seed project state, with the LLM stubbed by canned responses.

| Folder | Verifies |
| --- | --- |
| unit/ | Contracts accept and reject correctly; deterministic matching; admission rules; each harness check by behaviour (continuous outputs without bounds or classes, optional zones, negative and above-1 values, input dependence, metric consistency, invalid ToolResult and color map, prescriptions, repeatability, persisted-byte provenance including CRLF); SDK matrix functions; runtime guardrails; the import rules above |
| integration/ | Match path end to end on the real RGB asset with the seed capability; API endpoints; startup recovery |
| evolution/ | Create path: a valid candidate is committed, becomes discoverable, is flagged New, and is matched on the next request; a duplicate is rejected |
| failure/ | The core invariant, one test per failure below |
| fixtures/ | A tiny RGB raster; canned LLM responses; known-good and known-bad capability sources; a seed-state registry |

**Every failure test has the same shape.** Fingerprint committed state (a hash of registry.json plus every file in committed capability folders). Inject the failure. Then assert three things: the fingerprint is unchanged; a quarantine or failure record with the reason exists; the next match-path request succeeds.

| Failure test | Injected failure | Extra assertion |
| --- | --- | --- |
| Generation fails | LLM stub raises or returns invalid output | Retries stop at the limit |
| Admission fails | Candidate imports a forbidden module or changes the entry point | Candidate is never executed |
| Execution crashes | Candidate raises an exception | Error ToolResult returned; server still serving |
| Execution hangs | Candidate loops forever | Subprocess killed at the configured timeout |
| Malformed ToolResult | Candidate omits or mistypes a field | Schema check fails |
| Evaluation fails | Ungrounded finding; prescriptive next step; non-reproducible output | Quarantined with its report |
| Persistence fails before the commit point | Crash after the folder rename, before the index replace | Recovery moves the orphan to quarantine |
| Persistence fails at the commit point | Index write fails | Previous registry.json intact |
| Concurrent duplicates | Two identical candidates reach commit together | Exactly one is committed |

Two more failure tests cover a guardrail violation that gets past admission and a candidate that requires a band the asset lacks, for eleven in all.

### Missing components added

- **agrimon/registry/**: the commit protocol and recovery were specified but had no home. This is the most safety-critical code in the repository.
- **agrimon/catalog/**: loads assets/catalog.json and validates sources.
- **agrimon/config/ and agrimon/observability/**: were implied, now explicit.
- **agrimon/evolution/templates/**: the fixed capability template.
- **agrimon/harness/probes/**: the synthetic inputs behind the probe-behaviour check.
- **scripts/**: prepare\_assets builds catalog.json; reset\_demo restores the seed state.
- **var/runs/**: match-path outputs moved out of workspace/, since they are data from trusted capabilities, not untrusted code.
- **A zip exclusion list**: .env, workspace/ and var/ are never shipped.

### Complexity removed

- **var/cache/ removed.** registry.json is small, so the UI reads it directly. The New flag comes from the most recent commit timestamp.
- **Metrics endpoint removed.** Logs and request records are enough for Evolution 1.
- **LLM matching removed.** Matching is deterministic.
- **SSE replaced with polling.** The frontend polls request status about once a second, leaving one fewer streaming path to get right.

* **Clarifying dialogue removed.** The intent resolver records its assumptions in the Intent instead of asking follow-up questions.
* **Free LLM narrative removed. Summaries and findings come from the capability's interpret function, which sees only computed evidence; the harness checks every number and reference**.

## Capability template and SDK

Every capability, seed or generated, is one capability.py assembled from the fixed template (version 2) plus a manifest.json. The platform owns execution, data access, validation, visualization, persistence, evaluation and provenance; the LLM owns only the analytical computation and its interpretation. The generated code may not touch the filesystem, network, credentials, processes, application state or the registry; admission rules block this before execution and a runtime guard in the subprocess blocks it during execution.

### Template sections

| Section | Owned by | Content |
| --- | --- | --- |
| Header | Template (fixed) | Imports of agrimon.sdk, NumPy and math only; template version marker |
| Slot 1: compute(bands, params) | LLM | Returns a per-pixel array, or values plus optional zone masks and extra metrics. No invented ranges or thresholds; np.nan where undefined |
| Slot 1: interpret(evidence) | LLM | Writes summary, findings with evidence references, and follow-up or inspection next steps from computed evidence only |
| Slot 2: literals | Trusted code from LLM declarations | LAYER\_NAME, ANALYSIS\_TYPE, DESCRIPTION, REQUIRED\_BANDS, VALUE\_LABEL, VALUE\_UNIT, AGGREGATION, COLOR\_MAP, CLASSIFICATION (only when requested), PARAMETERS |
| execute(context) → ToolResult | Template (fixed) | Loads bands, calls compute, aggregates to the matrix, adds platform metrics, builds zones and class summary, calls interpret with the evidence, validates and returns the ToolResult |

### SDK surface (agrimon.sdk)

| Function | Purpose |
| --- | --- |
| load\_bands(context, names) | Named bands scaled 0–1 as read-only arrays, plus a nodata mask |
| analysis\_output(out, shape) | Normalizes compute's return into values, optional zone masks and capability metrics; validates shapes and names |
| to\_matrix(values, nodata, rows, cols, aggregation) | Aggregates pixels to the matrix by mean, median, min, max or mode |
| matrix\_metrics(grid, unit) | Platform statistics of the matrix: mean, min, max, std, valid and nodata cells |
| zones\_from\_masks(masks, grid, context) | Largest connected regions per mask with cells, share, mean and area; none when no masks |
| class\_summary(grid, classes) | Cell counts and shares per declared class; none when no classification |
| evidence(...) | The computed values interpret may use |
| build\_result(...) | Assembles and validates the ToolResult v2 with provenance |

The fixed footer is the only caller of the SDK; generated code may not reference it.

### Admission rules (ast, before any execution)

1. The file parses, and its fixed header and footer are byte-identical to the current template version.
2. Slot 1 holds only function definitions: compute(bands, params), interpret(evidence) and private helpers whose names start with an underscore; no decorators, classes, globals or generators, and execute is not redefined.
3. No imports of any kind.
4. No calls to open, eval, exec, compile, \_\_import\_\_, globals, locals, getattr, setattr, vars or input; no references to os, sys, subprocess, socket, pathlib, shutil, sdk or context; no NumPy file I/O or random attributes, and no private attributes.
5. Slot 2 holds only the ten literal constants, within the configured file size.
6. The literals match the manifest; required bands exist in the selected asset; the color map is one of the five allowed; a classification uses mode aggregation.
7. The analysis key is not already committed (duplicate check against registry.json).

## Deterministic matching

Semantic judgment lives in intent resolution; matching is plain rule evaluation that can be audited and unit-tested. The intent resolver receives the list of committed analysis keys with their descriptions, and must either choose one or propose a new key. The matcher then applies four rules in order.

1. **Compatibility filter.** Keep capabilities whose required bands are all present in the selected scene and that were built for the current contract (toolresult/2).
2. **Key match.** Keep those whose analysis key, or one of its declared aliases, equals the Intent's analysis key exactly.
3. **Selection.** If several remain, take the highest version; on a tie, the most recent commit.
4. **Decision.** One capability selected → match path. None → create path, and the new capability is committed under the Intent's proposed key, so the same question matches next time.

Every decision is written to the request record with the rule that decided it. Example keys: brightness\_overview (seed) and vegetation\_proxy\_rgb (first generated). A candidate that requires a band the scene lacks, such as near-infrared for NDVI, fails admission.

## HTTP API and request states

The API is JSON over HTTP on localhost. The frontend polls request status about once a second; there is no streaming.

| Method | Path | Returns |
| --- | --- | --- |
| POST | /api/requests | Accepts a question and scene id; returns a request id |
| GET | /api/requests/{request\_id} | Current state, Intent and its assumptions, match decision, ToolResult reference, evaluation summary, or failure context |
| GET | /api/assets | The asset catalog |
| GET | /api/capabilities | registry.json entries, with the newest generated capability flagged New |
| GET | /api/capabilities/{id}/{version} | Manifest, evaluation summary and read-only source |
| GET | /api/runs/{run\_id} | ToolResult JSON |
| GET | /api/evaluations | One row per committed capability and quarantined attempt, for the harness page |
| GET | /api/evaluations/{report\_id} | A full EvaluationReport |
| GET | /api/health | Startup check results: configuration, catalog, registry integrity |

Static pages: / serves index.html (three panels) and /harness.html serves the evaluation table.

**Request states:** received → resolving\_intent → matching → executing (match path) or generating → admitting → executing\_staged → evaluating → committing (create path) → completed or failed. A failed request records the stage, the reason, and a statement that committed capabilities were not affected.

## Registry and record formats

All records are JSON files validated by Pydantic models in agrimon.contracts. registry.json is the authoritative discoverability index.

| File | Location | Key fields |
| --- | --- | --- |
| registry.json | capabilities/ | registry\_version; updated\_at; one entry per capability: id, version, analysis\_key, aliases, name, description, required\_bands, origin (seed or generated), committed\_at, source\_request\_id, content\_hash, contract, path, verdict, overall score |
| manifest.json | capabilities/\<id>/\<version>/ and staging | The CapabilityManifest: id, version, template version, analysis key, description, required bands, layer name, analysis type, value label and unit, aggregation, color map, optional classification, parameters, method and citation |
| evaluation.json | Beside each manifest, committed or quarantined | The EvaluationReport: per-check results, category scores, verdict, harness version |
| catalog.json | assets/ | Per scene: id, file, sensor, acquisition date, CRS, width and height, resolution, bands (name, index, scale factor), nodata value |
| Request record | var/requests/\<request\_id>.json | Question, scene id, state history with timestamps, Intent, match decision and deciding rule, attempt id, run id, failure context |
| Attempt record | workspace/staging or quarantine/\<attempt\_id>/attempt.json | State history, generation retries, admission results, failure stage and reason, links to candidate, ToolResult and report |
| ToolResult | var/runs/\<run\_id>/ or staging | ToolResult v1 |
| Audit log | var/logs/registry\_audit.jsonl | One line per commit: time, id, version, content hash, previous and new registry\_version |

## Configuration

agrimon.toml holds every non-secret setting; .env holds only OPENAI\_API\_KEY. Both are validated at startup, and the app refuses to start on an invalid value. Defaults below are starting points.

| Key | Default | Used by |
| --- | --- | --- |
| server.port | 8000 | API |
| llm.intent\_model | Set by the user | Intent resolver |
| llm.generation\_model | Set by the user | Evolution engine |
| runtime.timeout\_seconds | 60 | Runtime |
| evolution.max\_retries | 2 | Evolution engine |
| evolution.max\_source\_bytes | 20000 | Admission |
| grid.rows, grid.cols | 48, 48 | SDK, harness |
| (removed in v2: class\_spread\_warning) | 0.95 | Harness |
| harness.summary\_max\_chars | 600 | Harness |
| requests.max\_concurrent\_evolutions | 1 | Orchestrator |
| paths.assets, paths.capabilities, paths.workspace, paths.var | Relative to the project root | All |

One evolution runs at a time, which serializes commits without a lock service; match-path requests continue alongside it.

## Build plan

Approved plan: foundations first, then each pipeline stage in the order a request passes through it: Question → Intent → Match → Execute existing / Generate new → Validate → Evaluate → Commit or Quarantine → Answer + Visualize. Each step's exit criterion is validated before the next begins. Inputs: two USGS EROS true-color scenes, and gpt-4o-mini for intent resolution and generation; matching is deterministic.

| Step | Stage | Builds | Done when |
| --- | --- | --- | --- |
| F1 | Contracts and config | Pydantic models for Intent, Context, ToolResult (v2 after revision), manifest, EvaluationReport, request and attempt records; agrimon.toml and .env loading | Sample JSON validates, and malformed JSON is rejected |
| F2 | Asset catalog | catalog.json for the RGB scenes; catalog loader and validation; /api/health | Health check reports the scenes as valid |
| F3 | SDK and template | The eight SDK functions; the fixed execute(context) → ToolResult template | The SDK and template can execute a seed capability against the real scene and produce a valid 48×48 ToolResult with metrics, zones and summary |
| F4 | Registry (read) and seed | registry.json; rgb\_overview 1.0.0 built from the template | Registry loads and lists the seed |
| F5 | Runtime | Subprocess runner with configurable timeout; ToolResult validation; error ToolResult on failure | The seed runs in a subprocess; a hanging script is stopped at the timeout |
| P1 | User question | Request API with states and records; orchestrator; three-panel UI with question box and status polling | A question creates a request whose state shows in the UI |
| P2 | Intent resolution | LLM turns the question into a structured Intent and proposes an analysis key when needed; deterministic matching decides whether an existing capability satisfies the intent | Brightness question → brightness\_overview; vegetation question → a new proposed key |
| P3 | Capability match | Deterministic four-rule matcher; each decision logged with its rule | Matcher unit tests pass; the UI shows the match decision |
| P4 | Execute existing + answer | Runtime call; canvas grid, legend, metrics, findings with evidence, next steps, raw JSON; clickable capability list | First end-to-end: the brightness question shows the seed's grid and findings |
| P5 | Generate new | LLM writes compute and interpret plus analytical metadata; staging folder; attempt record; two retries | The vegetation question produces a staged candidate |
| P6 | Validate | Seven admission rules; staged execution; ToolResult schema validation | A valid candidate runs; a forbidden import is rejected before execution |
| P7 | Evaluate | Full harness: 21 checks (18 blocking, 3 warnings) with probes and input variants; the seed evaluated by the same harness | The Excess Green candidate passes all 18 blocking checks; the seed has its evaluation.json |
| P8 | Commit or quarantine | Commit protocol; audit log; quarantine with reason; startup recovery | Excess Green committed; a failing candidate quarantined with committed state unchanged |
| P9 | Answer + visualize (create path) | Answer labelled as a new capability; New flag; clickable capability card (description, key, method and citation, bands, color map, classes if any, verdict and category scores, creating summary); link to the harness page | Full loop: vegetation question → evaluated → auto-saved → displayed → clickable; asking again reuses it |
| H1 | Failure suite | Eleven failure tests plus integration and evolution tests with stubbed LLM responses | All pass: committed state unchanged, failure recorded, next request succeeds |
| H2 | Packaging | docs/ (four files), README, app\_spec.json, reset\_demo, zip exclusions | A fresh unzip runs from the README; all eight acceptance criteria pass |

## Acceptance criteria

Evolution 1 is done when all eight hold on a clean machine with Python 3.12 and an OpenAI key.

- [ ] **Install.** Unzip, create the venv, install requirements.txt, add the key to .env, run run.ps1 or run.sh; the app opens on localhost.
- [ ] **Match path.** "Give me a brightness overview" matches rgb\_overview, shows the 48×48 grid with brightest and darkest zones, and generates no code.
- [ ] **Create path.** "Where does vegetation appear?" finds no match, generates vegetation\_proxy\_rgb from the fixed template, passes all 18 blocking checks, commits automatically, and appears in the capability list marked New. The answer calls it an RGB vegetation proxy, not NDVI.
- [ ] **Reuse.** Asking the vegetation question again matches the new capability with no generation.
- [ ] **Grounding.** Every finding cites a metric or zone; every next step is follow-up analysis or human inspection.
- [ ] **Harness page.** Opens in a new tab and shows all 21 checks by category for every capability and quarantined attempt.
- [ ] **Invariant.** All eleven failure tests pass: committed state unchanged, failure recorded, next request succeeds.
- [ ] **Trust boundary.** Nothing under workspace/ is ever listed or matched; capabilities/ changes only through the commit protocol.

## Technical decisions before implementation

All fifteen decisions are resolved. The six Evolution 1 defaults are rows 2, 5, 6, 7, 9 and 11.

| # | Decision | Status | Selection |
| --- | --- | --- | --- |
| 1 | Deployment topology and users | Resolved | Single-user, local |
| 2 | Execution fault isolation | Resolved | Generated capabilities run in a Python subprocess with a configurable timeout; security isolation deferred to production |
| 3 | Registry storage and atomic commit | Resolved | JSON files plus an atomically replaced registry.json |
| 4 | Project-folder role | Resolved | capabilities/ holds trusted, committed capabilities only; staged and quarantined code lives under workspace/ and is never discoverable |
| 5 | Commit approval | Resolved | Automatic commit once all blocking admission, execution, ToolResult and evaluation checks pass; no user approval; the harness is the commit gate |
| 6 | Matching method | Resolved | The LLM resolves intent into a structured Intent; deterministic matching against capability metadata and declared contracts selects reusable capabilities |
| 7 | Generation approach | Resolved | Every generated capability conforms to a fixed template: execute(context) → ToolResult, with a controlled SDK. The LLM supplies only the analytical computation (compute) and its interpretation (interpret); imports, entry point, Context, ToolResult structure, platform metrics, zones, visualization and provenance belong to the platform |
| 8 | Admission depth | Resolved | ast checks (fixed sections unchanged, no imports, forbidden calls, names and attributes) plus a runtime audit-hook guard |
| 9 | Harness criteria | Resolved | 21 checks across seven categories: 18 block commit, 3 warn |
| 10 | Imagery set | Resolved | A small fixed catalog of real rasters with at least one RGB-compatible scene; the catalog declares bands, CRS, dimensions, date and sensor. Multispectral Sentinel-2 comes after the loop works |
| 11 | Foundational capability | Resolved | rgb\_overview: true-color brightness grid; the first generated capability is the Excess Green RGB vegetation proxy; NDVI and other multispectral indices wait for the required bands |
| 12 | Request processing model | Resolved | Async in-process jobs; the frontend polls request status; no SSE |
| 13 | Output formats and display | Resolved | ToolResult v2 matrix (default 48×48) with one of five color maps; the platform derives display statistics, drawn on a canvas in the three-panel UI |
| 14 | LLM roles and settings | Resolved | OpenAI SDK for intent resolution and capability generation only; summaries and findings are written by the capability's interpret function from computed evidence and checked by the harness; models set in agrimon.toml |
| 15 | app\_spec.json contents | Resolved | What the app is: contract and template versions, SDK allowlist, harness checks, grid defaults, catalog path |
