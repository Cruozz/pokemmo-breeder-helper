from dataclasses import replace
import json

import pytest

from cosmetics import ACTIVE_COSMETICS, CosmeticPolicy, costume_family, normalize_particles, particle_catalog
from chain_planner import ChainState, ChainCandidate, SpeciesProfile, _forced_child
from execution import build_execution_plan
from models import Monster
from planner import make_report_with_candidates


def specimen(identifier, gender, ivs, species="伊布", particles=(), costume=False):
    return Monster(id=identifier, species=species, gender=gender, ivs=ivs,
                   egg_groups=["陆上"], particles=list(particles), is_costume=costume)


def state(identifier, particles=(), gender="F", species="伊布", costume="", mask=1):
    return ChainState(species, gender, ("陆上",), mask, False, "", False,
                      frozenset({identifier}), 0, 0, 0, 0, particles=frozenset(particles),
                      costume_id=costume, costume_lineage=identifier if costume else "")


def plan(inventory, **options):
    return make_report_with_candidates(inventory, "伊布", "", "", "31/31/x/x/x/x", ["陆上"],
                                       allow_ditto=False, cosmetic_options=options)


def walk(root):
    yield root
    if root.action:
        yield from walk(root.action.parent_a)
        yield from walk(root.action.parent_b)


def test_catalog_has_all_2026_particles_and_intrinsic_effects():
    catalog = particle_catalog()
    assert len(catalog) == 42
    assert sum(not p["intrinsic"] for p in catalog) == 40
    assert normalize_particles(["闪光灵棺质子", "Sarcophagus", "白莲花"]) == ["shiny_sarcophagus", "sarcophagus", "lotus_field"]
    assert costume_family("利欧路") == costume_family("路卡利欧") == "pharaoh"
    assert costume_family("小火龙") == costume_family("喷火龙") == "royal"


@pytest.mark.parametrize("extra", [("hitodama",), ("bats",), ("bats", "ghosts")])
def test_all_owned_particles_block_overlap_including_unselected(extra):
    token = ACTIVE_COSMETICS.set(CosmeticPolicy("target", frozenset({"hitodama"})))
    try:
        mother = state("mother", ("hitodama", "bats"))
        father = state("father", extra, gender="M")
        assert _forced_child(mother, father, SpeciesProfile("伊布", "伊布", ("陆上",)), "F") is None
    finally:
        ACTIVE_COSMETICS.reset(token)


def test_disjoint_particles_accumulate_and_inherited_child_is_not_a_new_donor():
    token = ACTIVE_COSMETICS.set(CosmeticPolicy("unique"))
    try:
        mother = state("mother", ("hitodama", "bats"))
        father = state("father", ("ghosts",), gender="M")
        child = _forced_child(mother, father, SpeciesProfile("伊布", "伊布", ("陆上",)), "F")
        assert child.particles == frozenset({"hitodama", "bats", "ghosts"})
        second = _forced_child(child, state("plain", gender="M"), SpeciesProfile("伊布", "伊布", ("陆上",)), "F")
        assert second.particles == child.particles
        assert _forced_child(child, state("duplicate", ("bats",), gender="M"), SpeciesProfile("伊布", "伊布", ("陆上",)), "F") is None
    finally:
        ACTIVE_COSMETICS.reset(token)


def test_ignore_mode_permits_duplicates_but_default_protects_rare_inventory():
    rare = specimen("rare", "F", [31, 1, 1, 1, 1, 1], particles=["bats"])
    assert not CosmeticPolicy().allowed(rare)
    assert CosmeticPolicy("ignore").allowed(rare)
    rare.is_costume = True
    assert not CosmeticPolicy("ignore").allowed(rare)
    unknown = replace(rare, is_costume=False, has_particles=True, particles=[])
    assert not CosmeticPolicy("unique").allowed(unknown)
    assert CosmeticPolicy("ignore").allowed(unknown)


def test_male_costume_converts_with_ditto_and_cannot_leave_family():
    male = state("royal", gender="M", species="小火龙", costume="royal")
    ditto = state("ditto", gender="N", species="百变怪")
    child = _forced_child(male, ditto, SpeciesProfile("小火龙", "小火龙", ("怪兽", "龙")), "F")
    assert child.costume_id == "royal" and child.costume_lineage == "royal"
    assert _forced_child(male, state("ordinary", species="小火龙"), SpeciesProfile("小火龙", "小火龙", ("怪兽", "龙")), "F") is None
    assert _forced_child(replace(male, gender="F"), state("other", gender="M"), SpeciesProfile("伊布", "伊布", ("陆上",)), "F") is None


def test_plain_use_can_spend_repeated_particles_only_in_ignore_mode():
    inventory = [specimen("mom", "F", [31, 1, 1, 1, 1, 1], particles=["bats"]),
                 specimen("dad", "M", [1, 31, 1, 1, 1, 1], particles=["bats"])]
    report, candidates = plan(inventory, particle_mode="ignore")
    assert candidates, report
    assert candidates[0].root.used_ids == frozenset({"mom", "dad"})
    report, candidates = plan(inventory, particle_mode="unique")
    for candidate in candidates:
        assert not {"mom", "dad"}.issubset(candidate.root.used_ids)


def test_zero_v_particle_donor_is_attached_early_and_survives_snapshot_and_execution():
    inventory = [specimen("mom", "F", [31, 1, 1, 1, 1, 1]),
                 specimen("dad", "M", [1, 31, 1, 1, 1, 1]),
                 specimen("particle", "M", [1, 1, 1, 1, 1, 1], species="喵喵", particles=["bats", "ghosts"])]
    report, candidates = plan(inventory, particle_mode="target", target_particles=["bats"])
    assert candidates, report
    root = candidates[0].root
    assert {"bats", "ghosts"}.issubset(root.particles)
    assert "particle" in root.used_ids
    assert all(not (s.action.parent_a.particles & s.action.parent_b.particles) for s in walk(root) if s.action)
    restored = ChainCandidate.from_dict(json.loads(json.dumps(candidates[0].to_dict())))
    execution = build_execution_plan(restored)
    assert execution.steps[-1].child.particles == sorted(root.particles)
    assert execution.planning_options["target_particles"] == ["bats"]


def test_costume_plan_disables_x_iv_protection_only_inside_that_plan():
    mother = specimen("ninja", "F", [31, 1, 1, 31, 1, 1], species="喵喵", costume=True)
    target = [31, 31, None, None, None, None]
    assert mother.has_unrequested_perfect_iv(target)
    father = specimen("dad", "M", [1, 31, 1, 1, 1, 1], species="喵喵")
    report, candidates = make_report_with_candidates([mother, father], "猫老大", "", "", "31/31/x/x/x/x", ["陆上"],
                                                    cosmetic_options={"target_costume": True})
    assert candidates, report
    assert candidates[0].root.costume_id == "ninja"
    assert "ninja" in candidates[0].root.used_ids
    assert candidates[0].cosmetic_options["costume_lineage"] == "ninja"
    assert mother.has_unrequested_perfect_iv(target)


def test_three_separate_zero_v_particle_donors_can_enter_one_route():
    inventory = [specimen("mom", "F", [31, 1, 1, 1, 1, 1]), specimen("dad", "M", [1, 31, 1, 1, 1, 1])]
    selected=["hitodama", "bats", "ghosts"]
    inventory += [specimen("particle-"+name, "M", [1]*6, species="喵喵", particles=[name]) for name in selected]
    report, candidates=plan(inventory,particle_mode="target",target_particles=selected)
    assert candidates,report
    assert set(selected).issubset(candidates[0].root.particles)


def test_zero_v_costume_can_acquire_its_first_v():
    mother=specimen("costume", "F", [1]*6, species="喵喵", costume=True)
    father=specimen("father", "M", [31,1,1,1,1,1], species="喵喵")
    report, candidates=make_report_with_candidates([mother,father],"猫老大","F","","31/x/x/x/x/x",["陆上"],
        cosmetic_options={"target_costume":True})
    assert candidates,report
    assert candidates[0].root.costume_lineage=="costume"
    assert candidates[0].root.mask==1


def test_zero_v_male_costume_can_convert_with_a_braced_one_v_ditto():
    male=specimen("costume", "M", [1]*6, species="喵喵", costume=True)
    ditto=specimen("ditto", "N", [31,1,1,1,1,1], species="百变怪")
    report,candidates=make_report_with_candidates([male,ditto],"猫老大","F","","31/x/x/x/x/x",["陆上"],
        allow_ditto=False,cosmetic_options={"target_costume":True})
    assert candidates,report
    assert candidates[0].root.costume_lineage=="costume"
    assert candidates[0].root.used_ids==frozenset({"costume","ditto"})


def test_unidentified_particle_flag_survives_ignore_mode_breeding():
    mother=specimen("unknown", "F", [31,1,1,1,1,1]);mother.has_particles=True
    father=specimen("father", "M", [1,31,1,1,1,1])
    report,candidates=plan([mother,father],particle_mode="ignore")
    assert candidates,report
    child=build_execution_plan(candidates[0]).steps[-1].child
    assert child.has_particles and not child.particles
    assert not CosmeticPolicy().allowed(child)
