# AgriMon · Project folders

The repository is split into trust zones. Discovery reads only `capabilities/registry.json`, so
nothing outside committed state can ever be matched or run as a normal capability.

![Project folders by trust zone](project-folders.svg)

## Top-level folders

| Folder | Trust zone | Purpose | Written by |
| --- | --- | --- | --- |
| `agrimon/` | Trusted code | The backend: one Python package with a subpackage per component | Developers |
| `web/` | Trusted code | Three-panel UI (`index.html`) and evaluation harness page (`harness.html`), plain HTML, CSS and JavaScript | Developers |
| `scripts/` | Trusted code | `reset_demo.py` rebuilds the seed state; `prepare_assets.py` rebuilds the catalog and probe rasters | Developers |
| `assets/scenes/` | Trusted data | The true-color scenes (two USGS EROS images) | Developers |
| `assets/catalog.json` | Trusted data | Per scene: id, file, bands, size, date, CRS, resolution, nodata | `prepare_assets.py` |
| `capabilities/registry.json` | Committed state | The only discovery index: every committed capability with its hash, contract, verdict and score | Registry commit only |
| `capabilities/<id>/<version>/` | Committed state | `capability.py`, `manifest.json`, `evaluation.json`; write-once and read-only | Registry commit only |
| `capabilities/.pending-*/` | Committed state (transient) | A commit in progress; moved to quarantine by startup recovery if left behind | Registry commit only |
| `workspace/staging/<attempt>/` | Untrusted | A candidate in flight: code, manifest, staged run, harness runs, attempt record | Evolution engine |
| `workspace/quarantine/<attempt>/` | Untrusted | Rejected candidates with stage, reason and evaluation report; shown on the harness page, never matched | Evolution engine |
| `var/requests/` | Runtime records | One JSON record per request: state history, intent, match decision, failure context | Orchestrator |
| `var/runs/` | Runtime records | ToolResults from match-path runs | Runtime |
| `var/logs/` | Runtime records | `agrimon.jsonl` (app log) and `registry_audit.jsonl` (one line per commit) | Observability |
| `docs/` | Reference | Specs, workflows and diagrams | Developers |
| `tests/` | Reference | 104 tests in `unit/`, `integration/`, `evolution/`, `failure/`, with canned LLM responses in `fixtures/llm/` | Developers |
| Root files | Reference | `agrimon.toml` (how it runs), `app_spec.json` (what it is), `requirements*.txt`, `run.ps1`, `run.sh`, `.env.example`; `.env` holds the OpenAI key and is never shipped | Developers; `.env` by the user |

## `agrimon/` subpackages

| Subpackage | Component | Purpose |
| --- | --- | --- |
| `api/` | HTTP API | FastAPI endpoints and static pages |
| `orchestrator/` | Orchestrator | Request lifecycle, registry snapshot pinning, startup recovery, read models |
| `intent/` | Intent resolver | Turns a question into a structured intent with an analysis key (LLM) |
| `matching/` | Capability selector | Deterministic four-rule match; no LLM, no writes |
| `answers/` | Answer composer | Answer from the ToolResult plus visualization stats and evaluation summary |
| `evolution/` | Evolution engine | Generator, candidate assembly, admission, retry loop, quarantine |
| `evolution/templates/` | Capability template | Fixed header and footer, slot definitions, the seed capability |
| `harness/` | Evaluation harness | 21 checks, scoring and verdict; the commit gate |
| `harness/probes/` | Harness probes | Uniform and masked probe rasters; band and mirror variants are written per run |
| `runtime/` | Capability runtime | One subprocess per run, timeout, guardrail audit hook, scrubbed environment |
| `registry/` | Registry | Snapshots, integrity checks, fingerprint, atomic commit |
| `catalog/` | Imagery catalog | Loads and validates `assets/catalog.json` |
| `contracts/` | Contracts | Pydantic models: Intent, Context, ToolResult v2, manifest, EvaluationReport, records |
| `sdk/` | Capability SDK | Band loading, matrix aggregation, platform metrics, zones, class summary, ToolResult builder; called only by the fixed template footer |
| `config/` | Configuration | Reads `agrimon.toml` and `.env`; the only reader of the OpenAI key |
| `observability/` | Observability | JSON-lines logging with request, attempt and run ids |
