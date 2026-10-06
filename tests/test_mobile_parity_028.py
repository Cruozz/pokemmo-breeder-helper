import json
import unittest

from test_mobile_execution import bridge
from test_route_colors import color_fixture, walk
from execution_view import execution_map
from species_data import get_species_database
from models import Monster


class MobileParity028Tests(unittest.TestCase):
    def test_species_picker_exposes_canonical_egg_moves(self):
        eevee = json.loads(bridge.search_species("伊布"))["items"][0]
        self.assertIn("祈愿", eevee["egg_moves"])
        self.assertIn("哈欠", eevee["egg_moves"])

    def test_skill_validation_rejects_invalid_and_over_limit(self):
        for moves in (["不存在技能"], ["祈愿", "哈欠", "诅咒", "撒娇", "假哭"]):
            response = json.loads(bridge.generate_plan("[]", json.dumps(dict(species="伊布", target_moves=moves))))
            self.assertFalse(response["ok"])
            self.assertTrue(response["error"])

    def test_mobile_route_layers_equal_desktop_after_completion_and_reload(self):
        for maternal in (False, True):
            _, plan, inventory = color_fixture(maternal)
            for completed in (False, True):
                plan.steps[0].completed = completed
                mobile = bridge._present_plan(plan, inventory)
                desktop = list(walk(execution_map(plan, inventory, {(plan.id, s.number) for s in plan.steps}, get_species_database())))
                for step in mobile["steps"]:
                    node = next(n for n in desktop if n.step_number == step["number"])
                    self.assertEqual(step["route_role"], node.route_role)
                    self.assertEqual(step["route_moves"], list(node.route_moves))
                    self.assertEqual(step["display_gender"], node.gender)
                    for side in ("a", "b"):
                        record = step[f"parent_{side}_record"]
                        self.assertIsNotNone(record)
                        self.assertTrue(set(step[f"parent_{side}_moves"]).issubset(record["moves"]))

    def test_generated_skill_route_survives_completion_boundary(self):
        request = dict(species="伊布", target_moves=["祈愿"], ivs=["31", "31", "31", "X", "X", "X"], allow_ditto=False)
        response = json.loads(bridge.generate_plan("[]", json.dumps(request)))
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["plan"]["planning_options"]["target_moves"], ["祈愿"])
        inventory = []
        for step in response["plan"]["steps"]:
            result = json.loads(bridge.complete_step(json.dumps(inventory), json.dumps(response), json.dumps(dict(number=step["number"], gender=step["planned_gender"]))))
            self.assertTrue(result["ok"], result)
            response, inventory = result["response"], result["inventory"]
        self.assertIn("祈愿", response["plan"]["steps"][-1]["child"]["moves"])
        self.assertEqual(inventory, [])

    def test_bridge_never_converts_three_v_male_with_two_v_ditto(self):
        inventory = [Monster(id="male", species="伊布", gender="M", ivs=[31,31,31,1,1,1]).to_dict(),
                     Monster(id="ditto", species="百变怪", gender="N", ivs=[31,31,1,1,1,1]).to_dict()]
        for strategy in ("inventory", "steps"):
            request = dict(species="伊布", ivs=["31","31","31","X","X","X"], lock_gender=True,
                           target_gender="F", convert_maternal_with_ditto=True, strategy=strategy)
            response = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(request)))
            self.assertTrue(response["ok"], response)
            for step in response["plan"]["steps"]:
                self.assertFalse({step["parent_a_id"], step["parent_b_id"]} == {"male", "ditto"} and step["child"]["gender"] == "F")

    def test_bridge_upgrades_natured_two_v_male_with_three_v_ditto_and_locks_female(self):
        inventory = [Monster(id="male", species="伊布", gender="M", nature="固执", ivs=[31,31,1,1,1,1]).to_dict(),
                     Monster(id="ditto", species="百变怪", gender="N", ivs=[31,31,31,1,1,1]).to_dict()]
        request = dict(species="伊布", ivs=["31","31","31","X","X","X"], lock_gender=True,
                       target_gender="F", convert_maternal_with_ditto=True, allow_ditto=False,
                       nature="固执", nature_strategy="chain")
        response = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(request)))
        self.assertTrue(response["ok"], response)
        self.assertEqual(len(response["plan"]["steps"]), 1)
        step = response["plan"]["steps"][0]
        self.assertEqual({step["parent_a_id"], step["parent_b_id"]}, {"male", "ditto"})
        self.assertEqual(step["child"]["gender"], "F")
        self.assertEqual(step["child"]["nature"], "固执")
        self.assertEqual(step["child"]["ivs"].count(31), 3)

    def test_bridge_rejects_reported_plain_milotic_two_v_three_v_conversion(self):
        inventory = [Monster(id="male", species="美纳斯", gender="M", nature="爽朗", is_alpha=True,
                             ivs=[9, 27, 30, 31, 29, 31]).to_dict(),
                     Monster(id="ditto", species="百变怪", gender="N", nature="认真", is_alpha=True,
                             ivs=[31, 1, 28, 31, 10, 31]).to_dict()]
        request = dict(species="美纳斯", ivs=["31", "X", "31", "31", "31", "31"],
                       nature="内敛", target_alpha=True, nature_strategy="late", allow_ditto=False,
                       convert_maternal_with_ditto=True)
        response = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(request)))
        self.assertTrue(response["ok"], response)
        for step in response["plan"]["steps"]:
            self.assertNotEqual({step["parent_a_id"], step["parent_b_id"]}, {"male", "ditto"})
