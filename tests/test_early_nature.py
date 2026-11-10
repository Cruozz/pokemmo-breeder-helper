import json
import unittest
from test_mobile_execution import bridge


class EarlyNatureTests(unittest.TestCase):
    def assert_nature_lineage(self, plan, child_id, nature):
        holders = {child_id}
        uses = 0
        for step in plan['steps']:
            for side in ('a', 'b'):
                if step['parent_' + side + '_id'] in holders:
                    self.assertEqual(step['item_' + side], '不变之石', step)
                    self.assertEqual(step['child']['nature'], nature, step)
                    holders.add(step['child']['id'])
                    uses += 1
        self.assertGreater(uses, 0)
        self.assertIn(plan['steps'][-1]['child']['id'], holders)

    def test_early_hits_for_both_sexes_at_each_requested_tier(self):
        for count in (3, 4, 5):
            for gender in ('F', 'M'):
                for ditto in (False, True):
                    with self.subTest(target=count, gender=gender, ditto=ditto):
                        self.check_early_hit(count, gender, ditto)

    def check_early_hit(self, count, gender, ditto):
        inventory = []
        selected = (0, 1, 2, 4, 5)[:count]
        request = dict(species='黑暗鸦', nature='固执',
                       ivs=['31' if i in selected else 'X' for i in range(6)],
                       allow_ditto=ditto, max_purchase_v=max(1, count-2))
        response = json.loads(bridge.generate_plan('[]', json.dumps(request)))
        self.assertTrue(response['ok'], response)
        chosen = next(s for s in response['plan']['steps']
                      if s['can_record_early_nature'] and s['child']['gender'] == gender)
        for step in list(response['plan']['steps']):
            hit = step['number'] == chosen['number']
            result = json.loads(bridge.complete_step(json.dumps(inventory), json.dumps(response), json.dumps(dict(
                number=step['number'], gender=step['planned_gender'], nature_hit=True if hit else None))))
            self.assertTrue(result['ok'], result)
            inventory, response = result['inventory'], result['response']
            if hit:
                break
        self.assertTrue(response['plan']['needs_replan'])
        child = next(m for m in inventory if m['id'] == chosen['child']['id'])
        self.assertEqual(child['nature'], '固执')
        self.assertEqual(child['nature_attempt_result'], 'hit')
        self.assertEqual(child['nature_attempt_level'], count-1)
        self.assertEqual(child['gender'], gender)
        replanned = json.loads(bridge.generate_plan(json.dumps(inventory), json.dumps(response['plan']['planning_options'])))
        self.assertTrue(replanned['ok'], replanned)
        plan = replanned['plan']
        self.assertEqual(plan['nature_phase'], 'finish')
        self.assert_nature_lineage(plan, child['id'], '固执')
        final = plan['steps'][-1]
        self.assertIn(child['id'], (final['parent_a_id'], final['parent_b_id']))
        partner_id = final['parent_b_id'] if final['parent_a_id'] == child['id'] else final['parent_a_id']
        partner = next(s['child'] for s in plan['steps'] if s['child']['id'] == partner_id)
        self.assertEqual(partner['gender'], 'F' if gender == 'M' else 'M')
        self.assertEqual(sum(v == 31 for v in partner['ivs']), count)
        if gender == 'M':
            self.assertEqual(partner['species'], '黑暗鸦')
            mother = next(m for m in inventory if m['gender'] == 'F')
            self.assertTrue(any(mother['id'] in (s['parent_a_id'], s['parent_b_id']) for s in plan['steps']))
        # A packaged mobile route and the desktop entry point must agree.
        from models import Monster
        from planner import make_report_with_candidates
        from execution import build_execution_plan
        _, candidates = make_report_with_candidates(
            [Monster.from_dict(m) for m in inventory], '黑暗鸦', '', '固执',
            '/'.join(request['ivs']), [], allow_ditto=ditto,
            preferred_material_ids={child['id']}, max_purchase_v=max(1, count-2))
        desktop = build_execution_plan(candidates[0])
        self.assertEqual([(s.child.species, s.child.gender, s.child.ivs, s.child.nature, s.item_a, s.item_b) for s in desktop.steps],
                         [(s['child']['species'], s['child']['gender'], s['child']['ivs'], s['child']['nature'], s['item_a'], s['item_b']) for s in plan['steps']])
        for step in list(plan['steps']):
            result = json.loads(bridge.complete_step(json.dumps(inventory), json.dumps(replanned), json.dumps(dict(
                number=step['number'], gender=step['planned_gender']))))
            self.assertTrue(result['ok'], result)
            inventory, replanned = result['inventory'], result['response']
            self.assertFalse(replanned['plan']['needs_replan'])
        self.assertEqual(inventory, [])
        self.assertEqual(final['child']['species'], '黑暗鸦')
        self.assertEqual(sum(v == 31 for v in final['child']['ivs']), count)

    def test_recorded_male_is_preserved_across_strategies_and_reload(self):
        from models import Monster
        mother = Monster(id='body', species='黑暗鸦', gender='F', ivs=[31,31,31,None,31,None])
        male = Monster(id='early-hit', species='波波', gender='M', nature='固执',
                       ivs=[None,31,31,None,31,31], nature_attempt_result='hit')
        for strategy in ('inventory', 'steps', 'cost'):
            for preferred in ([], [male.id]):
                with self.subTest(strategy=strategy, preferred=preferred):
                    result = json.loads(bridge.generate_plan(json.dumps([mother.to_dict(),male.to_dict()]), json.dumps(dict(
                        species='黑暗鸦', nature='固执', ivs=['31','31','31','X','31','31'],
                        strategy=strategy, max_purchase_v=3, preferred_material_ids=preferred))))
                    self.assertTrue(result['ok'], result)
                    self.assert_nature_lineage(result['plan'], male.id, '固执')

    def test_recorded_nature_guard_survives_child_and_snapshot(self):
        from chain_planner import ChainState, SpeciesProfile, _forced_child
        from models import Monster
        kwargs = dict(species='黑暗鸦', egg_groups=('飞行',), mask=7, is_alpha=False,
                      generation=0, breeds=0, braces=0, everstones=0)
        male = ChainState(**kwargs, gender='M', has_nature=True, nature='固执',
                          used_ids=frozenset({'hit'}), preserve_nature=True)
        female = ChainState(**kwargs, gender='F', has_nature=False, nature='', used_ids=frozenset({'body'}))
        profile = SpeciesProfile('黑暗鸦', '黑暗鸦', ('飞行',))
        self.assertIsNone(_forced_child(female, male, profile, 'F'))
        child = _forced_child(female, male, profile, 'F', everstone_b=True)
        self.assertIsNotNone(child)
        restored = ChainState.from_dict(child.to_dict())
        self.assertTrue(restored.preserve_nature)
        other = ChainState(**kwargs, gender='M', has_nature=False, nature='', used_ids=frozenset({'other'}))
        self.assertIsNone(_forced_child(restored, other, profile, 'F'))
        self.assertIsNotNone(_forced_child(restored, other, profile, 'F', everstone_a=True))

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
