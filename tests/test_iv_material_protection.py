"""Preserve whole inventory materials whose perfect IVs lie on target X stats."""
import json
import unittest

from chain_planner import find_chain_candidates
from execution import build_execution_plan
from models import Monster
from planner import find_candidates, make_report_with_candidates


TARGET = [31, None, 31, 31, 31, 31]


def material(key, species, gender, mask, nature="", **options):
    return Monster(id=key, species=species, gender=gender, nature=nature,
                   ivs=[31 if mask & (1 << i) else 1 for i in range(6)], **options)


def walk(node):
    yield node
    if node.action:
        yield from walk(node.action.parent_a)
        yield from walk(node.action.parent_b)


class IVMaterialProtectionTests(unittest.TestCase):
    def test_reported_gengar_and_ditto_are_protected_across_all_planning_options(self):
        stock = [Monster(id="gengar", species="耿鬼", gender="M", nature="慎重",
                         ivs=[31, 31, 13, 4, 18, 6]),
                 Monster(id="ditto", species="百变怪", gender="N", nature="爽朗",
                         ivs=[19, 31, 0, 9, 3, 31]),
                 material("male", "烛光灵", "M", 11),
                 material("female", "怨影娃娃", "F", 15)]
        before = [monster.to_dict() for monster in stock]
        for strategy in ("inventory", "steps"):
            for allow_ditto in (False, True):
                for nature_strategy in ("late", "chain"):
                    with self.subTest(strategy=strategy, ditto=allow_ditto, nature=nature_strategy):
                        report, candidates = make_report_with_candidates(stock, "耿鬼", "", "内敛",
                            "31/x/31/31/31/31", [], strategy=strategy, allow_ditto=allow_ditto,
                            nature_strategy=nature_strategy, convert_maternal_with_ditto=True)
                        self.assertTrue(candidates, report)
                        for candidate in candidates:
                            self.assertFalse(candidate.root.used_ids & {m.id for m in stock})
                            for node in walk(candidate.root):
                                if node.leaf:
                                    self.assertNotEqual(node.leaf.ivs[1], 31)
                            plan = build_execution_plan(candidate)
                            self.assertTrue(all(not {step.parent_a_id, step.parent_b_id} &
                                                {m.id for m in stock} for step in plan.steps))
                        self.assertIn("X 项", report)
                        self.assertIn("攻击", report)
        self.assertEqual(before, [monster.to_dict() for monster in stock])

    def test_x_stat_with_nonperfect_or_unknown_iv_keeps_material_usable(self):
        for attack in (None, 0, 1, 30):
            with self.subTest(attack=attack):
                stock = [Monster(id="ready", species="耿鬼", gender="F", nature="内敛",
                                 ivs=[31, attack, 31, 31, 31, 31])]
                report, candidates = make_report_with_candidates(stock, "耿鬼", "", "内敛",
                                                                  "31/x/31/31/31/31", [])
                self.assertTrue(candidates, report)
                self.assertEqual(candidates[0].root.used_ids, frozenset({"ready"}))
                self.assertEqual(candidates[0].root.breeds, 0)

    def test_direct_chain_entry_excludes_extra_iv_stock_before_maternal_conversion(self):
        stock = [material("source", "鬼斯", "M", 3), material("ditto", "百变怪", "N", 34)]
        candidates, _ = find_chain_candidates(stock, "鬼斯", "", "", TARGET, ["不定形"],
                                              allow_ditto=False, convert_maternal_with_ditto=True)
        self.assertTrue(candidates)
        self.assertTrue(all(not candidate.root.used_ids & {"source", "ditto"} for candidate in candidates))

    def test_every_x_stat_protects_perfect_iv_materials(self):
        for index in range(6):
            with self.subTest(index=index):
                target = [31] * 6
                target[index] = None
                stock = [material("six-v", "鬼斯", "F", 63)]
                candidates, _ = find_chain_candidates(stock, "鬼斯", "", "", target, ["不定形"])
                self.assertTrue(candidates)
                self.assertTrue(all("six-v" not in candidate.root.used_ids for candidate in candidates))

    def test_target_nature_and_hidden_ability_do_not_bypass_extra_iv_protection(self):
        stock = [material("nature-ha", "耿鬼", "F", 63, "内敛", has_hidden_ability=True)]
        report, candidates = make_report_with_candidates(stock, "耿鬼", "", "内敛",
            "31/x/31/31/31/31", [], need_hidden_ability=True, nature_strategy="chain")
        self.assertTrue(candidates, report)
        self.assertTrue(all("nature-ha" not in candidate.root.used_ids for candidate in candidates))

    def test_attack_material_remains_usable_for_later_attack_target(self):
        stock = [material("gengar", "耿鬼", "M", 3, "内敛"),
                 material("ditto", "百变怪", "N", 3),
                 material("donor3", "烛光灵", "M", 7),
                 material("donor4", "怨影娃娃", "M", 23),
                 material("donor5", "随风球", "M", 55)]
        report, candidates = make_report_with_candidates(stock, "耿鬼", "", "内敛",
            "31/31/31/x/31/31", [], nature_strategy="chain", allow_ditto=False,
            convert_maternal_with_ditto=True)
        self.assertTrue(candidates, report)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertEqual(candidates[0].root.used_ids, frozenset(m.id for m in stock))
        self.assertEqual(build_execution_plan(candidates[0]).steps[-1].child.nature, "内敛")

    def test_no_x_target_keeps_all_six_perfect_ivs_usable(self):
        stock = [material("six-v", "耿鬼", "F", 63, "内敛")]
        report, candidates = make_report_with_candidates(stock, "耿鬼", "", "内敛",
                                                         "31/31/31/31/31/31", [])
        self.assertTrue(candidates, report)
        self.assertEqual(candidates[0].root.used_ids, frozenset({"six-v"}))
        self.assertEqual(candidates[0].root.breeds, 0)

    def test_legacy_single_step_entry_also_protects_extra_iv_stock(self):
        stock = [material("mother", "鬼斯", "F", 3),
                 material("father", "怨影娃娃", "M", 34, egg_groups=["不定形"])]
        candidates, _ = find_candidates(stock, "鬼斯", "", "", "31/x/x/x/x/31", ["不定形"])
        self.assertEqual(candidates, [])

    def test_mobile_bridge_uses_the_same_material_protection(self):
        from test_mobile_execution import bridge
        stock = [material("source", "耿鬼", "M", 3), material("ditto", "百变怪", "N", 34)]
        request = dict(species="耿鬼", nature="内敛", ivs=["31", "X", "31", "31", "31", "31"],
                       allow_ditto=False, convert_maternal_with_ditto=True)
        response = json.loads(bridge.generate_plan(json.dumps([m.to_dict() for m in stock]), json.dumps(request)))
        self.assertTrue(response["ok"], response)
        self.assertTrue(all(not {step["parent_a_id"], step["parent_b_id"]} & {"source", "ditto"}
                            for step in response["plan"]["steps"]))
        self.assertIn("X 项", response["report"])


if __name__ == "__main__":
    unittest.main()
