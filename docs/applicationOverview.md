# AgriMon · Application overview

AgriMon answers open-ended analytical questions about true-color imagery. Its analytical vocabulary
grows from the questions people ask: when no existing capability answers a question, it builds one,
proves it with an evaluation harness, and keeps it for reuse.

## What a user sees

**Left panel.** The data assets (scenes, with bands, size, date and georeferencing status), the
capability registry (newest generated capability marked *New*, seed capabilities marked *Seed*), and a
link to the evaluation harness page.

**Middle panel.** The question box, a pipeline stepper (Question, Intent, Match, Execute/Generate,
Validate, Evaluate, Commit/Quarantine, Answer) driven by request-status polling, and the result: a
48×48 grid drawn from the ToolResult with its color map, the largest high and low zones outlined, and
per-cell values on hover. A toggle shows the source image for comparison.

**Right panel.** *Analysis*: whether an existing or new capability answered, the summary, findings
with their evidence references, next steps (follow-up analysis or human inspection only), the
evaluation verdict with category scores, metrics, the resolved intent and match rule, and the raw
ToolResult JSON. *Capability*: the clicked capability's description, analysis key, formula, citation,
bands, classes, evaluation, the question that created it, and its read-only source.

**Harness page.** One row per committed capability and quarantined attempt with blocking/warning
counts and seven category scores; select a row to see all 17 checks with observed and expected values.

## Principles

- Open in analytical intent, controlled in execution.
- The model reasons; capabilities compute. No model writes answer text: summaries and findings are
  rendered from computed metrics.
- Analytical output must be grounded in computed evidence. Next steps are framed as follow-up
  analysis or human inspection, never unsupported prescriptions.
- Evolution only adds. Committed capabilities are write-once.
- A failed attempt cannot corrupt committed capabilities or stop later requests.

## Scope of Evolution 1

Match-or-create on real imagery, with one seed capability (true-color brightness overview) and
automatic commit through the harness gate. Composition, promotion and revocation are Evolution 2;
security sandboxing, dynamic ingestion and map display are production concerns.
