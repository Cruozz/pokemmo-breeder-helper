import unittest

from chain_planner import ChainState, SpeciesProfile, _forced_child
from models import Monster
from planner import make_report_with_candidates


def state(key, mask, gender="M", nature=False):
    return ChainState(species="百变怪" if gender == "N" else "伊布", gender=gender,
                      egg_groups=() if gender == "N" else ("陆上",), mask=mask,
                      has_nature=nature, nature="固执" if nature else "", is_alpha=False,
                      used_ids=frozenset({key}), generation=0, breeds=0, braces=0, everstones=0,
                      material_v=mask.bit_count())


class DittoConversionTests(unittest.TestCase):
    profile = SpeciesProfile("伊布", "伊布", ("陆上",), False, ("F", "M"))

    def test_lower_tier_ditto_cannot_flip_three_iv_breeder_even_if_three_ivs_are_preserved(self):
        for gender, output in (("M", "F"), ("F", "M")):
            for reversed_parents in (False, True):
                for nature in (False, True):
                    with self.subTest(gender=gender, reversed=reversed_parents, nature=nature):
                        breeder, ditto = state("male", 7, gender), state("ditto", 3, "N", nature)
                        child = (_forced_child(ditto, breeder, self.profile, output, brace_b=2, everstone_a=nature)
                                 if reversed_parents else
                                 _forced_child(breeder, ditto, self.profile, output, brace_a=2, everstone_b=nature))
                        self.assertIsNone(child)

    def test_same_tier_conversion_can_raise_ivs(self):
        child = _forced_child(state("male", 7), state("ditto", 11, "N"), self.profile, "F", 2, 3)
        self.assertIsNotNone(child)
        self.assertEqual(child.mask, 15)

    def test_same_tier_conversion_cannot_drop_original_iv(self):
        child = _forced_child(state("male", 7), state("ditto", 25, "N"), self.profile, "F", 1, 3)
        self.assertIsNone(child)

    def test_lower_tier_nature_ditto_still_works_without_gender_conversion(self):
        child = _forced_child(state("male", 7), state("ditto", 3, "N", True),
                              self.profile, "M", brace_a=2, everstone_b=True)
        self.assertIsNotNone(child)
        self.assertEqual(child.mask, 7)
        self.assertTrue(child.has_nature)

    def test_planner_avoids_reported_three_iv_male_two_iv_ditto_route(self):
        inventory = [Monster(id="male", species="伊布", gender="M", ivs=[31, 31, 31, 1, 1, 1]),
                     Monster(id="ditto", species="百变怪", gender="N", ivs=[31, 31, 1, 1, 1, 1])]
        for allow_ditto in (False, True):
            for strategy in ("inventory", "steps"):
                with self.subTest(allow_ditto=allow_ditto, strategy=strategy):
                    report, candidates = make_report_with_candidates(
                        inventory, "伊布", "F", "", "31/31/31/x/x/x", ["陆上"],
                        allow_ditto=allow_ditto, strategy=strategy, convert_maternal_with_ditto=True)
                    self.assertTrue(candidates, report)
                    for candidate in candidates:
                        pending = [candidate.root]
                        while pending:
                            current = pending.pop()
                            if current.action:
                                parents = (current.action.parent_a, current.action.parent_b)
                                self.assertFalse(current.gender == "F" and current.used_ids == frozenset({"male", "ditto"}))
                                pending.extend(parents)


if __name__ == "__main__":
    unittest.main()
