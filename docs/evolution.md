# AgriMon · The evolution lifecycle

## Match or create

1. **Intent.** The LLM (`gpt-4o-mini`) turns the question into a structured Intent. It sees the
   committed analysis keys and either chooses one or proposes a new snake_case key. It must not
   propose a multispectral index the scene cannot support; it proposes an RGB proxy instead and
   records that as an assumption.
2. **Match (deterministic, no LLM).** Over a registry snapshot pinned for the request:
   - Rule 1, compatibility: built for the current contract (`toolresult/2`) and required bands present.
   - Rule 2, key match: analysis key or alias equals the Intent's key.
   - Rule 3, selection: highest version; then most recent commit.
   - Rule 4, decision: one → verify its file hash, then execute it; none → create one.

## Create path

For each candidate (up to 1 + `evolution.max_retries`):

| Stage | What happens | On failure |
| --- | --- | --- |
| Generate | The LLM writes `compute` and `interpret` plus the analytical metadata | Quarantine; retry with the error as feedback |
| Admit | Seven `ast` rules on the persisted file (see capability-contract.md) | Quarantine before any execution; retry (a duplicate stops) |
| Stage and execute | Subprocess from `workspace/staging/<attempt>/`, runtime guard on, no API key | Quarantine with the error; retry |
| Evaluate | 21 checks, including a repeat run, band-inversion, mirror and probe runs | Quarantine with the report; retry with the failed checks as feedback |
| Commit | Atomic registry commit; copied file hash re-verified; staging removed | Quarantine (with any orphan); stop |

The staged run's ToolResult becomes the answer, so a capability is never run twice for the user.

## The commit gate

A candidate is committed automatically when all 18 blocking checks pass. The 3 warning checks lower
the score but never block. The harness is independent of the generator and tests behaviour, not
field presence.

| Category | Blocking | Warning |
| --- | --- | --- |
| Contract | Schema conformance; Matrix and grid size; Asset and color map | |
| Execution | Clean run; Reproducibility | |
| Data | Required data available; Input dependence (each required band changes the matrix) | |
| Analytical quality | Data-derived matrix (varied, mirrored input → mirrored matrix); Probe behaviour; Metrics consistency; Zones and classes consistency | |
| Grounding | Numbers traced; Evidence references; No unsupported prescriptions | Methodology reference |
| User value | | Answers the intent (LLM judge); Useful result |
| Governance | Admission passed; Not a duplicate; Provenance chain (file bytes); Committed state untouched | |

No check imposes a universal value range, min/max bounds or classes.

## What gets kept

- Committed: `capabilities/<id>/<version>/` holds `capability.py`, `manifest.json` and `evaluation.json`,
  read-only, listed in `registry.json` and audited in `var/logs/registry_audit.jsonl`.
- Rejected: `workspace/quarantine/<attempt>/` keeps the candidate, `attempt.json` (stage, reason,
  history) and `evaluation.json` if it got that far. Visible on the harness page, never matched.
- Capabilities committed under `toolresult/1` are kept but never matched; `scripts/reset_demo.py`
  rebuilds the registry with the v2 seed.

## Deferred

Evolution 2: composition (capabilities calling capabilities with pinned versions), promotion from
Provisional to Trusted, revocation cascades, qualitative review as a blocking gate.
