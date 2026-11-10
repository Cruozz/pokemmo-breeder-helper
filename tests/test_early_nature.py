import json
import unittest
from test_mobile_execution import bridge


class EarlyNatureTests(unittest.TestCase):
    def test_early_hits_for_both_sexes_at_each_requested_tier(self):
        for count in (3, 4, 5):
            for gender in ('F', 'M'):
                with self.subTest(target=count, gender=gender):
                    inventory = []
                    request = dict(species='索罗亚克', nature='内敛', ivs=['31'] * count + ['X'] * (6-count), allow_ditto=False)
                    response = json.loads(bridge.generate_plan('[]', json.dumps(request)))
                    self.assertTrue(response['ok'], response)
                    candidates = [s for s in response['plan']['steps'] if s['can_record_early_nature'] and s['child']['gender'] == gender]
                    self.assertTrue(candidates, response)
                    chosen = candidates[0]['number']
                    for step in response['plan']['steps']:
                        if step['number'] > chosen:
                            break
                        hit = step['number'] == chosen
                        result = json.loads(bridge.complete_step(json.dumps(inventory), json.dumps(response), json.dumps(dict(
                            number=step['number'], gender=step['planned_gender'], nature_hit=True if hit else None))))
                        self.assertTrue(result['ok'], result)
                        inventory, response = result['inventory'], result['response']
                    self.assertTrue(response['plan']['needs_replan'])
                    child = next(m for m in inventory if m['id'] == candidates[0]['child']['id'])
                    self.assertEqual(child['nature'], '内敛')
                    self.assertEqual(child['nature_attempt_result'], 'hit')
                    self.assertEqual(child['nature_attempt_level'], count-1)
                    self.assertEqual(child['gender'], gender)
                    replanned = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(response['plan']['planning_options'])))
                    self.assertTrue(replanned['ok'], replanned)
                    self.assertEqual(replanned['plan']['nature_phase'], 'finish')
                    self.assertTrue(any(child['id'] in {s['parent_a_id'], s['parent_b_id']} for s in replanned['plan']['steps']))

    def test_forged_lower_tier_hit_is_rejected_without_consumption(self):
        response = json.loads(bridge.generate_plan('[]', json.dumps(dict(species='索罗亚克', nature='内敛', ivs=['31']*5+['X'], allow_ditto=False))))
        first = response['plan']['steps'][0]
        self.assertFalse(first['can_record_early_nature'])
        result = json.loads(bridge.complete_step('[]', json.dumps(response), json.dumps(dict(number=first['number'], nature_hit=True))))
        self.assertFalse(result['ok'])
        self.assertFalse(first['completed'])

    def test_locked_or_unspecified_nature_does_not_offer_early_hit(self):
        from execution import ExecutionPlan, ExecutionStep
        from models import Monster
        step = ExecutionStep(1, 'a', 'b', 'a', 'b', Monster(id='child', gender='M', ivs=[31]*4+[None]*2), nature_check_role='ignore')
        plan = ExecutionPlan('test', '索罗亚', [step], target_nature='内敛', adaptive_nature=True, target_iv_count=5, maternal_nature_min_ivs=5)
        self.assertTrue(plan.can_record_early_nature(step))
        step.item_a = '不变之石'
        self.assertFalse(plan.can_record_early_nature(step))
        step.item_a = ''
        plan.target_nature = ''
        self.assertFalse(plan.can_record_early_nature(step))


class DesktopEarlyNatureTests(unittest.TestCase):
    def test_explicit_hit_saves_once_and_preserves_old_route_until_approval(self):
        from unittest.mock import patch
        from test_execution_consistency import app_fixture
        app = app_fixture()
        plan = app.active_plan
        plan.adaptive_nature = True
        plan.target_nature = '内敛'
        plan.target_iv_count = 4
        plan.maternal_nature_min_ivs = 4
        step = plan.steps[0]
        self.assertTrue(plan.can_record_early_nature(step))
        with patch('app.messagebox.askyesno', return_value=True), \
             patch('app.messagebox.askyesnocancel') as normal_question, \
             patch('app.save_active_plan'), \
             patch('app.consume_parents_and_add_child') as consume, \
             patch('app.load_inventory', return_value=[step.child]):
            app.complete_next_step(step, early_nature_hit=True)
        normal_question.assert_not_called()
        consume.assert_called_once()
        self.assertEqual(consume.call_args.args[1].nature, '内敛')
        self.assertEqual(consume.call_args.args[1].gender, 'M')
        self.assertTrue(plan.needs_replan)
        self.assertTrue(step.completed)
        self.assertIs(app.active_plan, plan)
        self.assertFalse(app.auto_activate_replan_pending)
        self.assertEqual(app.auto_replan_preferred_material_ids, {step.child.id})
        app.generate_plan.assert_called_once()
