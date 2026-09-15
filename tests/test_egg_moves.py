from __future__ import annotations

import unittest

from chain_planner import (
    ChainCandidate, ChainState, SpeciesProfile, _forced_child, _virtual_materials,
    find_chain_candidates,
)
from execution import build_execution_plan
from models import Monster
from planner import make_report_with_candidates
from reference_data import get_reference_database
from species_data import get_species_database


def monster(identifier, species, gender, moves=(), ivs=None, **kwargs):
    return Monster(
        id=identifier, species=species, gender=gender, moves=list(moves),
        ivs=[31, 1, 1, 1, 1, 1] if ivs is None else ivs, **kwargs,
    )


def state(identifier, species, gender, moves=(), *, virtual=False, hidden=False):
    record = get_species_database().get(species)
    parent = get_species_database().breeding_parent(record)
    leaf = monster(identifier, species, gender, moves, has_hidden_ability=hidden)
    return ChainState(
        species=species, gender=gender, egg_groups=tuple(parent.egg_groups),
        mask=1, has_nature=False, nature="", is_alpha=False,
        used_ids=frozenset({identifier}), generation=0, breeds=0, braces=0, everstones=0,
        purchases=int(virtual), is_virtual=virtual, leaf=leaf,
        has_hidden_ability=hidden, inherited_moves=frozenset(moves),
    )


def profile(species):
    db = get_species_database()
    record = db.get(species)
    parent = db.breeding_parent(record)
    return SpeciesProfile(species, species, parent.egg_groups, allowed_genders=record.allowed_genders)


class EggMoveReferenceTests(unittest.TestCase):
    def setUp(self):
        self.database = get_reference_database()

    def test_evolved_species_uses_hatch_learnset(self):
        self.assertIn("飞膝踢", self.database.egg_moves_for_species("路卡利欧"))
        self.assertTrue(self.database.is_egg_move("妙蛙花", "花瓣舞"))

    def test_exact_aliases_are_normalized_and_deduplicated(self):
        self.assertEqual(
            self.database.normalize_egg_move_selection("伊布", [" Wish ", "祈愿", "Wish"]),
            ("祈愿",),
        )

    def test_move_limit_and_unsupported_moves_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "最多保留 4"):
            self.database.normalize_egg_move_selection("伊布", ["a", "b", "c", "d", "e"])
        with self.assertRaisesRegex(ValueError, "不支持"):
            self.database.normalize_egg_move_selection("伊布", ["飞膝踢"])
        with self.assertRaisesRegex(ValueError, "名称列表"):
            self.database.normalize_egg_move_selection("伊布", "Wish")
        self.assertEqual(self.database.canonical_move("完全不存在的技能", fuzzy=False), "完全不存在的技能")

    def test_route_preserves_all_hops_and_source_annotations(self):
        route = self.database.egg_move_routes("妙蛙种子", "污泥攻击")[0]
        self.assertEqual([step.species for step in route.steps], ["水跃鱼", "无壳海兔", "溶食兽"])
        self.assertEqual(route.steps[0].annotations, ("蛋",))
        self.assertEqual(route.steps[-1].annotations, ("Lv.10",))
        self.assertEqual(route.direct_donor.species, "水跃鱼")

    def test_all_bundled_workbook_routes_parse_without_losing_rows(self):
        raw_count = parsed_count = 0
        for species, moves in self.database.egg_moves_by_species.items():
            for move, routes in moves.items():
                raw_count += len(routes)
                parsed_count += len(self.database.egg_move_routes(species, move))
        self.assertEqual(raw_count, 11145)
        self.assertEqual(parsed_count, raw_count)

    def test_baby_annotations_are_not_part_of_species_name(self):
        routes = self.database.egg_move_routes("伊布", "祈愿")
        baby = next(route for route in routes if route.direct_donor.species == "皮丘")
        self.assertEqual(baby.direct_donor.annotations, ("幼年", "蛋"))


class EggMoveInheritanceTests(unittest.TestCase):
    def test_unlearnable_move_does_not_cross_a_compatible_egg_group(self):
        child = _forced_child(state("f", "伊布", "F"), state("m", "图图犬", "M", ["龙之怒"]), profile("伊布"), "F")
        self.assertEqual(child.inherited_moves, frozenset())
        self.assertEqual(child.introduced_moves, frozenset())

    def test_sketch_is_not_automatically_inherited_by_smeargle(self):
        child = _forced_child(state("f", "图图犬", "F", ["祈愿"]), state("m", "伊布", "M"), profile("图图犬"), "M")
        self.assertEqual(child.inherited_moves, frozenset())

    def test_valid_moves_from_both_parents_survive(self):
        child = _forced_child(state("f", "伊布", "F", ["祈愿"]), state("m", "图图犬", "M", ["哈欠"]), profile("伊布"), "F")
        self.assertEqual(child.inherited_moves, frozenset({"祈愿", "哈欠"}))
        self.assertEqual(child.introduced_moves, frozenset({"哈欠"}))

    def test_ditto_cannot_inject_a_move(self):
        ditto = state("d", "百变怪", "N", ["祈愿"])
        child = _forced_child(state("f", "伊布", "F"), ditto, profile("伊布"), "F")
        self.assertFalse(child.inherited_moves)

    def test_market_source_keeps_the_actual_evolved_form(self):
        leaves = _virtual_materials(
            profile("利欧路"), [31, None, None, None, None, None], False, "", False,
            target_moves=frozenset({"飞膝踢"}), egg_move_donors={"飞膝踢": ("火焰鸡",)},
        )
        self.assertTrue(any(leaf.leaf.species == "火焰鸡" and "飞膝踢" in leaf.inherited_moves for leaf in leaves))
        self.assertFalse(any(leaf.leaf.species == "火稚鸡" for leaf in leaves))

    def test_purchase_specs_do_not_merge_plain_and_skill_materials(self):
        plain = state("buy:1", "伊布", "F", virtual=True)
        carrier = state("buy:2", "伊布", "M", ["祈愿"], virtual=True, hidden=True)
        child = _forced_child(plain, carrier, profile("伊布"), "F")
        candidate = ChainCandidate(child, [31, None, None, None, None, None], "", "F", target_moves=("祈愿",))
        requirements = candidate.purchase_requirements()
        self.assertEqual(len(requirements), 2)
        self.assertIn("必须已携带技能：祈愿", requirements[1])
        self.assertIn("必须保留梦特潜力", requirements[1])
        self.assertNotIn("必须已携带", requirements[0])


class EggMovePlanningTests(unittest.TestCase):
    def plan(self, inventory, moves, species="伊布", ivs="31/x/x/x/x/x", **kwargs):
        report, candidates = make_report_with_candidates(
            inventory, species, "F", "", ivs, [], allow_ditto=False,
            target_moves=moves, **kwargs,
        )
        self.assertTrue(candidates, report)
        return report, candidates[0]

    def test_same_iv_skill_import_is_a_real_step(self):
        report, candidate = self.plan([
            monster("f", "伊布", "F"), monster("m", "图图犬", "M", ["祈愿"]),
        ], ["祈愿"])
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.breeds, 1)
        self.assertEqual(candidate.root.braces, 0)
        self.assertEqual(candidate.root.used_ids, frozenset({"f", "m"}))
        self.assertIn("库存已携带 图图犬", report)
        self.assertNotIn("大葱鸭", " ".join(candidate.egg_move_sources()))

    def test_multiple_skills_can_be_imported_at_the_same_iv_tier(self):
        _, candidate = self.plan([
            monster("f", "伊布", "F"), monster("m", "图图犬", "M", ["祈愿"]),
            monster("m2", "土龙弟弟", "M", ["哈欠"]),
        ], ["祈愿", "哈欠"])
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.breeds, 2)
        self.assertEqual(candidate.root.inherited_moves, frozenset({"祈愿", "哈欠"}))
        self.assertEqual(len(candidate.root.used_ids), 3)
        plan = build_execution_plan(candidate)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(set(plan.steps[-1].child.moves), {"祈愿", "哈欠"})

    def test_zero_iv_target_can_still_import_a_skill(self):
        _, candidate = self.plan([
            monster("f", "伊布", "F", ivs=[1] * 6),
            monster("m", "图图犬", "M", ["祈愿"], ivs=[1] * 6),
        ], ["祈愿"], ivs="x/x/x/x/x/x")
        self.assertEqual(candidate.root.breeds, 1)
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.mask, 0)

    def test_cross_group_chain_uses_zero_iv_intermediate_mothers(self):
        _, candidate = self.plan([
            monster("bulba", "妙蛙种子", "F"),
            monster("mudkip", "水跃鱼", "F", ivs=[1] * 6),
            monster("shellos", "无壳海兔", "F", ivs=[1] * 6),
            monster("gulpin", "溶食兽", "M", ["污泥攻击"], ivs=[1] * 6),
        ], ["污泥攻击"], species="妙蛙种子")
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.breeds, 3)
        self.assertEqual(candidate.root.braces, 1)
        plan = build_execution_plan(candidate)
        self.assertEqual([step.child.species for step in plan.steps], ["无壳海兔", "水跃鱼", "妙蛙种子"])
        self.assertEqual([step.child.gender for step in plan.steps], ["M", "M", "F"])
        self.assertTrue(all(step.child.moves == ["污泥攻击"] for step in plan.steps))
        self.assertEqual(len(candidate.root.used_ids), 4)

    def test_level_up_or_sketch_route_does_not_grant_inventory_a_free_move(self):
        _, candidate = self.plan([
            monster("f", "伊布", "F"), monster("m", "图图犬", "M"),
        ], ["祈愿"])
        self.assertGreater(candidate.root.purchases, 0)
        self.assertTrue(any("必须已携带技能：祈愿" in text for text in candidate.purchase_requirements()))

    def test_inventory_and_target_aliases_match_without_editing_raw_moves(self):
        source = monster("f", "伊布", "F", ["Wish"])
        _, candidate = self.plan([source], ["祈愿", "Wish"])
        self.assertEqual(candidate.target_moves, ("祈愿",))
        self.assertEqual(candidate.root.inherited_moves, frozenset({"祈愿"}))
        self.assertEqual(source.moves, ["Wish"])

    def test_invalid_moves_are_rejected_by_both_planner_entry_points(self):
        report, candidates = make_report_with_candidates([], "伊布", "F", "", "31/x/x/x/x/x", [], target_moves=["飞膝踢"])
        self.assertFalse(candidates)
        self.assertIn("遗传技能设置无效", report)
        candidates, missing = find_chain_candidates([], "伊布", "F", "", [31, None, None, None, None, None], ["陆上"], target_moves=["飞膝踢"])
        self.assertFalse(candidates)
        self.assertIn("不支持", " ".join(missing))

    def test_four_move_market_bundle_is_explicit(self):
        moves = ["祈愿", "哈欠", "挠痒", "同步干扰"]
        _, candidate = self.plan([monster("f", "伊布", "F")], moves)
        self.assertEqual(candidate.root.inherited_moves, frozenset(moves))
        text = " ".join(candidate.purchase_requirements())
        self.assertIn("必须已携带技能", text)
        for move in moves:
            self.assertIn(move, text)

    def test_same_tier_import_preserves_nature_and_hidden_ability(self):
        report, candidates = make_report_with_candidates([
            monster("f", "伊布", "F", nature="固执", has_hidden_ability=True),
            monster("m", "图图犬", "M", ["祈愿"]),
        ], "伊布", "F", "固执", "31/x/x/x/x/x", [], allow_ditto=False,
            need_hidden_ability=True, target_moves=["祈愿"], nature_strategy="chain")
        self.assertTrue(candidates, report)
        root = candidates[0].root
        self.assertEqual((root.breeds, root.purchases, root.everstones), (1, 0, 1))
        self.assertTrue(root.has_hidden_ability)
        self.assertTrue(root.has_nature)
        self.assertEqual(root.nature, "固执")

    def test_alpha_import_keeps_two_iv_floor(self):
        _, candidate = self.plan([
            monster("f", "伊布", "F", ivs=[31, 31, 1, 1, 1, 1], is_alpha=True, has_hidden_ability=True),
            monster("m", "图图犬", "M", ["祈愿"], ivs=[31, 31, 1, 1, 1, 1], is_alpha=True),
        ], ["祈愿"], ivs="31/31/x/x/x/x", target_alpha=True)
        self.assertEqual((candidate.root.breeds, candidate.root.purchases), (1, 0))
        self.assertTrue(candidate.root.is_alpha)
        self.assertEqual(candidate.root.mask.bit_count(), 2)

    def test_male_only_line_can_hatch_with_same_iv_ditto(self):
        report, candidates = make_report_with_candidates([
            monster("hitmonchan", "快拳郎", "M", ["音速拳"]),
            monster("ditto", "百变怪", "N"),
        ], "无畏小子", "M", "", "31/x/x/x/x/x", [], allow_ditto=True, target_moves=["音速拳"])
        self.assertTrue(candidates, report)
        self.assertEqual((candidates[0].root.breeds, candidates[0].root.purchases), (1, 0))
        self.assertEqual(candidates[0].root.species, "无畏小子")
        self.assertEqual(candidates[0].root.inherited_moves, frozenset({"音速拳"}))

    def test_skill_preparation_does_not_downgrade_protected_material(self):
        _, candidate = self.plan([
            monster("valuable", "伊布", "F", ivs=[31, 31, 1, 1, 1, 1]),
            monster("m", "图图犬", "M", ["祈愿"]),
        ], ["祈愿"])
        self.assertNotIn("valuable", candidate.root.used_ids)

    def test_five_iv_market_route_keeps_all_four_moves_on_maternal_line(self):
        moves = ["祈愿", "哈欠", "挠痒", "同步干扰"]
        _, candidate = self.plan([], moves, ivs="31/31/31/31/31/x")
        self.assertEqual(candidate.root.inherited_moves, frozenset(moves))
        self.assertEqual((candidate.root.breeds, candidate.root.purchases), (15, 16))

    def test_six_iv_market_route_retains_required_move_variants(self):
        moves = ["祈愿", "哈欠", "挠痒", "同步干扰"]
        _, candidate = self.plan([], moves, ivs="31/31/31/31/31/31")
        self.assertEqual(candidate.root.inherited_moves, frozenset(moves))
        self.assertEqual((candidate.root.breeds, candidate.root.purchases), (31, 32))

    def test_completed_five_iv_body_can_import_skills_without_rebuilding(self):
        _, candidate = self.plan([
            monster("body", "伊布", "F", ivs=[31, 31, 31, 31, 31, 1]),
        ], ["祈愿", "哈欠"], ivs="31/31/31/31/31/x")
        self.assertIn("body", candidate.root.used_ids)
        self.assertEqual((candidate.root.breeds, candidate.root.purchases), (1, 1))
        self.assertEqual(candidate.root.inherited_moves, frozenset({"祈愿", "哈欠"}))

    def test_purchased_skill_holder_is_not_reported_as_owned_inventory(self):
        _, candidate = self.plan([], ["祈愿"])
        self.assertGreater(candidate.root.purchases, 0)
        self.assertNotIn("库存中已经有", candidate.description())
        self.assertIn("必须已携带技能：祈愿", candidate.description())

    def test_snapshot_round_trip_preserves_skill_steps_and_sources(self):
        _, candidate = self.plan([
            monster("f", "伊布", "F"), monster("m", "图图犬", "M", ["祈愿"]),
        ], ["祈愿"])
        restored = ChainCandidate.from_dict(candidate.to_dict())
        self.assertEqual(restored.egg_move_sources(), candidate.egg_move_sources())
        self.assertEqual(restored.root.introduced_moves, candidate.root.introduced_moves)
        self.assertEqual(build_execution_plan(restored).steps[-1].child.moves, ["祈愿"])


if __name__ == "__main__":
    unittest.main()
