import json
import unittest
from unittest.mock import patch
from test_mobile_execution import bridge
from models import Monster
from storage import find_high_confidence_duplicate_groups


class MobileInventoryTests(unittest.TestCase):
    def test_duplicates_use_desktop_rules_and_exclude_incomplete_records(self):
        base = dict(species="伊布", gender="F", nature="固执", ivs=[31, 20, 31, 12, 7, 31], moves=["祈愿", "哈欠", "诅咒", "撒娇"])
        items = [Monster(id="a", **base), Monster(id="b", **base),
                 Monster(id="c", **{**base, "moves": base["moves"][:3]}),
                 Monster(id="incomplete", **{**base, "ivs": [None]*6}),
                 Monster(id="different", **{**base, "gender": "M"})]
        expected = [[m.id for m in group] for group in find_high_confidence_duplicate_groups(items)]
        self.assertEqual(json.loads(bridge.inventory_duplicates(json.dumps([m.to_dict() for m in items]))), expected)
        self.assertEqual(expected, [["a", "b", "c"]])

    def test_editor_normalizes_species_and_preserves_inventory_metadata(self):
        item = Monster(id="kept-id", species="eevee", gender="F", account="box", page="3", slot="21", notes="keep", moves=["祈愿"])
        saved = json.loads(bridge.validate_material(json.dumps(item.to_dict())))
        self.assertEqual(saved["species"], "伊布")
        self.assertEqual(saved["egg_groups"], ["陆上"])
        for field in ("id", "account", "page", "slot", "notes", "moves"):
            self.assertEqual(saved[field], item.to_dict()[field])

    def test_editor_rejects_invalid_species_gender_ivs_and_moves(self):
        base = Monster(id="ditto", species="百变怪", gender="N").to_dict()
        for changes in ({"species": "invalid-example"}, {"gender": "M"}, {"ivs": [99]*6}, {"ivs": [31]}, {"moves": [str(i) for i in range(5)]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                bridge.validate_material(json.dumps({**base, **changes}))

    def test_portraits_use_species_database_ids(self):
        icons = json.loads(bridge.species_icons())
        self.assertEqual(icons["伊布"], 133)
        self.assertEqual(icons["eevee"], 133)

    def test_reference_contains_shared_egg_move_sources(self):
        lines = json.loads(bridge.species_reference("伊布"))
        self.assertTrue(any("祈愿" in line for line in lines))
        self.assertTrue(any("陆上" in line for line in lines))

    def test_advanced_rule_choices_reach_shared_planner_and_survive_plan(self):
        for gender in ("smart", "minimal", "lock_all"):
            request = dict(species="伊布", nature="固执", nature_strategy="chain", intermediate_gender_strategy=gender,
                           ivs=["31","31","X","X","X","X"], allow_ditto=False)
            with patch.object(bridge, "make_report_with_candidates", wraps=bridge.make_report_with_candidates) as planner:
                response = json.loads(bridge.generate_plan("[]", json.dumps(request)))
                self.assertTrue(response["ok"], response)
                self.assertEqual(planner.call_args.args[9], "chain")
                self.assertEqual(planner.call_args.args[12], gender)
                self.assertEqual(response["plan"]["planning_options"]["intermediate_gender_strategy"], gender)
