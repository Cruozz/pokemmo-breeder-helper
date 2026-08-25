from __future__ import annotations

import unittest

from reference_data import get_reference_database


class ReferenceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database = get_reference_database()

    def test_imported_workbook_record_counts(self) -> None:
        self.assertEqual(len(self.database.location_records), 4441)
        self.assertEqual(sum(len(routes) for moves in self.database.egg_moves_by_species.values() for routes in moves.values()), 11145)

    def test_queries_locations_and_egg_moves_by_species(self) -> None:
        self.assertTrue(self.database.locations_for_species("蘑蘑菇"))
        bulbasaur_moves = self.database.egg_moves_for_species("妙蛙种子")
        self.assertIn("花瓣舞", bulbasaur_moves)
        self.assertIn("妙蛙花", bulbasaur_moves["花瓣舞"][0])

    def test_recognizes_egg_move(self) -> None:
        self.assertTrue(self.database.is_egg_move("妙蛙种子", "花瓣舞"))
        self.assertFalse(self.database.is_egg_move("妙蛙种子", "撞击"))

    def test_canonicalizes_reviewed_move_ocr_errors(self) -> None:
        self.assertEqual(self.database.canonical_move("吸章"), "吸取")
        self.assertEqual(self.database.canonical_move("吸联"), "吸取")
        self.assertEqual(self.database.canonical_move("麻牌粉"), "麻痹粉")
        self.assertEqual(self.database.canonical_move("长豪"), "长嚎")
        self.assertEqual(self.database.canonical_move("Tackle"), "撞击")


if __name__ == "__main__":
    unittest.main()
