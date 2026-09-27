# AgriMon · Architecture (Evolution 1)

One local Python process (FastAPI) serves the API and a no-build web page. Capability code always runs
in a separate Python subprocess. Everything persists as files in the project folder; there is no
database, container, queue or frontend framework.

## Components and packages

| Component | Package / folder | Responsibility |
| --- | --- | --- |
| Frontend | `web/` | Three panels, polling, canvas grid, harness page |
| API | `agrimon/api` | JSON endpoints and static pages |
| Orchestrator | `agrimon/orchestrator` | Request lifecycle, startup recovery, read models |
| Intent resolver | `agrimon/intent` | LLM question → structured Intent; proposes an analysis key |
| Matcher | `agrimon/matching` | Deterministic four-rule match over a pinned registry snapshot |
| Answer composer | `agrimon/answers` | Answer = ToolResult + which capability produced it + evaluation summary + platform-derived visualization stats |
| Evolution engine | `agrimon/evolution` | Generate → Admit → Stage and execute → Evaluate → Commit or Quarantine |
| Capability template | `agrimon/evolution/templates` | Fixed header and footer; slot 1 (`compute`, `interpret`) and slot 2 (literals); the seed |
| Evaluation harness | `agrimon/harness` | 21 checks (18 blocking), probe and variant rasters, EvaluationReport; the commit gate |
| Capability runtime | `agrimon/runtime` | One subprocess per run, configurable timeout, runtime guardrail hook, no API key in its environment; always returns a ToolResult |
| Registry | `agrimon/registry` | Read, snapshot, verify, fingerprint, atomic commit |
| Catalog | `agrimon/catalog` | `assets/catalog.json` loading and source validation |
| Contracts | `agrimon/contracts` | Pydantic models for every JSON record |
| SDK | `agrimon/sdk` | The only application interface capabilities may import |
| Configuration | `agrimon/config` | `agrimon.toml` + `.env`; the only reader of the OpenAI key |
| Observability | `agrimon/observability` | JSON-lines logs with request/attempt/run ids; commit audit log |

## HTTP API

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/api/requests` | `{question, scene_id}` → `{request_id}` |
| GET | `/api/requests/{id}` | State history, Intent, match decision, answer or failure context (polled) |
| GET | `/api/assets`, `/api/assets/{id}/image` | Catalog; scene image for preview |
| GET | `/api/capabilities` | Registry entries, newest generated flagged `is_new` |
| GET | `/api/capabilities/{id}/{version}` | Manifest, evaluation summary, source, creating question |
| GET | `/api/runs/{run_id}` | ToolResult of a match-path run |
| GET | `/api/evaluations`, `/api/evaluations/{ref}` | Harness rows; one full report (`cap:<id>:<v>` or `att:<attempt>`) |
| GET | `/api/health` | Configuration, catalog, registry integrity, startup recovery results |

## Trust zones and write rules

- `agrimon/`, `web/`, `scripts/`: trusted code, changed only by developers.
- `assets/`: trusted data, read-only at run time.
- `capabilities/`: committed capabilities. Only `agrimon.registry` writes here, only through commit.
  Folders are write-once and marked read-only. `registry.json` is the only source of discovery.
- `workspace/`: untrusted. `staging/<attempt>` while a candidate is in flight, `quarantine/<attempt>`
  when it is rejected. Never matched, never listed as a capability.
- `var/`: runtime records (requests, match-path runs, logs, audit).

## The core invariant and how it is enforced

> A failed capability generation, execution, evaluation, or persistence attempt cannot corrupt
> committed capabilities or prevent subsequent requests from being processed.

1. Single writer: only the registry's commit writes committed state.
2. Committed state holds only passing capabilities; everything else lives in `workspace/`.
3. Atomic commit: copy to `capabilities/.pending-<attempt>`, rename to `<id>/<version>`, then replace
   `registry.json` atomically. The replace is the commit point. A failed replace moves the copied
   folder back out to quarantine.
4. Out-of-process execution with a timeout and a guardrail hook; the runtime always returns a ToolResult.
5. Per-request isolation: each request pins a registry snapshot; one evolution at a time.
6. Trusted evaluators: the harness and seed are hand-written; the generator never sees the harness.
7. Startup recovery: stale index temp files are removed, orphan folders and interrupted attempts are
   quarantined, and every indexed capability is verified against its content hash.
8. Provenance from persisted bytes: the SHA-256 of `capability.py` as written to disk flows through
   Context, ToolResult and EvaluationReport to the commit, which re-hashes the copied file; the match
   path re-hashes before every run and refuses a mismatch.

`tests/failure/test_invariant.py` proves each failure path leaves the fingerprint of `capabilities/`
unchanged and the next request succeeding.
