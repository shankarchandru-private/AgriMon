# AgriMon · Evolution 1

A small, complete prototype of a **self-evolving geospatial analytics system**. Ask an open-ended
question about a true-color image. If a trusted capability already answers it, AgriMon runs that
capability. If not, it generates a new Python capability from a fixed template, validates and
evaluates it with a 17-check harness, commits it automatically when every blocking check passes,
and reuses it for later questions. A failed attempt is quarantined and can never damage committed
capabilities or stop the next request.

```
Question → Intent (LLM) → Match (deterministic) → Execute existing | Generate new
         → Validate → Evaluate → Commit | Quarantine → Answer + Visualize
```

## Requirements

- Python 3.11 or 3.12 (Windows, macOS or Linux). Nothing else: all dependencies are pip wheels.
- An OpenAI API key (the app uses `gpt-4o-mini`; a restricted key with a spend limit is fine).

## Install and run

**Windows (PowerShell)**

```powershell
cd AgriMon
copy .env.example .env      # then edit .env and set OPENAI_API_KEY
.\run.ps1                   # first run creates .venv and installs requirements.txt
```

If PowerShell blocks the script, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**macOS / Linux**

```bash
cd AgriMon
cp .env.example .env        # then edit .env and set OPENAI_API_KEY
./run.sh
```

**Manual alternative**

```bash
python -m venv .venv
.venv/Scripts/activate       # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python -m agrimon
```

Open **http://127.0.0.1:8000**.

## Try it

1. Pick a scene in the left panel.
2. Ask **"Give me a brightness overview"**. This matches the seed capability `rgb_overview`: the
   stepper skips Validate / Evaluate / Commit, and the 48×48 grid, findings and next steps appear.
3. Ask **"Where does vegetation appear?"**. No capability matches, so AgriMon generates one
   (typically an Excess Green RGB vegetation proxy), runs it in a staged subprocess, evaluates it,
   commits it and shows the answer. The new capability appears on the left marked **New**; click it
   to see its formula, citation, classes, evaluation and the question that created it.
4. Ask the vegetation question again, or on the other scene: it is now matched, not regenerated.
5. Open **Evaluation harness** (left panel) for all 17 checks per capability and per quarantined attempt.

Model output varies: a generated candidate can fail a check. It is then quarantined, and the
generator retries up to two more times with the failure as feedback. Failed attempts appear on the
harness page with the stage and reason.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

53 tests, no API key needed (the LLM is stubbed with canned responses in `tests/fixtures/llm/`):

- `tests/unit`: contracts, SDK and template, registry, runtime, matcher, admission, boundaries, OpenAI client
- `tests/integration`: the match path end to end through the HTTP API
- `tests/evolution`: the create path, retry after a rejected candidate, reuse, quarantine listing
- `tests/failure`: nine tests of the core invariant (generation, admission, crash, hang, malformed
  result, evaluation, persistence before and at the commit point, concurrent duplicates). Each asserts
  committed state is byte-identical afterwards and the next request succeeds.

## Developer scripts

- `python scripts/reset_demo.py`: clears `capabilities/`, `workspace/` and `var/`, then installs the
  seed through the same admission, harness and commit gate as generated capabilities.
- `python scripts/prepare_assets.py`: rebuilds `assets/catalog.json` from `assets/scenes/` (keeping
  labels and dates you edited) and the harness probe rasters. Add a scene by dropping an RGB
  GeoTIFF/JPEG/PNG into `assets/scenes/` and running it; set `acquisition_date` in the catalog if known.

## Repository layout

| Path | Trust zone | Written by |
| --- | --- | --- |
| `agrimon/` | Trusted code: one package with a subpackage per component | Developers |
| `web/` | Trusted code: three-panel UI and harness page | Developers |
| `assets/` | Trusted data: scenes and `catalog.json` | Developers |
| `capabilities/` | Committed capabilities; `registry.json` is the only source of discovery | Registry commit only (write-once) |
| `workspace/` | Untrusted: `staging/` and `quarantine/`; never discoverable | Evolution engine |
| `var/` | Runtime records: requests, match-path runs, logs, commit audit log | Backend, runtime, observability |
| `docs/` | `applicationOverview.md`, `architecture.md`, `evolution.md`, `capability-contract.md` | Developers |
| `app_spec.json` | What the app is: contracts, template, SDK allowlist, harness checks | Developers |
| `agrimon.toml` | How it runs: models, timeouts, grid size, paths | Developers |

## Known limits (deliberately deferred)

- **Not a security sandbox.** Capability code runs in a separate process with a timeout, which
  protects availability; containers, network blocking and memory limits are production work.
- **Scenes are not georeferenced.** The two bundled USGS EROS JPEGs have no CRS or resolution, so
  zones report cell counts and shares, not square metres.
- **RGB only.** Vegetation answers are RGB proxies (such as Excess Green), never NDVI; multispectral
  indices need a scene with a near-infrared band.
- **Composition** (capabilities calling capabilities) is Evolution 2.

When sharing, zip the folder **without** `.env`, `.venv/`, `workspace/` contents and `var/` contents.
