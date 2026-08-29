from __future__ import annotations

import unittest

from models import Monster, format_box_position


class MonsterPositionTests(unittest.TestCase):
    def test_box_slot_is_presented_as_page_row_column(self) -> None:
        self.assertEqual(format_box_position("1", "1"), "1-1,1")
        self.assertEqual(format_box_position("5", "13"), "5-2,3")
        self.assertEqual(format_box_position("8", "60"), "8-6,10")

    def test_invalid_or_incomplete_position_stays_unlocated(self) -> None:
        self.assertEqual(format_box_position("", "13"), "")
        self.assertEqual(format_box_position("5", ""), "")
        self.assertEqual(format_box_position("5", "not-a-slot"), "")

    def test_legacy_page_and_slot_rows_are_converted_on_load(self) -> None:
        monster = Monster.from_dict(
            {
                "id": "legacy-row",
                "species": "海星星",
                "page": "5",
                "slot": "13",
            }
        )

        self.assertEqual(monster.page, "5")
        self.assertEqual(monster.slot, "13")
        self.assertEqual(monster.position_label, "5-2,3")

    def test_staged_nature_hand_metadata_survives_inventory_roundtrip(self) -> None:
        original = Monster(
            id="nature-hand",
            species="陆上组兼容素材",
            gender="M",
            ivs=[31, 31, 31, None, 31, None],
            breeding_target_key="索罗亚|adamant|31/31/31/x/31/31|normal|regular|",
            breeding_role="nature_hand",
            nature_attempt_level=4,
            nature_attempt_result="miss",
        )

        restored = Monster.from_dict(original.to_dict())

        self.assertEqual(restored.breeding_target_key, original.breeding_target_key)
        self.assertEqual(restored.breeding_role, "nature_hand")
        self.assertEqual(restored.nature_attempt_level, 4)
        self.assertEqual(restored.nature_attempt_result, "miss")

    def test_ditto_route_gender_pending_marker_survives_roundtrip(self) -> None:
        restored = Monster.from_dict(
            Monster(
                id="ditto-next",
                species="晃晃斑",
                gender="M",
                gender_unconfirmed=True,
            ).to_dict()
        )

        self.assertTrue(restored.gender_unconfirmed)
        self.assertEqual(restored.gender, "M")


if __name__ == "__main__":
    unittest.main()
