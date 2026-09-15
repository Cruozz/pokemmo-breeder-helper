import unittest

from models import Monster
from planner import make_report_with_candidates
from execution import build_execution_plan


def material(key, species, gender, ivs):
    return Monster(id=key, species=species, gender=gender, ivs=ivs,
                   is_alpha=True, has_hidden_ability=True, verified=True)


class MaternalAlternativeTests(unittest.TestCase):
    def inventory(self):
        return [
            material('female', '烈咬陆鲨', 'F', [30, 24, 13, 31, 30, 31]),
            material('male', '烈咬陆鲨', 'M', [13, 31, 31, 29, 27, 31]),
            material('ditto', '百变怪', 'N', [18, 31, 31, 24, 31, 22]),
            material('snake', '饭匙蛇', 'F', [25, 31, 13, 3, 29, 31]),
            material('pikachu', '皮卡丘', 'M', [15, 31, 31, 21, 21, 11]),
            material('luxray', '伦琴猫', 'M', [31, 31, 31, 25, 8, 15]),
        ]

    def plan(self, inventory, ivs='31/31/31/x/31/31', conversion=True, nature='固执'):
        report, candidates = make_report_with_candidates(
            inventory, '烈咬陆鲨', '', nature, ivs, ['怪兽', '龙'],
            target_alpha=True, allow_ditto=False, strategy='inventory',
            need_hidden_ability=True, convert_maternal_with_ditto=conversion,
        )
        self.assertTrue(candidates, report)
        return candidates[0]

    def test_weak_female_does_not_disable_four_iv_conversion(self):
        candidate = self.plan(self.inventory())
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.breeds, 4)
        self.assertTrue(candidate.root.maternal_conversion)
        self.assertNotIn('female', candidate.root.used_ids)
        plan = build_execution_plan(candidate)
        conversion = next(s for s in plan.steps if 'ditto' in (s.parent_a_id, s.parent_b_id))
        self.assertEqual(conversion.child.ivs, [None, 31, 31, None, 31, 31])
        self.assertEqual(conversion.child.gender, 'F')
        self.assertTrue(conversion.child.has_hidden_ability)
        self.assertTrue(conversion.child.is_alpha)
        leaves = [s.leaf for s in self.walk(candidate.root) if s.leaf]
        self.assertEqual(sum(m.species == '百变怪' for m in leaves), 1)
        self.assertEqual(len(leaves), len({m.id for m in leaves}))

    @staticmethod
    def walk(root):
        yield root
        if root.action:
            yield from MaternalAlternativeTests.walk(root.action.parent_a)
            yield from MaternalAlternativeTests.walk(root.action.parent_b)

    def test_special_attack_target_also_compares_conversion(self):
        inventory = self.inventory()
        for m in inventory:
            m.ivs[1], m.ivs[3] = m.ivs[3], m.ivs[1]
        candidate = self.plan(inventory, '31/x/31/31/31/31')
        self.assertTrue(candidate.root.maternal_conversion)
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.breeds, 4)

    def test_useful_female_with_extra_attack_stat_is_not_discarded(self):
        inventory = self.inventory()
        inventory[0].ivs = [31, 31, 31, 31, 31, 31]
        candidate = self.plan(inventory, nature='')
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.breeds, 0)
        self.assertFalse(candidate.root.maternal_conversion)
        self.assertEqual(candidate.root.used_ids, frozenset({'female'}))

    def test_complementary_ditto_survives_many_irrelevant_candidates(self):
        inventory = self.inventory()
        inventory += [material(f'aaa-{i:02}', '百变怪', 'N', [31, 1, 1, 31, 1, 1]) for i in range(25)]
        candidate = self.plan(inventory)
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.breeds, 4)
        self.assertIn('ditto', candidate.root.used_ids)

    def test_disabled_conversion_does_not_use_ditto(self):
        candidate = self.plan(self.inventory(), conversion=False)
        self.assertNotIn('ditto', candidate.root.used_ids)
        self.assertFalse(candidate.root.maternal_conversion)


if __name__ == '__main__':
    unittest.main()
