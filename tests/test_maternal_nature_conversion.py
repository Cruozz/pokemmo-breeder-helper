import unittest

from chain_planner import ChainState, SpeciesProfile, _maternal_conversion_candidates
from execution import build_execution_plan
from models import Monster
from planner import make_report_with_candidates


def source(key, mask, *, nature=False, ditto=False):
    return ChainState(species="百变怪" if ditto else "长尾怪手", gender="N" if ditto else "M",
                      egg_groups=() if ditto else ("陆上",), mask=mask,
                      has_nature=nature, nature="固执" if nature else "", is_alpha=True,
                      used_ids=frozenset({key}), generation=0, breeds=0, braces=0, everstones=0,
                      material_v=mask.bit_count())


class MaternalNatureConversionTests(unittest.TestCase):
    profile = SpeciesProfile("长尾怪手", "长尾怪手", ("陆上",), False, ("F", "M"))

    def test_adamant_source_and_matching_two_iv_ditto_produce_natured_female(self):
        states = _maternal_conversion_candidates([source("male", 6, nature=True)],
                    [source("ditto", 6, ditto=True)], self.profile, 55, preserve_nature=True)
        self.assertTrue(states)
        for child in states:
            self.assertEqual(child.mask, 6)
            self.assertEqual(child.gender, "F")
            self.assertTrue(child.has_nature)
            self.assertEqual(child.nature, "固执")
            self.assertEqual(child.action.item_a, "不变之石")
            self.assertTrue(child.force_gender_lock)
            self.assertTrue(child.maternal_conversion)

    def test_preserving_nature_cannot_also_brace_the_sources_missing_iv(self):
        states = _maternal_conversion_candidates([source("male", 6, nature=True)],
                    [source("ditto", 5, ditto=True)], self.profile, 55, preserve_nature=True)
        self.assertEqual(states, [])

    def test_matching_three_iv_ditto_upgrades_natured_source_and_locks_female(self):
        states = _maternal_conversion_candidates([source("male", 6, nature=True)],
                    [source("ditto", 7, ditto=True)], self.profile, 55, preserve_nature=True)
        self.assertTrue(states)
        for child in states:
            self.assertEqual(child.mask, 7)
            self.assertEqual(child.gender, "F")
            self.assertEqual(child.nature, "固执")
            self.assertTrue(child.has_nature)
            self.assertEqual(child.action.item_a, "不变之石")
            self.assertEqual(child.action.item_b, "HP护腕")
            self.assertTrue(child.force_gender_lock)

    def test_mismatched_three_iv_ditto_cannot_drop_a_natured_sources_iv(self):
        states = _maternal_conversion_candidates([source("male", 6, nature=True)],
                    [source("ditto", 25, ditto=True)], self.profile, 55, preserve_nature=True)
        self.assertEqual(states, [])

    def test_non_chain_conversion_may_use_two_braces_without_locking_nature(self):
        states = _maternal_conversion_candidates([source("male", 6, nature=True)],
                    [source("ditto", 5, ditto=True)], self.profile, 55)
        self.assertTrue(any(child.mask == 7 and not child.has_nature for child in states))

    def test_large_plain_pool_does_not_prune_the_only_nature_source(self):
        males = [source(f"aaa-plain-{i}", 6) for i in range(12)] + [source("zzz-nature", 6, nature=True)]
        states = _maternal_conversion_candidates(males, [source("ditto", 6, ditto=True)],
                    self.profile, 55, preserve_nature=True)
        self.assertTrue(any("zzz-nature" in child.used_ids and child.has_nature for child in states))
        self.assertTrue(any(not child.has_nature for child in states))

    def test_ditto_can_supply_the_target_nature_when_the_male_does_not(self):
        states = _maternal_conversion_candidates([source("male", 6)],
                    [source("ditto", 6, ditto=True, nature=True)], self.profile, 55, preserve_nature=True)
        self.assertTrue(states)
        self.assertTrue(all(child.has_nature and child.action.item_b == "不变之石" for child in states))

    @staticmethod
    def inventory():
        def material(key, species, gender, mask, nature=""):
            return Monster(id=key, species=species, gender=gender, nature=nature, is_alpha=True,
                           ivs=[31 if mask & (1 << i) else 1 for i in range(6)])
        return [material("adamant-ambipom", "双尾怪手", "M", 6, "固执"),
                material("ditto-2v", "百变怪", "N", 6),
                material("ditto-3v", "百变怪", "N", 7),
                material("donor-3v", "伊布", "M", 7),
                material("donor-4v", "伊布", "M", 23),
                material("donor-5v", "伊布", "M", 55),
                material("weak-female", "长尾怪手", "F", 33)]

    def test_five_iv_chain_uses_evolved_adamant_inventory_as_the_maternal_seed(self):
        for strategy in ("inventory",):
            with self.subTest(strategy=strategy):
                report, candidates = make_report_with_candidates(self.inventory(), "长尾怪手", "", "固执",
                    "31/31/31/x/31/31", ["陆上"], target_alpha=True, allow_ditto=False,
                    nature_strategy="chain", strategy=strategy, convert_maternal_with_ditto=True)
                self.assertTrue(candidates, report)
                plan = build_execution_plan(candidates[0])
                conversions = [step for step in plan.steps if "ditto-3v" in (step.parent_a_id, step.parent_b_id)]
                self.assertEqual(len(conversions), 1)
                step = conversions[0]
                self.assertEqual({step.parent_a_id, step.parent_b_id}, {"adamant-ambipom", "ditto-3v"})
                self.assertEqual(step.child.species, "长尾怪手")
                self.assertEqual(step.child.gender, "F")
                self.assertEqual(step.child.nature, "固执")
                self.assertEqual([i for i, value in enumerate(step.child.ivs) if value == 31], [0, 1, 2])
                self.assertNotIn("ditto-2v", candidates[0].root.used_ids)
                self.assertEqual(candidates[0].root.purchases, 0)
                self.assertEqual(candidates[0].root.breeds, 3)
                self.assertEqual(plan.steps[-1].child.nature, "固执")

    def test_five_iv_chain_can_still_start_with_same_tier_ditto(self):
        inventory = [monster for monster in self.inventory() if monster.id != "ditto-3v"]
        report, candidates = make_report_with_candidates(inventory, "长尾怪手", "", "固执",
            "31/31/31/x/31/31", ["陆上"], target_alpha=True, allow_ditto=False,
            nature_strategy="chain", strategy="inventory", convert_maternal_with_ditto=True)
        self.assertTrue(candidates, report)
        plan = build_execution_plan(candidates[0])
        conversion = next(step for step in plan.steps if "ditto-2v" in (step.parent_a_id, step.parent_b_id))
        self.assertEqual(conversion.child.nature, "固执")
        self.assertEqual(conversion.child.gender, "F")
        self.assertEqual(candidates[0].root.breeds, 4)
        self.assertEqual(candidates[0].root.purchases, 0)

    def test_steps_first_can_choose_a_shorter_market_route_without_forcing_conversion(self):
        report, candidates = make_report_with_candidates(self.inventory(), "长尾怪手", "", "固执",
            "31/31/31/x/31/31", ["陆上"], target_alpha=True, allow_ditto=False,
            nature_strategy="chain", strategy="steps", convert_maternal_with_ditto=True)
        self.assertTrue(candidates, report)
        self.assertEqual(candidates[0].root.breeds, 1)
        self.assertEqual(candidates[0].root.purchases, 1)
        self.assertFalse(candidates[0].root.used_ids & {"ditto-2v", "ditto-3v"})

    def test_disabled_conversion_does_not_use_conversion_only_dittos(self):
        _report, candidates = make_report_with_candidates(self.inventory(), "长尾怪手", "", "固执",
            "31/31/31/x/31/31", ["陆上"], target_alpha=True, allow_ditto=False,
            nature_strategy="chain", convert_maternal_with_ditto=False)
        self.assertTrue(candidates)
        self.assertFalse(candidates[0].root.used_ids & {"ditto-2v", "ditto-3v"})


if __name__ == "__main__":
    unittest.main()
