from __future__ import annotations

from dataclasses import replace
import gzip
import json
from pathlib import Path
import unittest

from guide_data import GuideDatabase, STAT_LABELS, ev_text, ev_values, get_guide_database, group_hordes, horde_locations_text
from scripts.build_guide_data import build


class GuideDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = get_guide_database()

    def test_complete_separate_snapshot(self):
        self.assertEqual(set(self.database.by_id), set(range(1, 650)))
        self.assertGreater(len(self.database.hordes), 4000)
        self.assertEqual({row.season for row in self.database.encounters}, {"任意", "春", "夏", "秋", "冬"})
        self.assertEqual(len(self.database.metadata["source_sha256"]), 64)

    def test_species_search_chinese_english_and_exact_number(self):
        for query in ("皮卡丘", "Pikachu", "025", "#25"):
            self.assertEqual([record["id"] for record in self.database.find_species(query)], [25])

    def test_type_group_ability_filters_are_combined(self):
        results = self.database.find_species(pokemon_type="草", egg_group="植物组", ability="茂盛")
        self.assertTrue(results)
        self.assertIn(1, [record["id"] for record in results])
        self.assertEqual(self.database.find_species("肯定不存在的精灵"), [])

    def test_season_and_time_do_not_leak(self):
        for season in ("春", "夏", "秋", "冬"):
            rows = self.database.find_encounters(season=season, period="夜晚", quantity="5只", region="合众")
            self.assertTrue(rows)
            self.assertTrue(all(row.season in {season, "任意"} for row in rows))
            self.assertTrue(all(row.quantity == 5 and row.region == "合众" for row in rows))
            self.assertTrue(all("夜晚" in dict(row.chances) for row in rows))

    def test_unknown_time_is_not_treated_as_available(self):
        row = replace(self.database.hordes[0], chances=())
        self.assertTrue(row.available("全部季节", "全部时段"))
        self.assertFalse(row.available("全部季节", "夜晚"))

    def test_all_year_is_available_in_every_season(self):
        row = replace(self.database.hordes[0], season="任意")
        for season in ("春", "夏", "秋", "冬"):
            self.assertTrue(row.available(season, "全部时段"))

    def test_effort_value_and_single_stat_filter(self):
        for stat in STAT_LABELS:
            rows = self.database.find_encounters(season="冬", stat=stat, single_stat=True)
            self.assertTrue(rows)
            totals = []
            for row in rows:
                values = ev_values(self.database.by_id[row.species_id])
                self.assertGreater(values[stat], 0)
                self.assertEqual(sum(value > 0 for value in values.values()), 1)
                totals.append(values[stat] * row.quantity)
            self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(ev_text(self.database.by_id[1], 5), "特攻 +5")

    def test_horde_query_does_not_include_single_encounters(self):
        self.assertTrue(all(row.quantity in {3, 5} for row in self.database.find_encounters()))
        self.assertTrue(any(row.quantity == 1 for row in self.database.find_encounters(quantity="全部遭遇")))

    def test_location_and_name_query(self):
        row = self.database.hordes[0]
        results = self.database.find_encounters(f"{row.name} {row.location.split('(')[0]}")
        self.assertIn(row, results)

    def test_no_duplicate_rows(self):
        self.assertEqual(len(set(self.database.encounters)), len(self.database.encounters))

    def test_horde_grouping_preserves_rows_and_does_not_mix_season_time_conditions(self):
        source = self.database.find_encounters()
        grouped = group_hordes(source)
        self.assertEqual(len(grouped), len({row.species_id for row in source}))
        self.assertEqual({row for group in grouped for row in group.encounters}, set(source))
        sample = source[0]
        spring = replace(sample, season="春", chances=(("清晨", "10%"),))
        summer = replace(sample, season="夏", chances=(("清晨", "10%"),))
        winter = replace(sample, season="冬", chances=(("夜晚", "20%"),))
        group = group_hordes([spring, summer, winter])[0]
        content = horde_locations_text(group)
        self.assertEqual(group.location_count, 1)
        self.assertIn("春 / 夏 · 清晨", content)
        self.assertIn("冬 · 夜晚", content)
        self.assertNotIn("春 / 夏 / 冬", content)

    def test_builder_rejects_incomplete_input(self):
        with self.assertRaises(ValueError):
            build(b"[]", "2026-09-29")

    def test_builder_rejects_unknown_season(self):
        path = Path(__file__).resolve().parents[1] / "data" / "guide.json.gz"
        payload = json.loads(gzip.decompress(path.read_bytes()))
        payload["species"][0]["locations"][0]["season"] = "unknown"
        with self.assertRaises(ValueError):
            build(json.dumps(payload["species"]).encode(), "2026-09-29")

    def test_bad_schema_is_rejected(self):
        with self.assertRaises(ValueError):
            GuideDatabase({"schema_version": 2})


if __name__ == "__main__":
    unittest.main()
