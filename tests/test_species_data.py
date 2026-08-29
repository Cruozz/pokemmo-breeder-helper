from __future__ import annotations

import unittest

from species_data import get_species_database


class SpeciesDataTests(unittest.TestCase):
    def test_resolves_chinese_and_english_names(self) -> None:
        database = get_species_database()
        chinese = database.get("拉鲁拉丝")
        english = database.get("Ralts")
        self.assertIsNotNone(chinese)
        self.assertEqual(chinese, english)
        self.assertEqual(chinese.egg_groups, ("人型", "不定形"))

    def test_genderless_species(self) -> None:
        ditto = get_species_database().get("百变怪")
        self.assertIsNotNone(ditto)
        self.assertEqual(ditto.allowed_genders, ("N",))

    def test_gender_sensitive_final_evolutions_require_matching_hatch_gender(self) -> None:
        database = get_species_database()
        self.assertEqual(database.required_evolution_gender("艾路雷朵"), "M")
        self.assertEqual(database.required_evolution_gender("雪妖女"), "F")
        self.assertEqual(database.required_evolution_gender("蜂女王"), "F")
        self.assertEqual(database.required_evolution_gender("沙奈朵"), "")

    def test_nidoran_lines_share_gender_linked_pokemmo_breeding_family(self) -> None:
        database = get_species_database()
        family = database.linked_breeding_family("尼多王")
        offspring = database.breeding_offspring_by_gender("尼多王")

        self.assertEqual([record.id for record in family], [29, 30, 31, 32, 33, 34])
        self.assertEqual(
            [(gender, record.id) for gender, record in offspring],
            [("F", 29), ("M", 32)],
        )
        self.assertEqual(database.breeding_output_genders("尼多后"), ("F", "M"))
        self.assertEqual(database.get("尼多后").egg_groups, ("怪兽", "陆上"))

    def test_finds_species_inside_noisy_level_text(self) -> None:
        record = get_species_database().find_in_text("Lv.1 蘑蘑菇 早")
        self.assertIsNotNone(record)
        self.assertEqual(record.display_name, "蘑蘑菇")

    def test_resolves_reviewed_species_ocr_confusion(self) -> None:
        record = get_species_database().get("蘑菇草")
        self.assertIsNotNone(record)
        self.assertEqual(record.id, 285)

    def test_resolves_weavile_name_with_ocr_glyph_and_type_suffix(self) -> None:
        record, confident, score = get_species_database().resolve_ocr_name(
            "Lv.69 玛扭拉'冰恶 早",
            "F",
        )
        self.assertIsNotNone(record)
        self.assertEqual(record.display_name, "玛狃拉")
        self.assertTrue(confident)
        self.assertEqual(score, 1.0)

    def test_searches_by_number_and_name_fragment(self) -> None:
        database = get_species_database()
        self.assertEqual(database.search("285")[0].display_name, "蘑蘑菇")
        self.assertIn("蘑蘑菇", [record.display_name for record in database.search("菇")])
        self.assertEqual(database.search("shroom")[0].display_name, "蘑蘑菇")

    def test_resolves_evolution_line_and_default_offspring(self) -> None:
        database = get_species_database()
        line = database.evolution_line("龙王蝎")
        self.assertEqual([record.id for record in line], [451, 452])
        self.assertEqual(database.breeding_parent("龙王蝎").display_name, "钳尾蝎")
        self.assertEqual(database.breeding_offspring("龙王蝎").display_name, "钳尾蝎")

    def test_handles_baby_and_incense_offspring_rules(self) -> None:
        database = get_species_database()
        self.assertEqual(database.breeding_parent("雷丘").display_name, "皮卡丘")
        self.assertEqual(database.breeding_offspring("雷丘").display_name, "皮丘")
        self.assertEqual(database.breeding_offspring("卡比兽").display_name, "卡比兽")
        self.assertTrue(database.requires_incense_for_target("小卡比兽"))
        self.assertFalse(database.requires_incense_for_target("卡比兽"))

    def test_repairs_level_row_gender_and_ascii_noise(self) -> None:
        database = get_species_database()
        record, confident, score = database.resolve_ocr_name("Lv.67引1梦人'超", "M")
        self.assertIsNotNone(record)
        self.assertEqual(record.display_name, "引梦貘人")
        self.assertTrue(confident)
        self.assertGreater(score, 0.82)


if __name__ == "__main__":
    unittest.main()
