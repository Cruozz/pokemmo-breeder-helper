import unittest

from guide_data import GuideDatabase, SEASONS, STAT_LABELS, ev_values, get_guide_database, horde_locations_text


def location(name, *, season="任意", period="rarity_day", quantity=5, method="草地", region="关都"):
    return {"location": name, "region_name": region, "type": method, "season": season,
            "min_level": 20, "max_level": 25, period: "5%",
            "is_horde_3x": quantity == 3, "is_horde_5x": quantity == 5}


def species(identifier, stat, locations, **extra_yields):
    return {"id": identifier, "name": f"精灵{identifier}", "locations": locations,
            "yields": {f"ev_{stat}": 1, **{f"ev_{key}": value for key, value in extra_yields.items()}}}


def database(*records):
    return GuideDatabase({"schema_version": 1, "species": list(records)})


class EffortSpotTests(unittest.TestCase):
    def test_different_seasons_and_times_are_independently_pure(self):
        db = database(
            species(1, "sp_attack", [location("混点", season="春", period="rarity_day", quantity=5)]),
            species(4, "speed", [location("混点", season="冬", period="rarity_night", quantity=3)]),
        )
        self.assertTrue(db.find_encounters("1", season="春", period="白天", quantity="5只", stat="sp_attack"))
        self.assertEqual([g.species_id for g in db.find_effort_spots("1", season="春", period="白天", quantity="5只", stat="sp_attack")], [1])
        self.assertEqual([g.species_id for g in db.find_effort_spots(season="冬", period="夜晚", stat="speed")], [4])

    def test_different_species_with_the_same_ev_yield_are_ev_pure(self):
        db = database(species(1, "hp", [location("混点")]), species(2, "hp", [location("混点")]))
        self.assertEqual([g.species_id for g in db.find_effort_spots(stat="hp")], [1, 2])

    def test_name_quantity_and_stat_filters_cannot_hide_competing_ev_stats(self):
        db = database(species(1, "hp", [location("混点", quantity=5)]),
                      species(4, "attack", [location("混点", quantity=3)]))
        self.assertEqual(db.find_effort_spots("1", season="春", period="白天", quantity="5只", stat="hp"), [])

    def test_year_round_row_is_clipped_to_pure_season_and_time_pairs(self):
        all_day = location("部分纯点")
        all_day.update(rarity_morning="5%", rarity_night="5%")
        db = database(species(1, "hp", [all_day]),
                      species(4, "speed", [location("部分纯点", season="春", period="rarity_night")]))
        group = db.find_effort_spots("1", stat="hp")[0]
        spring = [row for row in group.encounters if row.season == "春"]
        self.assertTrue(spring)
        self.assertTrue(all("夜晚" not in dict(row.chances) for row in spring))
        self.assertEqual(db.find_effort_spots("1", season="春", period="夜晚", stat="hp"), [])
        self.assertTrue(db.find_effort_spots("1", season="夏", period="夜晚", stat="hp"))
        text = horde_locations_text(group, effort_species=db.by_id[1])
        self.assertIn("春 · 清晨 / 白天", text)
        self.assertIn("夏 / 秋 / 冬 · 清晨 / 白天 / 夜晚", text)

    def test_source_location_ids_keep_same_named_floors_separate(self):
        first, second = location("同名山洞"), location("同名山洞")
        first["location_id"], second["location_id"] = 1, 2
        db = database(species(1, "hp", [first]), species(4, "attack", [second]))
        self.assertTrue(db.find_effort_spots(stat="hp"))
        self.assertTrue(db.find_effort_spots(stat="attack"))

    def test_grass_water_and_regions_are_distinct_and_normal_encounters_do_not_pollute_pure_hordes(self):
        db = database(
            species(1, "sp_attack", [location("纯点", quantity=3), location("纯点", quantity=5),
                                     location("同名地点", region="关都")]),
            species(4, "speed", [location("纯点", method="水面"), location("同名地点", region="城都")]),
            species(2, "hp", [location("纯点", quantity=1)]),
        )
        groups = db.find_effort_spots(stat="sp_attack")
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group.species_id, 1)
        self.assertEqual(group.location_count, 2)
        self.assertEqual(group.quantities, "3只 / 5只")
        content = horde_locations_text(group, effort_species=db.by_id[1])
        self.assertIn("整群基础值：特攻 +3", content)
        self.assertIn("整群基础值：特攻 +5", content)
        self.assertNotIn("水面", content)
        self.assertEqual(content.count("关都 · 纯点 · 纯点"), 1)
        self.assertEqual([group.species_id for group in db.find_effort_spots(stat="speed")], [4])

    def test_single_species_with_multiple_ev_stats_is_not_an_effort_pure_point(self):
        db = database(species(1, "hp", [location("多项收益")], attack=1))
        self.assertEqual(db.find_effort_spots(stat="hp"), [])

    def test_full_snapshot_checks_all_members_in_each_concrete_season_time_pool(self):
        db = get_guide_database()
        all_groups = db.find_effort_spots()
        self.assertTrue(all_groups)
        ids = [group.species_id for group in all_groups]
        self.assertEqual(len(ids), len(set(ids)))
        for stat in STAT_LABELS:
            groups = db.find_effort_spots(stat=stat)
            self.assertTrue(groups, stat)
            for group in groups:
                values = ev_values(db.by_id[group.species_id])
                self.assertGreater(values[stat], 0)
                self.assertEqual(sum(value > 0 for value in values.values()), 1)
                for row in group.encounters:
                    for season in SEASONS[1:] if row.season == "任意" else (row.season,):
                        for period, _ in row.chances:
                            all_ids = {other.species_id for other in db.hordes
                                       if other.point_key == row.point_key and other.available(season, period)}
                            all_stats = {key for identifier in all_ids for key, value in ev_values(db.by_id[identifier]).items() if value}
                            self.assertEqual(all_stats, {stat})

    def test_reference_defense_hordes_and_seasonal_girafarig_are_restored(self):
        db = get_guide_database()
        ids = {g.species_id for g in db.find_effort_spots(stat="defense")}
        self.assertTrue({74, 75, 95}.issubset(ids))
        self.assertTrue(db.find_effort_spots("203 214号道路", stat="sp_attack"))


if __name__ == "__main__":
    unittest.main()
