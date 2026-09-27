"""Developer tool: restores the seed state.

Clears capabilities/, workspace/ and var/, then installs the seed capability (rgb_overview)
through the same admission, staged execution, harness gate and commit protocol that generated
capabilities go through.

Usage:  python scripts/reset_demo.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agrimon.catalog import load_catalog  # noqa: E402
from agrimon.config import Settings, load_settings  # noqa: E402
from agrimon.evolution.admission import admit  # noqa: E402
from agrimon.evolution.candidate import make_candidate  # noqa: E402
from agrimon.evolution.templates.seed_rgb_overview import SEED, SEED_ALIASES, SEED_ANALYSIS_KEY, SEED_ID  # noqa: E402
from agrimon.harness import Harness  # noqa: E402
from agrimon.observability import setup_logging  # noqa: E402
from agrimon.registry import RegistryStore  # noqa: E402
from agrimon.registry.store import make_writable  # noqa: E402
from agrimon.runtime import Runtime, build_context  # noqa: E402


def clear(settings: Settings) -> None:
    for base in (settings.capabilities_dir, settings.workspace_dir, settings.var_dir):
        if base.exists():
            make_writable(base)
            for child in base.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    settings.capabilities_dir.mkdir(parents=True, exist_ok=True)
    settings.ensure_runtime_dirs()


def install_seed(settings: Settings) -> None:
    registry, runtime = RegistryStore(settings), Runtime(settings)
    harness = Harness(settings, runtime)
    scene = next(s for s in load_catalog(settings).scenes if {"red", "green", "blue"} <= set(s.band_names))
    source, manifest = make_candidate(SEED, SEED_ID, SEED_ANALYSIS_KEY, "seed", aliases=SEED_ALIASES)
    stage = settings.staging_dir / "seed"
    cand = stage / "candidate"
    cand.mkdir(parents=True, exist_ok=True)
    (cand / "capability.py").write_text(source, encoding="utf-8")
    snapshot = registry.snapshot()
    violations = admit(source, manifest, scene, snapshot, settings.evolution.max_source_bytes)
    if violations:
        raise SystemExit("seed failed admission: " + "; ".join(violations))
    from agrimon.evolution.candidate import content_hash

    ctx = build_context(settings, scene, manifest, content_hash(source), "staged", "seed", "seed-run", stage / "run")
    run = runtime.run(cand / "capability.py", ctx, stage / "run")
    report = harness.evaluate(
        capability_file=cand / "capability.py", manifest=manifest, first_run=run, context=ctx, scene=scene,
        snapshot=snapshot, admission_violations=violations, intent=None, work_dir=stage / "harness",
    )
    for c in report.checks:
        print(f"  [{'PASS' if c.passed else ('FAIL' if c.blocking else 'WARN')}] {c.category:18} {c.name}: {c.observed}")
    if report.verdict != "pass":
        raise SystemExit("seed failed the harness gate")
    entry = registry.commit(cand, manifest, report, "seed")
    shutil.rmtree(stage)
    print(f"seed committed: {entry.id} {entry.version} (score {report.overall_score}, "
          f"{report.blocking_passed}/{report.blocking_total} blocking checks)")


def main() -> None:
    settings = load_settings(ROOT, read_env=False)
    clear(settings)
    setup_logging(settings.logs_dir)
    install_seed(settings)


if __name__ == "__main__":
    main()
