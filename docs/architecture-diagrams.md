# AgriMon · Architecture diagrams

These diagrams pair with the three workflows in [workflow-sequence.md](workflow-sequence.md): the system
overview, one diagram per block, and the principles behind it all.

## System overview

![AgriMon system architecture](agrimon-architecture.svg)

## 1. Request path

The orchestrator owns the request. The LLM only turns the question into an intent, a deterministic
selector picks an existing capability or asks for a new one, and committed capabilities run in a
separate process against the imagery assets.

![Request path architecture](architecture-1-request.svg)

## 2. Evolution engine

The generator asks the LLM for analysis code only. The template assembler wraps it in the fixed
header and footer, staging hashes the file on disk, admission rejects unsafe code before it runs, and
only a candidate that passes the harness reaches the atomic registry commit. Everything else goes to
quarantine.

![Evolution engine architecture](architecture-2-evolution.svg)

## 3. Evaluation harness

The harness runs the candidate again on variant and probe images. It groups 21 checks into seven
categories (18 blocking, 3 warnings), and fingerprints committed state before and after. Its report
decides whether the candidate is committed.

![Evaluation harness architecture](architecture-3-harness.svg)

## Principles, strengths and how they evolve

![Architecture principles](architecture-principles.svg)

| Principle | What it means | Strength today | Next evolution |
| --- | --- | --- | --- |
| Open in intent, controlled in execution | Any question is accepted, but code only runs through one fixed contract | Fixed template and SDK: the LLM writes only `compute` and `interpret` | Chained capabilities (composition, Evolution 2) |
| Clear ownership | The platform owns execution, data, validation, visualization, persistence, evaluation and provenance; the capability owns the analysis | Admission rules plus a runtime audit hook, no API key in the subprocess | A real sandbox: containers, no network, memory limits |
| Evidence before trust | Nothing is reused until it has been evaluated | A behavioural harness, independent of the generator, that tests outputs rather than field presence | Trust tiers: provisional to trusted, with human review |
| Evolution only adds | Committed capabilities are immutable, and failures never touch them | Atomic registry commit, read-only files, quarantine that is never matched | Versioning, pinned dependencies and revocation cascades |
| Provenance built in | Every result traces to the exact code that produced it | SHA-256 of the saved file flows through Context, ToolResult and report to the commit | Signed lineage and a tamper-proof audit trail |
| Grounded output | Every number traces to computed evidence, next steps are follow-ups, not prescriptions | Findings cite metrics, zones or classes, checked by the harness | Grounding in cited agronomic knowledge |
| Deterministic reuse | The LLM proposes, rules decide | Pinned registry snapshot and four matching rules: same intent, same capability | Semantic matching with embeddings, still behind a rule gate |

## System dynamics: how the parts relate

![AgriMon system dynamics](system-dynamics.svg)

A systems view of the same parts: what grows, what limits growth, and what keeps it safe.

| Loop | Type | Path | What it means |
| --- | --- | --- | --- |
| R1 Reuse compounds | Reinforcing | Library → match and reuse → user trust → questions asked → unmatched intents → new candidates → harness gate → library | Every committed capability makes later answers faster and reproducible, which builds trust and brings more questions, some of which extend the library further |
| B1 Gaps close | Balancing | Match and reuse → fewer unmatched intents → fewer new candidates | As the library covers more intents, generation slows down on its own; the system spends its effort only on real gaps |
| R2 Failures teach | Reinforcing | New candidates → harness gate → quarantine → reasons fed back → better next candidate | A rejected candidate is not wasted: its admission violations or failed checks become the feedback for the next attempt within the same request (up to three candidates); feedback does not yet carry across requests |
| Library → trust | Direct link | Evidence and provenance stored with every capability | Trust comes from evidence the user can open (the harness report and file hash), not from the model's confidence |

Two parts act as constraints rather than loops. The harness gate caps how fast the library grows,
because only candidates that pass all 18 blocking checks get in. The invariant keeps quarantine out
of the reuse loop, so failures can inform the next candidate but can never be matched or reused.
