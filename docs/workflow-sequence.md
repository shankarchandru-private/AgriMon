# AgriMon · Workflows

Three sequence diagrams, from the outside in:

1. [Master workflow](#1-master-workflow): question → capability selection (existing or new) → answer and harness updates.
2. [Evolution engine](#2-evolution-engine): how a new capability is generated, validated and committed or quarantined.
3. [Evaluation harness](#3-evaluation-harness): how one candidate is evaluated against 21 checks.

Invariant across all three: a failure at any step leaves committed capabilities byte-identical and
does not stop the next request.

## 1. Master workflow

![Master workflow](workflow-1-master.png)

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Web UI
    participant Orch as API + orchestrator
    participant Intent as Intent resolver (LLM)
    participant Sel as Capability selector (matcher)
    participant Reg as Registry
    participant Run as Runtime
    participant Eng as Evolution engine

    User->>UI: Ask a question about the selected scene
    UI->>Orch: POST /api/requests {question, scene_id}
    Orch-->>UI: request_id (UI polls GET /api/requests/{id})
    Orch->>Intent: Resolve question
    Intent-->>Orch: Structured intent + analysis key
    Orch->>Reg: Pin registry snapshot for this request
    Orch->>Sel: Select capability (intent, snapshot, scene)
    Note over Sel: Deterministic: compatible, key or alias match, highest version

    alt Existing capability
        Sel-->>Orch: Capability id + version
        Orch->>Reg: Integrity check (file hash)
        Orch->>Run: Execute capability
        Run-->>Orch: ToolResult
    else New capability needed
        Sel-->>Orch: No match
        Orch->>Eng: Create capability (intent, scene)
        Note over Eng: See workflow 2 (generate, validate, evaluate)
        Eng->>Reg: Commit only if every blocking check passed
        Eng-->>Orch: ToolResult + evaluation report, or failure context
    end

    Note over Orch: Compose answer + visualization stats
    Orch-->>UI: Answer on next poll
    UI-->>User: Grid, summary, findings, next steps, evaluation verdict

    opt A new capability was committed
        UI->>Orch: GET /api/capabilities
        Orch-->>UI: Registry with new capability flagged
        UI-->>User: Capability list shows it marked New
    end
    User->>UI: Open evaluation harness page
    UI->>Orch: GET /api/evaluations
    Orch-->>UI: Committed capabilities + quarantined attempts with check results
    UI-->>User: 21 checks per capability or attempt
```

## 2. Evolution engine

![Evolution engine workflow](workflow-2-evolution.png)

```mermaid
sequenceDiagram
    autonumber
    participant Orch as Orchestrator
    participant Eng as Evolution engine
    participant Gen as Generator
    participant LLM as OpenAI gpt-4o-mini
    participant Stg as Staging (workspace)
    participant Adm as Admission
    participant Run as Runtime (subprocess)
    participant Har as Evaluation harness
    participant Reg as Registry
    participant Q as Quarantine

    Orch->>Eng: evolve(intent, scene, registry snapshot)
    loop Candidate 1 to 1 + max_retries (default 3)
        Eng->>Gen: generate(intent, scene, feedback from last attempt)
        Gen->>LLM: Contract, asset bands and size, feedback
        LLM-->>Gen: compute + interpret source, analytical metadata (JSON)
        Gen-->>Eng: GenerationOutput (Pydantic-validated)
        Eng->>Stg: Assemble fixed template + manifest, write capability.py
        Stg-->>Eng: Content hash = SHA-256 of persisted file bytes
        Eng->>Adm: admit(persisted source, manifest, scene, snapshot)
        alt Admission violations
            Adm-->>Eng: Violations (e.g. import, I/O, forbidden call)
            Eng->>Q: Quarantine attempt (stage admitting)
            Note over Eng: Duplicate (rule 7) stops, otherwise retry with feedback
        else Admitted
            Eng->>Run: Staged run: execute(Context with content hash)
            Run-->>Eng: ToolResult
            alt Run failed (exception, timeout, guardrail violation)
                Eng->>Q: Quarantine attempt (stage executing)
            else Run succeeded
                Eng->>Har: evaluate(candidate, first run, context, snapshot)
                Note over Har: See workflow 3
                Har-->>Eng: EvaluationReport (verdict + 21 checks)
                alt All 18 blocking checks pass
                    Eng->>Reg: commit(candidate, manifest, report)
                    Note over Reg: Copy to .pending, rename, read-only, re-verify hash, atomically replace registry.json
                    Reg-->>Eng: Registry entry (committed, discoverable)
                    Eng->>Stg: Remove staging folder
                else A blocking check fails
                    Eng->>Q: Quarantine with report
                    Note over Eng: Retry with the failed checks as feedback
                end
            end
        end
    end
    Eng-->>Orch: Committed entry + staged ToolResult + report, or quarantined attempts
```

## 3. Evaluation harness

![Evaluation harness workflow](workflow-3-harness.png)

```mermaid
sequenceDiagram
    autonumber
    participant Caller as Evolution engine (or seed install)
    participant Har as Evaluation harness
    participant Var as Probes and variants
    participant Run as Runtime (subprocess)
    participant Judge as LLM judge
    participant Reg as Committed state

    Caller->>Har: evaluate(capability file, manifest, first run, context, scene, snapshot)
    Note over Har: Hash capability file bytes (start)
    Har->>Reg: Fingerprint committed state (start)
    Note over Har: Contract: schema, matrix and grid size, asset and color map
    Note over Har: Execution: clean first run
    Har->>Run: Repeat run with the same Context
    Run-->>Har: ToolResult (must be identical)
    Note over Har: Data: every declared band exists in the asset
    loop Each required band
        Har->>Var: Write scene with this band inverted
        Har->>Run: Run on the variant
        Run-->>Har: ToolResult (matrix must change)
    end
    Har->>Var: Write mirrored scene
    Har->>Run: Run on the mirrored scene
    Run-->>Har: ToolResult (mirrored matrix, r at least 0.9)
    Har->>Var: Uniform and masked-quadrant probe scenes
    Har->>Run: Run on each probe
    Run-->>Har: ToolResults (uniform matrix, nulls only where masked)
    Note over Har: Recompute metrics, zones and classes from the matrix
    Note over Har: Grounding: numbers traced, evidence cited, no prescriptions, methodology (warning)
    Har->>Judge: Does the result answer the question?
    Judge-->>Har: Score and reason (warning only, errors never block)
    Note over Har: Useful result (warning), admission passed, not a duplicate
    Note over Har: Re-hash file: file = Context = ToolResult provenance
    Har->>Reg: Fingerprint committed state (end, must equal start)
    Note over Har: Verdict pass only if all 18 blocking checks pass, score = mean of category scores
    Har-->>Caller: EvaluationReport (21 checks, 18 blocking, 3 warnings)
    Note over Caller: Saved as evaluation.json, gates commit or quarantine, shown on the harness page
```
