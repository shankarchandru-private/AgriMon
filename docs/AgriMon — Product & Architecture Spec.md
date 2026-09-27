# AgriMon — Product & Architecture Spec

Sep 26, 2026 · @Shankar

## Status

Iteration 5 of a living spec. Evolution 1 is scoped as match-or-create on real imagery, with composition deferred to Evolution 2. The long-term concept, capability model and lifecycle below still hold; Evolution 1 implements a subset of them. Formal specification starts from the Evolution 1 scope.

**Iteration 5: Evolution 1 is built.** The formal specification is the Evolution 1 Project Design Specification, and the app runs locally with 104 passing tests. After the first real run, the capability contract moved to v2: the platform owns execution, data access, validation, visualization, persistence, evaluation and provenance, and a generated capability owns only its analysis. ToolResult v2 carries a free-form analytical matrix (no required value ranges or classes), the harness runs 21 behavioural checks (18 blocking), provenance hashes the persisted file bytes, and a runtime guard blocks I/O, network and process launches. The open questions that blocked the formal specification are resolved below.

Conventions: **Agreed** items are in the Decision log. Anything marked *Proposed* is Claude's suggestion pending Shankar's call.

## Evolution 1 scope

Evolution 1 proves the match-or-create loop end to end on real imagery. A question either matches an existing capability, or a new Python capability is generated, executed, evaluated, and persisted only if it passes. Composition is deferred to Evolution 2.

### What Evolution 1 must demonstrate

| # | Requirement | Demonstrated when | Dimension |
| --- | --- | --- | --- |
| 1 | Natural-language analytical requests | A free-text question resolves to a structured intent: metric, area, time window, output form | User value |
| 2 | Capability registry | The registry lists capabilities with their contracts and status; lookup returns a match or "no match" with a reason | Governance |
| 3 | One foundational capability | A hand-written, pre-trusted capability answers a matching question (built: true-color brightness overview, rgb\_overview, since the scenes have no near-infrared band) | Contract |
| 4 | Generation on no match | A question with no match produces a new capability, never a free-form answer | Governance |
| 5 | Execute(Context) contract | Every capability, seeded or generated, has one entry point taking a Context: data asset references, area, time window, parameters | Contract, Execution |
| 6 | Source normalization and validation | Assets are checked and normalized (CRS, bands, nodata, scaling, extent) before any capability sees them | Data |
| 7 | Structured ToolResult contract | Every run returns a ToolResult: status, layer, analysis matrix, metrics with units, optional zones and classes, grounded findings and next steps, provenance, warnings, errors; malformed results are rejected (ToolResult v2) | Contract |
| 8 | Execution on real imagery | Runs use imagery bundled as static assets, not synthetic arrays | Data, Execution |
| 9 | Pydantic evaluation harness in the UI | Each run has a typed evaluation report, opened from the answer in a separate tab | Analytical quality, User value |
| 10 | Persistence and cache | Passing capabilities are saved to the registry and project folder; the UI shows them without a restart | Governance |

### Spec evaluation by dimension

| Dimension | What Evolution 1 needs | Status in Evolution 1 as built |
| --- | --- | --- |
| Contract | Execute(Context) input schema and ToolResult output schema, shared by seeded and generated capabilities | Defined: Context and ToolResult v2 (Pydantic); domain of validity deferred |
| Execution | Generated code runs isolated, read-only, with time and memory limits; a failure returns an error ToolResult and never crashes the app | Subprocess per run with a timeout, an audit-hook guard and no API key; containers deferred to production |
| Data | An asset manifest (scenes, sensors, bands, dates, fields) plus normalization and validation rules | Two USGS EROS true-color scenes in assets/catalog.json, validated at startup |
| Analytical quality | Harness with invariants, reference cases and reproducibility checks | Behavioural checks: repeat, band-inverted, mirrored and probe runs; 18 of 21 checks block commit |
| Grounding | Data grounding: every number in the answer comes from the ToolResult. Domain grounding: index formulas and thresholds come from cited agronomic sources | Harness checks that numbers trace to evidence, findings cite it and nothing is prescribed; a citation is a warning, not a failure |
| User value | Answer, capability card and harness tab; failures explain themselves; a demo question set that exercises both paths | Demo: brightness overview (match path) and "Where does vegetation appear?" (create path) |
| Governance | Evolution 1 states (Staged, Quarantined, Committed); write-once capability files; a persistence approval rule | Auto-commit when every blocking check passes; atomic registry commit with hash re-verification |

### Consequences of deferring composition

- **Every gap creates a new primitive, the riskiest kind.** A new capability can't borrow trust from proven parts, so the harness carries all of it. Reference cases matter most in Evolution 1.
- **Matching becomes the key decision.** The same analysis with different parameters (NDRE instead of NDVI) should reuse a parameterized capability, not generate a near-duplicate.
- **Project-folder persistence must stay append-only.** Committed tool files are write-once; staged and quarantined code lives outside the registry folder; the UI cache is derived from the registry, never the source of truth.

### Deferred to Evolution 2 and later

- Composite capabilities, pinned dependencies, trust propagation
- Promotion from Provisional to Trusted, and revocation cascades
- Qualitative review (LLM or agronomist) as a blocking gate

## Product concept

AgriMon answers open-ended analytical questions about a farm's geospatial imagery. When the capabilities it has can't answer a question, it builds new ones, and it keeps whatever passes evaluation for reuse. Answers are a by-product. The durable asset is a growing, trusted library of capabilities.

Example question: *"Which zones in Field 12 showed persistent stress across the last three drone flights?"* AgriMon returns an answer (a zone map, affected acreage, a short narrative). If it had to build something, it also returns a card describing the new capability and that capability's evaluation harness.

|  | Conventional GIS / ag analytics | LLM chatbot over GIS | AgriMon |
| --- | --- | --- | --- |
| Analytical vocabulary | Fixed, grows with vendor releases | Unbounded but thrown away after each answer | Grows and persists |
| Who chooses the method | User must know the tool | Model, from scratch each time | System, reusing proven capabilities first |
| Reproducibility | High | Low (code regenerated) | High (answers tied to versioned capabilities) |
| Learns from use | No | No | Yes, compounding |
| Trust basis | Vendor QA | None structural | Evaluation evidence stored with each capability |

The differentiator is not code generation. It is the discipline around it: admission, isolation, independent evaluation, versioning and curation.

## Governing principles

Principle 1 governs everything else: **open-ended in analytical intent, controlled in execution.** Constrain the execution environment, not the user's question.

1. **Open intent, controlled execution.** Any question may be asked. Every computation runs inside fixed guardrails.
2. **The model reasons; capabilities compute.** The LLM interprets, plans and writes capabilities. It never produces an answer number directly.
3. **Evolution only adds.** Committed capabilities are immutable. Change means a new version.
4. **Make corruption impossible rather than recovering from it.** A failed capability never touches committed state, so nothing needs restoring.
5. **Trust is earned in stages.** Provisional, then trusted, based on evidence. "It ran" is not evidence.
6. **Evaluation is independent of generation.** The generator never writes or sees the tests it is judged by.
7. **Contracts include a domain of validity.** Each capability states the crop, sensor, resolution and growth stage it is valid for.
8. **Reuse before composing, compose before creating.** New primitives are a last resort.
9. **Every answer can be traced.** Each result links to the capability versions, data and parameters behind it.
10. **The system says when it can't answer reliably.** A clear "can't answer" beats a confident fabrication.
11. **Failures are contained and explained.** The user gets the failure context, and other questions carry on unaffected.

## Capability model (v0.2)

A capability is a reusable analytical function that future natural-language requests can call. It is immutable, composable, and trusted only on evidence.

| Property | Meaning |
| --- | --- |
| Reusable | Any future request whose intent matches can call it |
| Immutable | Never modified once committed; change means a new version |
| Composable | Can call other capabilities and combine them into a new one |
| Pinned dependencies | Depends on exact versions of other capabilities, so its behaviour can't change beneath it |
| Contract | Declares inputs, outputs, units, spatial and temporal assumptions, and domain of validity |
| Evidence-backed | Trusted only after deterministic and qualitative evaluation |
| Transparent | Evaluation results are stored with it and visible in the app |
| Lifecycle state | Staged, Quarantined, Provisional, Trusted, or Revoked |

**Three kinds of plan step** (*Proposed*):

- **Direct match:** run an existing capability. Lowest risk.
- **Composite:** a new capability that orchestrates trusted ones. Only its glue logic is new. The preferred way to evolve from Evolution 2 onward.
- **Primitive:** a new underlying computation. Highest risk. In Evolution 1 this is the only way to evolve, so the evaluation harness carries all the trust.

## Evolution lifecycle

A new capability passes Plan → Generate → Admit → Stage → Execute → Evaluate → Commit or Quarantine. Once committed, it can later be promoted or revoked. Commit is the only step that writes to shared state.

| Stage | Purpose | Key control |
| --- | --- | --- |
| Plan | Decide whether to reuse, compose or create | Composition preferred over new primitives |
| Generate | Write the capability and its contract | Generator cannot see or change evaluation suites |
| Admit | Static checks before anything runs | Contract complete, allowed dependencies only, no forbidden operations, not a duplicate |
| Stage | Place it in an isolated shadow area | Invisible to the planner and to all other requests |
| Execute | Run it in the sandbox | Read-only data, no network, resource limits, other capabilities reachable only through the registry |
| Evaluate | Test its behavior | Deterministic and qualitative checks by an evaluator independent of the generator |
| Commit | Accept it | Atomic, append-only, enters as **Provisional** |
| Quarantine | Reject it | Artifact and failure reason kept for diagnosis; never routed to |
| Promote | Raise trust over time | Successful reuse, user confirmation, agreement with ground truth |
| Revoke | Pull it back after commit | Moves the registry pointer; the revocation spreads to every capability that depends on it |

**Shankar's "Validate" is split in two** (*Proposed*): Admit is the static gate before execution; Evaluate is the behavioral judgment after it.

## Architecture flow (v0.3)

Shankar's flow is the backbone: natural-language interface → Intent layer → Capability registry → either execute an existing capability, or send a new one through the Evolution engine (Validation → Staging → Evaluation → Commit or Quarantine). The diagram adds the proposed refinements listed below it.

&#91;embedded content: AgriMon architecture v0.3 · existing path and evolution path\]

Existing capabilities go straight from the Planner to the sandboxed runtime. Gaps go through the Evolution engine, and only a capability that passes evaluation is committed to the registry, as Provisional.

**Proposed refinements to Shankar's flow**

1. **Separate intent from planning.** The Intent layer outputs a structured intent only. A Planner that reads the registry decides whether to reuse, compose or create. The Intent layer can't know what needs building without seeing the registry.
2. **Decide per step, not per question.** Most questions mix the two cases. One plan can run three trusted capabilities and create one new composite.
3. **Use one shared execution runtime.** Existing capabilities also run in the sandbox. The Evolution engine's execute step uses the same runtime, in a staged namespace.
4. **Make Execute explicit.** It sits between Admit (the static half of Validation) and Evaluate.
5. **Name the data layer.** A read-only catalog of imagery and field data sits under every execution.
6. **Add a results and provenance layer.** It returns the answer, the new capability's card and evaluation harness, and failure context. The staged run's output becomes the provisional answer, so the capability isn't run twice.
7. **Commit is the only registry write.** The Planner reads a registry snapshot, so a commit can't change a question already in progress.
8. **Add a "cannot answer" exit from the Planner** for when data or valid methods are missing (not drawn).

## Safety and containment controls

Six groups of controls keep the system evolving without letting a generated capability compromise existing ones. Safety comes from making corruption impossible. Checkpoints are only a backstop.

| Control group | Controls |
| --- | --- |
| Registry integrity | Append-only and immutable; capabilities identified by their content; only Commit writes; dependencies pinned to exact versions; no cycles; limit on dependency depth |
| Execution containment | Sandboxed; read-only data; no network or side effects; limits on time, memory and processing area; other capabilities called only through the registry interface |
| Request isolation | Each question gets its own staging area; a failure ends only that question's creation path; timeouts and circuit breakers; planner routes only to committed capabilities |
| Independent evaluation | Deterministic: invariants, reference scenes, consistency with trusted dependencies, reproducibility, transformation tests. Qualitative: agronomic plausibility review. Evaluation suites are fixed and hidden from the generator |
| Trust propagation | A capability can't be more trusted than its least-trusted dependency; revocation spreads to dependents |
| Transparency | Evaluation record stored with each capability and visible in the app; every answer links to the versions used |

**Rollback, not restore** (*Proposed*, replacing application checkpoints): the registry is versioned, so revoking a capability moves the active registry pointer back. The application itself is never reverted.

## Failure handling

Every failure is contained to its own question, explained to the user, and followed by normal service. Each message also confirms what was **not** affected.

| Failure point | What the user sees | System effect |
| --- | --- | --- |
| Generate or Admit | "I couldn't build a valid method for this, because …" | None |
| Stage and execute | Which step failed and why, plus a partial answer if existing capabilities cover part of the question | Capability quarantined |
| Evaluate | "I built a method, but it didn't pass these checks," with the harness results | Quarantined; answer withheld or clearly flagged (open question) |
| After commit | Past answers produced by the capability flagged, with an explanation | Capability revoked; revocation spreads to dependents |
| Data or method unavailable | "This can't be answered reliably with the data available," and what would make it answerable | None |

## Decision log

Eleven decisions were agreed on 2026-09-26, newest first. Iteration 5 added the contract v2 decisions: the platform owns execution, data, validation, visualization, persistence, evaluation and provenance; capabilities own only their analysis; no universal value ranges or forced classes; five allowed color maps; provenance from persisted file bytes; a runtime guardrail hook. Implementation-level decisions live in the Evolution 1 design spec.

| Iteration | Decision |
| --- | --- |
| 4 | Evolution 1 is match-or-create only; composition is deferred to Evolution 2 |
| 4 | Ten Evolution 1 requirements adopted (see Evolution 1 scope) |
| 4 | Evolution 1 is evaluated on seven dimensions: Contract, Execution, Data, Analytical quality, Grounding, User value, Governance |
| 3 | Architecture backbone: web app NL interface → Intent layer → Capability registry → execute existing, or Evolution engine → Commit/Quarantine |
| 3 | A living spec doc tracks the concept; formal specification follows architecture agreement |
| 2 | Governing principle: open-ended in analytical intent, controlled in execution |
| 2 | Capabilities are immutable, composable, can depend on other capabilities, and are trusted only after deterministic and qualitative evaluation |
| 2 | Evaluation results are stored and visible in the app |
| 2 | A failed capability must not affect the registry, the application flow, or other questions; the user gets the failure context |
| 2 | Evolution pipeline shape: Generate → Validate → Stage → Execute → Evaluate → Commit or Quarantine |
| 1 | Core loop: intent → existing capability? → execute, or create → validate/evaluate → retain → execute and show results, including the new capability and its evaluation harness |

## Open questions

The first seven are resolved in the Evolution 1 design: 1) a match is an exact analysis-key or alias match after a compatibility filter, and parameters do not create new capabilities; 2) the foundation is a true-color brightness overview; 3) two USGS EROS true-color scenes; 4) auto-commit when the harness passes; 5) a separate process with a timeout and guard; 6) 18 blocking checks and 3 warnings; 7) the refinements were adopted as a deterministic selector, one shared runtime, an asset catalog and an answer composer. The rest remain open for later evolutions.

- [ ] What counts as a match? Does the same analysis with different parameters reuse a capability or generate a new one?
- [ ] Foundational capability: vegetation index + zonal statistics, or something else?
- [ ] Imagery assets: which scenes, sensors, fields and dates ship as static assets?
- [ ] Persistence approval: auto-commit when the harness passes, or the user confirms in the UI?
- [ ] Isolation level for Evolution 1 execution: a separate process, or a container?
- [ ] Harness pass criteria: which checks block a commit, and which only warn?
- [ ] Accept the proposed refinements to the architecture flow (separate Planner, shared runtime, data and results layers)?
- [x] Is v1 limited to composition? Resolved: no. Evolution 1 is match-or-create; composition is deferred.
- [ ] Evolution 2: can provisional capabilities be dependencies of new capabilities? (Recommended: no.)
- [ ] Who promotes a capability to Trusted: the user, a designated agronomist/admin, or automatic after N successful reuses?
- [ ] Can a qualitative evaluation block a commit on its own, or only flag it for a human?
- [ ] When evaluation fails, is the unverified answer withheld or shown with a strong warning?
- [ ] When a capability is revoked, are its past answers flagged, recomputed, or left alone with a note?
- [ ] Primary user persona: grower, agronomist/consultant, or ag data scientist?
- [ ] Scope of sharing: are capabilities per farm, per organization, or global?

## Next phase: formal specification

The formal specification for Evolution 1 is complete and built. These areas remain the frame for Evolution 2 and production:

- **Foundational Python toolset:** the curated primitives and libraries capabilities are built from (raster I/O, vector ops, indices, zonal statistics, time series, masking).
- **Capability contract schema:** inputs, outputs, units, domain of validity, dependencies, lifecycle state.
- **Evaluation harness specification:** invariant catalog, reference scenes, transformation tests, qualitative rubric, pass thresholds.
- **Sandbox and execution specification:** isolation boundaries, resource limits, the data access interface.
- **Registry specification:** versioning, snapshots, commit protocol, revocation cascade.
- **UX specification:** answer view, capability card, harness view, failure messages.
