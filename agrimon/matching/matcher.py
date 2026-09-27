"""Four rules, applied in order, over a pinned registry snapshot.

1. Compatibility filter: required bands present in the scene; output is the ToolResult v1 grid.
2. Key match: analysis key, or a declared alias, equals the Intent's key exactly.
3. Selection: highest version; on a tie, the most recent commit.
4. Decision: one capability -> match path; none -> create path.
"""

from __future__ import annotations

from agrimon.contracts import Intent, MatchDecision, Registry, Scene


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def match(intent: Intent, scene: Scene, snapshot: Registry) -> MatchDecision:
    bands = set(scene.band_names)
    compatible = [e for e in snapshot.capabilities if set(e.required_bands) <= bands]
    keyed = [e for e in compatible if intent.analysis_key == e.analysis_key or intent.analysis_key in e.aliases]
    base = {"registry_version": snapshot.registry_version, "candidates_after_filter": [f"{e.id} {e.version}" for e in compatible]}

    if not keyed:
        incompatible = [e for e in snapshot.capabilities if e not in compatible
                        and (intent.analysis_key == e.analysis_key or intent.analysis_key in e.aliases)]
        if incompatible:
            reason = (f"'{intent.analysis_key}' exists but needs bands {incompatible[0].required_bands} "
                      f"that scene {scene.id} does not have")
            return MatchDecision(matched=False, rule="rule 1: compatibility filter", reason=reason, **base)
        return MatchDecision(
            matched=False, rule="rule 4: decision (no key match)",
            reason=f"no committed capability has analysis key '{intent.analysis_key}'; creating one", **base,
        )

    keyed.sort(key=lambda e: (_version(e.version), e.committed_at), reverse=True)
    chosen = keyed[0]
    rule = "rule 3: selection (highest version)" if len(keyed) > 1 else "rule 2: key match"
    return MatchDecision(
        matched=True, capability_id=chosen.id, capability_version=chosen.version, rule=rule,
        reason=f"'{intent.analysis_key}' matches {chosen.id} {chosen.version}", **base,
    )
