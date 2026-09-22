"""Parity coverage for the Android JSON boundary and V0.2.2 execution rules."""
import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path

from models import Monster
from planner import make_report_with_candidates
from execution import build_execution_plan

spec = importlib.util.spec_from_file_location("mobile_boundary", Path(__file__).resolve().parents[1] / "android-app/app/src/main/python/mobile_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class MobileExecutionTests(unittest.TestCase):
    def generate(self, inventory=(), **options):
        request = dict(species="索罗亚克", nature="", ivs=["31", "31", "31", "X", "X", "X"], allow_ditto=False)
        request.update(options)
        response = json.loads(bridge.generate_plan(json.dumps(list(inventory)), json.dumps(request)))
        self.assertTrue(response["ok"], response)
        return response

    def complete(self, response, inventory, step, **outcome):
        answers = dict(number=step["number"], gender=step["planned_gender"])
        answers.update(outcome)
        return json.loads(bridge.complete_step(json.dumps(inventory), json.dumps(response), json.dumps(answers)))

    def test_same_target_has_same_desktop_execution(self):
        response = self.generate()
        _, candidates = make_report_with_candidates([], "索罗亚克", "", "", "31/31/31/x/x/x", [], allow_ditto=False)
        desktop = build_execution_plan(candidates[0])
        mobile = response["plan"]
        self.assertEqual(response["rules_version"], "0.2.8")
        self.assertEqual([(s.child.species, s.child.ivs, s.gender_policy, s.item_a, s.item_b) for s in desktop.steps],
                         [(s["child"]["species"], s["child"]["ivs"], s["gender_policy"], s["item_a"], s["item_b"]) for s in mobile["steps"]])

    def test_matching_outcome_keeps_route_id_and_final_not_in_inventory(self):
        response = self.generate()
        plan_id = response["plan"]["id"]
        description = response["plan"]["candidate_description"]
        used_count = response["plan"]["inventory_used_count"]
        inventory = []
        for step in response["plan"]["steps"]:
            result = self.complete(response, inventory, step)
            self.assertTrue(result["ok"], result)
            inventory, response = result["inventory"], result["response"]
            self.assertEqual(response["plan"]["id"], plan_id)
            self.assertEqual(response["plan"]["candidate_description"], description)
            self.assertEqual(response["plan"]["inventory_used_count"], used_count)
            self.assertFalse(response["plan"]["needs_replan"])
        self.assertEqual(inventory, [])
        self.assertTrue(all(s["completed"] for s in response["plan"]["steps"]))

    def test_cannot_skip_dependencies_or_complete_twice(self):
        response = self.generate()
        steps = response["plan"]["steps"]
        self.assertFalse(self.complete(response, [], steps[-1])["ok"])
        done = self.complete(response, [], steps[0])
        self.assertTrue(done["ok"])
        self.assertFalse(self.complete(done["response"], done["inventory"], steps[0])["ok"])

    def test_missing_inventory_parent_rejected_before_any_mutation(self):
        inventory = [Monster(id="a", species="索罗亚", gender="F", ivs=[31, 31, None, None, None, None]).to_dict(),
                     Monster(id="b", species="长毛狗", gender="M", ivs=[31, None, 31, None, None, None]).to_dict()]
        response = self.generate(inventory)
        result = self.complete(response, [], response["plan"]["steps"][0])
        self.assertFalse(result["ok"])
        self.assertNotIn("inventory", result)

    def test_nature_confirmation_required_and_miss_pauses_without_replacing(self):
        body = Monster(id="body", species="尼多兰", gender="F", nature="温顺",
                       ivs=[31,None,31,31,31,31], is_alpha=True, has_hidden_ability=True)
        inventory = [body.to_dict()]
        response = self.generate(inventory, species="尼多王", nature="内敛", target_alpha=True,
                                 need_hidden_ability=True, ivs=["31","X","31","31","31","31"])
        self.assertEqual(response["plan"]["nature_phase"], "gamble_upper")
        self.assertEqual(response["plan"]["retained_materials"][0]["id"], "body")
        original_id = response["plan"]["id"]
        for step in response["plan"]["steps"]:
            if step["should_check_nature"]:
                self.assertFalse(self.complete(response, inventory, step)["ok"])
            result = self.complete(response, inventory, step, nature_hit=False)
            self.assertTrue(result["ok"], result)
            inventory, response = result["inventory"], result["response"]
        self.assertEqual(response["plan"]["id"], original_id)
        self.assertTrue(response["plan"]["needs_replan"])
        self.assertIn("body", {item["id"] for item in inventory})
        request = response["plan"]["planning_options"]
        proposed = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(request)))
        self.assertTrue(proposed["ok"], proposed)
        self.assertEqual(proposed["plan"]["nature_phase"], "gamble_lower")
        self.assertTrue(response["plan"]["needs_replan"])

    def test_legacy_mark_only_plan_cannot_nuke_inventory(self):
        response = self.generate()
        response.pop("rules_version")
        self.assertFalse(self.complete(response, [], response["plan"]["steps"][0])["ok"])

    def test_full_nature_lifecycle_keeps_final_target_and_reaches_finished_product(self):
        for target, alpha, level, hidden in (
            ("尼多王", True, 5, True), ("尼多王", True, 5, False),
            ("暴雪王", True, 5, True), ("索罗亚克", False, 5, False),
            ("尼多王", True, 4, True), ("索罗亚克", False, 4, False),
        ):
            for hit_at in (None, ("maternal", level - 1), ("maternal", level),
                           ("gamble_upper", level - 1), ("gamble_lower", level - 2)):
                with self.subTest(target=target, alpha=alpha, level=level, hit_at=hit_at):
                    ivs = ["31", "X", "31", "31", "31", "31" if level == 5 else "X"]
                    inventory = []
                    response = self.generate(species=target, nature="内敛", ivs=ivs,
                                             target_alpha=alpha, need_hidden_ability=hidden)
                    request = response["plan"]["planning_options"]
                    phases = []
                    for _ in range(6):
                        plan = response["plan"]
                        phases.append(plan["nature_phase"])
                        self.assertTrue(plan["steps"], response)
                        self.assertEqual(plan["target_iv_count"], level)
                        self.assertEqual(plan["final_target"]["ivs"], [None if v == "X" else 31 for v in ivs])
                        original_id = plan["id"]
                        for step in plan["steps"]:
                            count = sum(v is not None for v in step["child"]["ivs"])
                            hit = step["should_check_nature"] and hit_at == (plan["nature_phase"], count)
                            result = self.complete(response, inventory, step, nature_hit=hit)
                            self.assertTrue(result["ok"], result)
                            inventory, response = result["inventory"], result["response"]
                            self.assertEqual(response["plan"]["id"], original_id)
                            if response["plan"]["needs_replan"]:
                                self.assertIn(step["child"]["id"], {m["id"] for m in inventory})
                                break
                        if not response["plan"]["needs_replan"]:
                            child = response["plan"]["steps"][-1]["child"]
                            self.assertEqual(sum(v == 31 for v in child["ivs"]), level)
                            self.assertEqual(child["nature"], "内敛")
                            self.assertEqual(child["is_alpha"], alpha)
                            if hidden:
                                self.assertTrue(child["has_hidden_ability"])
                            if target == "尼多王":
                                self.assertEqual((child["species"], child["gender"]), ("尼多朗", "M"))
                            self.assertNotIn(child["id"], {m["id"] for m in inventory})
                            break
                        saved_options = response["plan"]["planning_options"]
                        self.assertEqual(saved_options["ivs"], request["ivs"])
                        response = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(saved_options)))
                        self.assertTrue(response["ok"], response)
                    else:
                        self.fail(f"Route did not finish: {phases}")
                    if hit_at is None:
                        expected = ["maternal", "gamble_upper"]
                        if level == 5 or not alpha:
                            expected.append("gamble_lower")
                        self.assertEqual(phases, expected + ["guarantee"])

    def test_existing_four_iv_mother_can_continue_without_rescanning(self):
        mother = Monster(id="saved-4v", species="尼多兰", gender="F", is_alpha=True,
                         has_hidden_ability=True, ivs=[31, None, 31, 31, 31, None])
        response = self.generate([mother.to_dict()], species="尼多王", nature="内敛",
                                 target_alpha=True, need_hidden_ability=True,
                                 ivs=["31", "X", "31", "31", "31", "31"])
        self.assertEqual(response["plan"]["nature_phase"], "maternal")
        self.assertIn(mother.id, response["plan"]["materials"])
        self.assertEqual(sum(v == 31 for v in response["plan"]["steps"][-1]["child"]["ivs"]), 5)

    def test_phase_endpoint_is_never_removed_as_a_finished_product(self):
        body = Monster(id="body", species="尼多兰", gender="F", ivs=[31, None, 31, 31, 31, 31], is_alpha=True)
        inventory = [body.to_dict()]
        response = self.generate(inventory, species="尼多王", nature="内敛", target_alpha=True,
                                 ivs=["31", "X", "31", "31", "31", "31"])
        # An incomplete legacy snapshot must not silently discard the hand,
        # even if its old nature-prompt metadata is absent.
        response = deepcopy(response)
        response["plan"]["adaptive_nature"] = False
        for step in response["plan"]["steps"]:
            result = self.complete(response, inventory, step, nature_hit=False)
            self.assertTrue(result["ok"], result)
            inventory, response = result["inventory"], result["response"]
        self.assertTrue(response["plan"]["needs_replan"])
        self.assertIn(response["plan"]["steps"][-1]["child"]["id"], {m["id"] for m in inventory})
        self.assertIn("body", {m["id"] for m in inventory})


if __name__ == "__main__":
    unittest.main()
