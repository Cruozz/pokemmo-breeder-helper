"""Small exhaustive inventory oracle, independent of the recursive planner."""
import itertools
import unittest

from chain_planner import ChainState, SpeciesProfile, _structured_search, _one_breed_market_goals
from models import Monster


def leaf(key, species, gender, mask, groups=("虫",), alpha=False):
    return ChainState(species=species, gender=gender, egg_groups=groups, mask=mask,
        has_nature=False, nature="", is_alpha=alpha, used_ids=frozenset({key}),
        generation=0, breeds=0, braces=0, everstones=0, purchases=0,
        material_v=max(2 if alpha else 0, mask.bit_count()),
        leaf=Monster(id=key, species=species, gender=gender, egg_groups=list(groups)))


def exhaustive_plain(leaves, target_mask, max_leaves=None, final_groups=None):
    # State = species, sex, groups, exact guaranteed mask, consumed identities,
    # alpha. Enumerate every ascending equal-tier pair without planner helpers.
    states = {(s.species, s.gender, s.egg_groups, s.mask, s.used_ids, s.is_alpha)
              for s in leaves if s.mask and not s.mask & ~target_mask
              and s.effective_material_v == s.mask.bit_count()}
    for level in range(2, target_mask.bit_count() + 1):
        parents = [s for s in states if s[3].bit_count() == level - 1]
        buckets = {}
        for parent in parents:
            buckets.setdefault((parent[3], len(parent[4])), []).append(parent)
        pairs = ((a, b) for a in parents
                 if not (final_groups and level == target_mask.bit_count()
                         and not set(a[2]) & set(final_groups))
                 for (mask, count), bucket in buckets.items()
                 if (a[3] ^ mask).bit_count() == 2
                 and (max_leaves is None or len(a[4]) + count <= max_leaves)
                 for b in bucket)
        for a, b in pairs:
            if a[0] == "百变怪" or a[4] & b[4]:
                continue
            if b[0] != "百变怪" and not (a[1] == "F" and b[1] == "M" and set(a[2]) & set(b[2])):
                continue
            if (a[3] ^ b[3]).bit_count() != 2:
                continue
            for sex in ("F", "M"):
                states.add((a[0], sex, a[2], a[3] | b[3], a[4] | b[4], a[5] and b[5]))
    return states


class StrategySearchTests(unittest.TestCase):
    profile = SpeciesProfile("刺尾虫", "刺尾虫", ("虫",), False, ("F", "M"), "刺尾虫")

    def test_low_iv_mate_built_before_existing_two_iv(self):
        leaves = [leaf("worm", "刺尾虫", "F", 20),
                  leaf("female", "钳尾蝎", "F", 2, ("虫", "水中3")),
                  leaf("male", "始祖小鸟", "M", 4, ("飞行", "水中3"))]
        goals = _structured_search(leaves, self.profile, 22, False, "M", 2,
                                   exact=True, independent_hand=True)
        self.assertTrue(goals)
        self.assertEqual((goals[0].purchases, goals[0].breeds), (0, 2))
        self.assertEqual(goals[0].used_ids, frozenset({"worm", "female", "male"}))

    def test_small_exhaustive_inventory_and_identity_conflicts(self):
        base = [leaf("a", "刺尾虫", "F", 3), leaf("b", "钳尾蝎", "F", 2),
                leaf("c", "圆丝蛛", "M", 4), leaf("d", "圆丝蛛", "M", 1)]
        # All subsets, including cases where a plausible mate would reuse a
        # consumed parent. Compare identities as well as the shortest length.
        for count in range(5):
            for subset in itertools.combinations(base, count):
                oracle = {s[4] for s in exhaustive_plain(subset, 7)
                          if s[0] == "刺尾虫" and s[1] == "M" and s[3] == 7}
                actual = _structured_search(list(subset), self.profile, 7, False, "M", 2,
                                            exact=True, independent_hand=True)
                self.assertEqual({s.used_ids for s in actual}, oracle)

    def test_market_shortcut_is_one_egg_not_a_finished_purchase(self):
        for alpha in (False, True):
            goals = _one_breed_market_goals([], self.profile, [31, 0, 31, None, 31, None],
                                           23, "M", alpha, False)
            self.assertTrue(goals)
            for goal in goals:
                self.assertEqual((goal.breeds, goal.purchases, goal.mask), (1, 2, 23))
                self.assertFalse(goal.has_nature)
                self.assertEqual(goal.is_alpha, alpha)
                parents = (goal.action.parent_a, goal.action.parent_b)
                self.assertEqual([p.mask.bit_count() for p in parents], [3, 3])
                self.assertFalse(parents[0].used_ids & parents[1].used_ids)

    def test_market_keeps_mixed_route_and_checks_egg_groups(self):
        for groups, purchases in ((("虫",), 1), (("陆上",), 2)):
            goals = _one_breed_market_goals([leaf("donor", "圆丝蛛", "M", 7, groups)],
                self.profile, [31, 31, 31, None, 31, None], 23, "M", False, False)
            self.assertEqual(min(g.purchases for g in goals), purchases)

    def test_ditto_switch_and_alpha_floor(self):
        source = leaf("source", "刺尾虫", "M", 7)
        ditto = leaf("ditto", "百变怪", "N", 19, ())
        for enabled, expected in ((False, 1), (True, 0)):
            goals = _one_breed_market_goals([source, ditto], self.profile,
                [31, 31, 31, None, 31, None], 23, "M", False, enabled)
            self.assertEqual(min(g.purchases for g in goals), expected)
        self.assertFalse(_one_breed_market_goals([], self.profile,
            [31, 31, None, None, None, None], 3, "M", True, False))

    def test_exhaustive_alpha_and_ditto_inventory_variants(self):
        for alpha, ditto in itertools.product((False, True), repeat=2):
            leaves = [leaf("a", "刺尾虫", "M" if ditto else "F", 3, alpha=alpha),
                      leaf("b", "百变怪" if ditto else "圆丝蛛",
                           "N" if ditto else "M", 6, () if ditto else ("虫",), alpha=alpha)]
            expected = {s[4] for s in exhaustive_plain(leaves, 7)
                        if s[0] == "刺尾虫" and s[1] == "M" and s[3] == 7 and s[5] == alpha}
            actual = _structured_search(leaves, self.profile, 7, False, "M", 2,
                                        exact=True, independent_hand=True)
            self.assertEqual({s.used_ids for s in actual if s.is_alpha == alpha}, expected)

    def test_shortcuts_preserve_nature_hidden_ability_and_move(self):
        goals = _one_breed_market_goals([], self.profile,
            [31, 31, 31, None, 31, None], 23, "F", False, False,
            need_nature=True, nature="固执", hidden=True)
        self.assertTrue(goals)
        self.assertTrue(all(g.has_nature and g.has_hidden_ability and g.everstones == 1 for g in goals))
        mother = leaf("mother", "刺尾虫", "F", 7)
        mother.has_hidden_ability = True
        mother.inherited_moves = frozenset({"测试技能"})
        goals = _one_breed_market_goals([mother], self.profile,
            [31, 31, 31, None, 31, None], 23, "F", False, False,
            hidden=True, moves=frozenset({"测试技能"}))
        self.assertTrue(goals)
        self.assertTrue(all(g.has_hidden_ability and "测试技能" in g.inherited_moves for g in goals))

    def test_end_to_end_strategies_keep_random_hand_phase(self):
        from planner import make_report_with_candidates
        base = [Monster(id="body", species="飞天螳螂", gender="F", nature="勇敢",
                        ivs=[31, 31, 31, 8, 31, 31], egg_groups=["虫"]),
                Monster(id="mother", species="刺尾虫", gender="F", ivs=[31, 31, 1, 1, 1, 1], egg_groups=["虫"]),
                Monster(id="mate", species="圆丝蛛", gender="M", ivs=[1, 31, 31, 1, 1, 1], egg_groups=["虫"]),
                Monster(id="other", species="圆丝蛛", gender="M", ivs=[31, 1, 31, 1, 31, 1], egg_groups=["虫"])]
        for strategy, expected in (("inventory", (0, 2)), ("steps", (1, 1))):
            report, candidates = make_report_with_candidates(base, "飞天螳螂", "", "固执",
                "31/31/31/x/31/31", ["虫"], allow_ditto=False, strategy=strategy)
            self.assertTrue(candidates, report)
            best = candidates[0]
            self.assertEqual((best.root.purchases, best.root.breeds), expected)
            self.assertEqual(best.nature_phase, "gamble_upper")
            self.assertEqual(best.root.gender, "M")
            self.assertFalse(best.root.has_nature)
            self.assertNotIn("body", best.root.used_ids)


if __name__ == "__main__":
    unittest.main()
