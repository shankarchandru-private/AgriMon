# AgriMon · The evolution lifecycle

## Match or create

1. **Intent.** The LLM (`gpt-4o-mini`) turns the question into a structured Intent. It sees the
   committed analysis keys and either chooses one or proposes a new snake_case key. It must not
   propose a multispectral index the scene cannot support; it proposes an RGB proxy instead and
   records that as an assumption.
2. **Match (deterministic, no LLM).** Over a registry snapshot pinned for the request:
   - Rule 1, compatibility: required bands present in the scene.
   - Rule 2, key match: analysis key or alias equals the Intent's key.
   - Rule 3, selection: highest version; then most recent commit.
   - Rule 4, decision: one → execute it; none → create one.

## Create path

For each candidate (up to 1 + `evolution.max_retries`):

| Stage | What happens | On failure |
| --- | --- | --- |
| Generate | The LLM fills the three template slots and manifest fields | Quarantine; retry with the error as feedback |
| Admit | Seven `ast` rules: fixed sections unchanged, slot shapes, no imports, no forbidden calls or names, literal constants only, manifest consistent with code and scene, not a duplicate | Quarantine before any execution; retry (a duplicate stops) |
| Stage and execute | Candidate runs in a subprocess from `workspace/staging/<attempt>/` against the request's scene | Quarantine with the error; retry |
| Evaluate | 17 checks, including a second run and two probe runs | Quarantine with the report; retry with the failed checks as feedback |
| Commit | Atomic registry commit; staging folder removed | Quarantine (with any orphan); stop |

The staged run's ToolResult becomes the answer, so a capability is never run twice for the user.

## The commit gate

A candidate is committed automatically, with no user approval, when all 13 blocking checks pass.
The 4 warning checks lower the score and appear in the report but never block.

| Category | Blocking | Warning |
| --- | --- | --- |
| Contract | Schema conformance; Completeness | |
| Execution | Clean run; Reproducibility | |
| Data | Input validity; Value ranges | |
| Analytical quality | Probe behaviour | Class spread |
| Grounding | Numbers traced; Evidence references; No unsupported prescriptions | Formula citation |
| User value | | Answers the intent (LLM judge); Readable summary |
| Governance | Admission passed; Not a duplicate; Provenance complete | |

## What gets kept

- Committed: `capabilities/<id>/<version>/` holds `capability.py`, `manifest.json` and `evaluation.json`,
  read-only, listed in `registry.json` and audited in `var/logs/registry_audit.jsonl`.
- Rejected: `workspace/quarantine/<attempt>/` keeps the candidate, `attempt.json` (stage, reason,
  history) and `evaluation.json` if it got that far. Visible on the harness page, never matched.

## Deferred

Evolution 2: composition (capabilities calling capabilities with pinned versions), promotion from
Provisional to Trusted, revocation cascades, qualitative review as a blocking gate.
