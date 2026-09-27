"""P3: the four deterministic matching rules."""

from agrimon.contracts import Intent, Registry, RegistryEntry, Scene
from agrimon.matching import match


def _entry(id_, key, version="1.0.0", bands=("red", "green", "blue"), aliases=(), at="2026-01-01T00:00:00+00:00"):
    return RegistryEntry(id=id_, version=version, analysis_key=key, aliases=list(aliases), name=id_, description="d",
                         required_bands=list(bands), origin="generated", committed_at=at, content_hash="h",
                         path=f"{id_}/{version}", verdict="pass", overall_score=1.0)


SCENE = Scene(id="s", label="S", file="f", sensor="x", source="y", width=10, height=10, dtype="uint8",
              bands=[{"name": n, "index": i + 1, "scale": 1 / 255} for i, n in enumerate(["red", "green", "blue"])])


def _intent(key):
    return Intent(analysis_key=key, is_new_key=False, description="ddd", required_bands=["red"], question="q", scene_id="s")


def test_rule2_key_and_alias_match():
    reg = Registry(registry_version=3, capabilities=[_entry("a", "brightness_overview", aliases=["tco"])])
    assert match(_intent("brightness_overview"), SCENE, reg).rule == "rule 2: key match"
    assert match(_intent("tco"), SCENE, reg).matched


def test_rule1_filters_incompatible_bands():
    reg = Registry(capabilities=[_entry("n", "ndvi_index", bands=("red", "nir"))])
    d = match(_intent("ndvi_index"), SCENE, reg)
    assert not d.matched and d.rule == "rule 1: compatibility filter"


def test_rule3_highest_version_wins():
    reg = Registry(capabilities=[_entry("a", "k_one", "1.0.0"), _entry("a", "k_one", "1.2.0"), _entry("a", "k_one", "1.10.0")])
    d = match(_intent("k_one"), SCENE, reg)
    assert d.capability_version == "1.10.0" and d.rule.startswith("rule 3")


def test_rule4_no_match_goes_to_create():
    d = match(_intent("vegetation_proxy_rgb"), SCENE, Registry(capabilities=[_entry("a", "brightness_overview")]))
    assert not d.matched and d.rule.startswith("rule 4")
