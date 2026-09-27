# Building AgriMon: a spec-driven workflow

AgriMon is a self-evolving geospatial analytics app for precision agriculture. A user asks an
open-ended question about imagery. The app either reuses a trusted capability or writes a new one,
evaluates it, and keeps it only if it passes. This document summarizes how it was built with Claude
in one working session, spec first and code last.

**Outcome:** a working local prototype with 104 automated tests, a 21-check evaluation harness, and 8
capabilities generated and committed by the app itself from 13 successful user questions.

---

## The workflow at a glance

| Phase | What happened | Artifact |
| --- | --- | --- |
| 1. Concept | Defined the product, its differentiation and principles, with no code | Product & Architecture Spec |
| 2. Architecture | Walked the flow and the capability model; agreed the safety principle | Architecture flow, capability lifecycle |
| 3. Scope | Cut Evolution 1 to "match or create"; deferred composition | 10 requirements, 7 evaluation dimensions |
| 4. Design spec | Defined components, boundaries and the core invariant | Evolution 1 Project Design Specification |
| 5. Stack and repo | Chose the simplest technology; designed folders by trust zone | Tech stack, repository design |
| 6. Build plan | Ordered the build along the request flow, each step with an exit criterion | Build plan (F1–F5, P1–P9, H1–H2) |
| 7. Build | Implemented phase by phase, validating each before moving on | Code, tests, zip |
| 8. Real run and diagnosis | Ran with a live LLM; every candidate failed; traced root causes | Diagnosis of 15 failed attempts |
| 9. Contract revision | Rewrote the capability contract (v2) without changing the architecture | ToolResult v2, harness v2 |
| 10. Re-test and document | User re-tested; docs, diagrams and specs updated to match | 8 new capabilities, diagrams, prompt examples |

---

## 1. Concept before code

The first request was explicit: *"Do not implement anything yet."* The session produced a living
Product & Architecture Spec covering the core product, how it differs from GIS tools and LLM
chatbots, governing principles, capability model, open questions and a decision log.

The key idea that shaped everything after:

> **Open-ended in analytical intent, controlled in execution.**

The differentiator is not code generation. It is the discipline around it: admission, isolation,
independent evaluation, versioning and curation.

## 2. Architecture and capability model

The user supplied the backbone flow; Claude proposed refinements, each marked *Proposed* until agreed:

```
Question → Intent → Capability registry → Execute existing
                                        → or Evolution engine: Generate → Validate → Stage → Evaluate → Commit or Quarantine
```

Agreed properties of a capability: reusable, immutable once committed, versioned, trusted only on
evidence, with its evaluation visible in the app. The safety rule became the **core invariant**:

> A failed generation, execution, evaluation or persistence attempt cannot corrupt committed
> capabilities or prevent later requests from being processed.

## 3. Scoping Evolution 1

Composition (capabilities calling capabilities) was deferred to Evolution 2. Evolution 1 became
**match or create** on real imagery, judged on seven dimensions: Contract, Execution, Data,
Analytical quality, Grounding, User value and Governance.

## 4. The Project Design Specification

Before any technology was named, the design spec defined ten components (frontend, backend,
runtime, registry, evolution engine, harness, imagery, persistence, configuration, observability),
each with what it owns, consumes, produces and talks to. Seven boundary rules enforce the invariant,
among them: a single writer for committed state, atomic commit, out-of-process execution, and
evaluators the generator never sees.

## 5. Technology and repository, chosen for simplicity

The brief: a small, fast, zippable prototype with no databases, containers, orchestration or
frontend frameworks. Each choice was justified against a requirement.

| Layer | Choice |
| --- | --- |
| Backend | Python, FastAPI, Pydantic v2 |
| Frontend | Vanilla HTML, CSS and JavaScript; three panels; polling |
| Imagery | rasterio and NumPy on two USGS EROS true-color scenes |
| LLM | OpenAI gpt-4o-mini for intent and generation; matching is deterministic |
| Execution | One subprocess per run with a configurable timeout |
| Persistence | JSON files; `registry.json` is the only discovery index |

The repository was split into trust zones: trusted code, trusted data, committed capabilities
(written only by the registry commit), untrusted workspace (staging and quarantine) and runtime
records.

## 6. A build plan ordered by the request flow

The user asked for foundations first, then each stage in the order a request passes through it,
with an exit criterion validated before moving on:

- **Foundations (F1–F5):** contracts, asset catalog, SDK and template, registry and seed, runtime.
- **Pipeline (P1–P9):** question, intent, match, execute and answer, generate, validate, evaluate,
  commit or quarantine, answer and visualize the new capability.
- **Hardening (H1–H2):** failure test suite, packaging.

The first end-to-end result (the seed brightness capability answering a question) arrived at P4,
before any generation code existed.

## 7. Build

Each phase was implemented and checked against its exit criterion. Bugs found along the way were
fixed at the source, for example a leftover temp file on a failed index write, which led to
try/finally cleanup plus a startup sweep. The first build shipped as a zip and was delivered to the
user's project folder.

## 8. First real run: every candidate failed

With a live LLM, the match path worked but all 15 generated candidates were quarantined. The user
shared the evaluation results, and each failure was traced:

| Cause | Attempts | Root cause |
| --- | --- | --- |
| Missing class `min` | 10 | The contract forced every analysis into fixed classes with value ranges |
| Provenance mismatch | 4 | On Windows, the file was saved with CRLF line endings but hashed from the in-memory string |
| Value range | 1 | A valid negative value broke an invented 0–1 range |
| Numbers traced | 1 | A class label "(class 3)" was read as an ungrounded number |

The lesson: **the contract let visualization needs dictate the analysis**, and one real bug
(hashing) was hiding behind it.

## 9. Revising the contract, not the architecture

The user set new product goals: the platform owns execution, data access, validation,
visualization, persistence, evaluation and provenance; the capability owns only its analysis. The
architecture and lifecycle stayed the same; the contract and its checks changed.

| Area | v1 | v2 |
| --- | --- | --- |
| Capability code | Fill three slots of a rigid template | Write `compute` and `interpret` only |
| Output | Fixed classes and value ranges | Free-form analytical matrix; zones optional; classes only when asked |
| Visualization | Declared by the capability | Derived by the platform from the matrix |
| Provenance | Hash of an in-memory string | SHA-256 of the saved file bytes, carried to the commit (with a regression test) |
| Guardrails | Static checks | Static checks plus a runtime guard that blocks file writes, network and processes |
| Harness | 17 checks, mostly structural | 21 behavioural checks (18 blocking), e.g. inverting a band must change the result |

Tests grew from 53 to 104, covering each behaviour the user listed, including a failed evolution
leaving committed state unchanged.

## 10. Re-test, documentation and results

After the update the user re-tested with a live LLM. Thirteen questions succeeded, and the app
generated and committed 8 new capabilities, including vegetation proxy, vegetation hotspots, water
body variation, barren land and farm-land classification, and reused them across both scenes.

The session closed by bringing every document up to date with the working system:

- Both specs revised for contract v2 and the resolved open questions.
- Architecture diagrams: system overview, one per block, principles, folders and system dynamics.
- Three landscape sequence diagrams: master flow, evolution engine, evaluation harness.
- A prompt examples page built from the successful requests, with honest caveats.

Reviewing those real results also surfaced the next improvements: a check that each finding's
number matches its claim, and a check for unfilled placeholders in generated text.

---

## What made the workflow work

1. **Spec before code.** Concept, architecture, scope, design, stack, repository and build plan
   were each agreed before the next began, so implementation had few open questions.
2. **Decisions were recorded, not implied.** Proposals were marked *Proposed* until the user agreed,
   and the decision log kept the reasoning.
3. **One invariant guided every design choice.** The core invariant was stated early and every
   boundary, test and commit step traces back to it.
4. **Exit criteria per step.** The build followed the request flow, and each step had to work end
   to end before the next started.
5. **Real data exposed what tests could not.** Stubbed tests passed; the first live run failed. The
   failures were diagnosed from evidence, and the fix changed the contract, not the architecture.
6. **Documents kept pace with the code.** Specs, diagrams and examples were updated to describe the
   system as built, including its known gaps.
