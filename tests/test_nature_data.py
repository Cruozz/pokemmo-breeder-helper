from __future__ import annotations

import unittest

from nature_data import (
    FEATURED_NATURE_NAMES,
    NEUTRAL_NATURES,
    PLANNER_NATURES,
    filter_planner_natures,
    find_nature,
    is_neutral_nature,
    planner_nature_display_name,
)


class NatureDataTests(unittest.TestCase):
    def test_contains_all_standard_natures_and_five_neutral(self) -> None:
        self.assertEqual(len(PLANNER_NATURES) + len(NEUTRAL_NATURES), 25)
        self.assertEqual(len(PLANNER_NATURES), 20)
        self.assertEqual(len(NEUTRAL_NATURES), 5)

    def test_neutral_target_accepts_exact_neutral_names(self) -> None:
        self.assertTrue(is_neutral_nature("无修正（任一）"))
        self.assertTrue(is_neutral_nature("认真"))
        self.assertFalse(is_neutral_nature("胆小"))

    def test_pokemmo_chinese_name_and_effect(self) -> None:
        adamant = find_nature("固执")
        self.assertIsNotNone(adamant)
        self.assertEqual(adamant.english, "Adamant")
        self.assertEqual(adamant.effect, "攻击 +10%，特攻 -10%")
        self.assertEqual(find_nature("Docile").chinese, "坦率")

    def test_featured_planner_natures_are_starred_and_ordered_first(self) -> None:
        self.assertEqual(
            tuple(nature.chinese for nature in PLANNER_NATURES[:4]),
            FEATURED_NATURE_NAMES,
        )
        self.assertEqual(
            tuple(planner_nature_display_name(nature) for nature in PLANNER_NATURES[:4]),
            tuple(f"★ {name}" for name in FEATURED_NATURE_NAMES),
        )

    def test_live_filter_matches_partial_chinese_and_english(self) -> None:
        self.assertEqual(
            tuple(nature.chinese for nature in filter_planner_natures("固")),
            ("固执",),
        )
        self.assertEqual(
            tuple(nature.chinese for nature in filter_planner_natures("tim")),
            ("胆小",),
        )


if __name__ == "__main__":
    unittest.main()
