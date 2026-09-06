"""Regression: visible 3V donor must never execute an unrelated 2V step."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import App
from execution import ExecutionPlan, ExecutionStep
from execution_view import execution_map
from models import Monster
from species_data import get_species_database
from planner import make_report_with_candidates
from execution import build_execution_plan


def fixture():
    a = Monster(id="a", species="阿利多斯", gender="F", ivs=[None, None, None, None, 31, 31], egg_groups=["虫"])
    b = Monster(id="b", species="凯罗斯", gender="M", ivs=[None, 31, None, None, 31, None], egg_groups=["虫"])
    mother = Monster(id="mother", species="飞天螳螂", gender="F", ivs=[None, None, 31, None, 31, 31], egg_groups=["虫"])
    donor = Monster(id="donor", species="圆丝蛛", gender="M", ivs=[None, 31, None, None, 31, 31], egg_groups=["虫"])
    child = Monster(id="child", species="飞天螳螂", gender="F", ivs=[None, 31, 31, None, 31, 31], egg_groups=["虫"])
    first = ExecutionStep(1, "a", "b", "2V 母阿利多斯", "2V 公凯罗斯", donor, planned_gender="M", item_a="速度护腕", item_b="攻击护腕")
    second = ExecutionStep(2, "donor", "mother", "3V 公圆丝蛛", "3V 母飞天螳螂", child, planned_gender="F", item_a="攻击护腕", item_b="防御护腕")
    plan = ExecutionPlan("active", "飞天螳螂", [first, second], materials={m.id: m.to_dict() for m in (a, b, mother)})
    return plan, [a, b, mother]


def app_fixture():
    plan, inventory = fixture()
    a = App.__new__(App)
    a.active_plan = plan
    a.proposed_plan = ExecutionPlan("unrelated-proposal", "圆丝蛛", [])
    a.plan_view_mode = "active"
    a.displayed_plan_id = plan.id
    a.plan_worker_busy = False
    a.selected_plan_step_number = None
    a.inventory = inventory
    a.species_db = get_species_database()
    a.expanded_completed_sources = set()
    a.plan_candidate_cache = {}
    a.status_var = Mock()
    a.plan_status_var = Mock()
    a.refresh_inventory_tree = Mock()
    a.refresh_plan_status = Mock()
    a.generate_plan = Mock()
    a._restore_plan_target = Mock()
    a.auto_replan_preferred_material_ids = set()
    a.auto_activate_replan_pending = False
    return a


class ExecutionConsistencyTests(unittest.TestCase):
    def test_new_proposal_cannot_change_the_visible_active_step(self):
        a = app_fixture()
        a.plan_map = Mock()
        a.plan_summary_var = Mock()
        a.plan_purchase_var = Mock()
        a.plan_purchase_label = Mock()
        a.plan_view_label = Mock()
        a._set_plan_map_root = Mock()
        a._render_plan_tree(None)
        node = a._set_plan_map_root.call_args.args[0]
        self.assertEqual(node.children[0].title, "步骤 1 · 圆丝蛛")
        self.assertEqual(a.displayed_plan_id, "active")
        self.assertEqual(a._selected_ready_step().child.ivs, [None, 31, None, None, 31, 31])

    def test_proposal_preview_blocks_button_and_node_execution(self):
        a = app_fixture()
        a.plan_view_mode = "proposal"
        with patch("app.messagebox.showwarning"), patch("app.messagebox.showinfo"), patch("app.consume_parents_and_add_child") as consume:
            a.complete_next_step(a.active_plan.steps[0])
            a._activate_plan_step_number(1)
            a._toggle_plan_step_in_progress(1)
        consume.assert_not_called()
        self.assertFalse(a.active_plan.steps[0].in_progress)
        self.assertIsNone(a._selected_ready_step())

    def test_wrong_display_identity_blocks_even_if_step_number_matches(self):
        a = app_fixture()
        a.displayed_plan_id = "other"
        with patch("app.messagebox.showwarning"), patch("app.consume_parents_and_add_child") as consume:
            a.complete_next_step(a.active_plan.steps[0])
        consume.assert_not_called()

    def test_selected_unready_node_never_falls_back_to_other_step(self):
        a = app_fixture()
        a.selected_plan_step_number = 2
        self.assertIsNone(a._selected_ready_step())

    def complete(self, a, answers, actual=None):
        with patch("app.messagebox.askyesno", side_effect=answers) as ask, \
             patch("app.messagebox.askyesnocancel", return_value=actual) as sex, \
             patch("app.messagebox.showinfo"), patch("app.save_active_plan") as saved, \
             patch("app.consume_parents_and_add_child") as consume, \
             patch("app.load_inventory", return_value=[a.active_plan.steps[0].child, a.inventory[-1]]):
            a.complete_next_step(a.active_plan.steps[0])
        return ask, sex, saved, consume

    def test_locked_donor_completes_without_gender_prompt_or_replan(self):
        a = app_fixture()
        ask, sex, saved, consume = self.complete(a, [True])
        sex.assert_not_called()
        a.generate_plan.assert_not_called()
        self.assertEqual(a.active_plan.id, "active")
        self.assertTrue(a.active_plan.steps[0].completed)
        self.assertEqual(a.active_plan.ready_steps, [a.active_plan.steps[1]])
        self.assertIn("圆丝蛛", ask.call_args.args[1])
        self.assertIn("x/31/x/x/31/31", ask.call_args.args[1])
        self.assertIn("2V 母阿利多斯", ask.call_args.args[1])
        self.assertEqual(consume.call_args.args[0], ("a", "b"))

    def test_random_matching_gender_continues_same_plan(self):
        a = app_fixture()
        a.active_plan.steps[0].gender_policy = "random"
        ask, sex, saved, consume = self.complete(a, [True], actual=False)
        sex.assert_called_once()
        a.generate_plan.assert_not_called()
        self.assertFalse(a.active_plan.needs_replan)
        self.assertEqual(a.active_plan.id, "active")

    def test_mismatch_is_saved_but_declining_replan_keeps_paused_graph(self):
        a = app_fixture()
        a.active_plan.steps[0].gender_policy = "random"
        ask, sex, saved, consume = self.complete(a, [True, False], actual=True)
        self.assertEqual(consume.call_args.args[1].gender, "F")
        self.assertTrue(a.active_plan.needs_replan)
        self.assertEqual(a.active_plan.ready_steps, [])
        self.assertEqual(a.active_plan.id, "active")
        a.generate_plan.assert_not_called()
        self.assertTrue(saved.call_args.args[0]["needs_replan"])

    def test_approved_mismatch_search_does_not_clear_or_auto_replace_plan(self):
        a = app_fixture()
        a.active_plan.steps[0].gender_policy = "random"
        self.complete(a, [True, True], actual=True)
        a.generate_plan.assert_called_once()
        self.assertEqual(a.active_plan.id, "active")
        self.assertFalse(a.auto_activate_replan_pending)
        self.assertEqual(a.auto_replan_preferred_material_ids, {"donor"})

    def test_cancel_sex_prompt_does_not_consume_or_mark_completed(self):
        a = app_fixture()
        a.active_plan.steps[0].gender_policy = "random"
        ask, sex, saved, consume = self.complete(a, [True], actual=None)
        consume.assert_not_called()
        saved.assert_not_called()
        self.assertFalse(a.active_plan.steps[0].completed)

    def test_completed_sources_collapse_and_can_expand_without_mutation(self):
        plan, inventory = fixture()
        plan.steps[0].completed = True
        root = execution_map(plan, inventory, set(), get_species_database())
        donor = root.children[0]
        self.assertEqual(donor.children, [])
        self.assertTrue(donor.sources_collapsed)
        expanded = execution_map(plan, inventory, {(plan.id, 1)}, get_species_database())
        history = expanded.children[0].children
        self.assertEqual(len(history), 2)
        self.assertTrue(all("已消耗" in n.title for n in history))
        self.assertTrue(all(not n.actionable and not n.exclude_material_id for n in history))
        self.assertEqual(len(inventory), 3)

    def test_pending_node_does_not_hide_existing_inventory_parents(self):
        plan, inventory = fixture()
        root = execution_map(plan, inventory, set(), get_species_database())
        self.assertEqual(len(root.children[0].children), 2)

    def test_snapshot_restores_history_and_paused_state_across_restart(self):
        plan, inventory = fixture()
        plan.steps[0].completed = True
        plan.needs_replan = True
        plan.replan_reason = "实际性别与下步不符"
        restored = ExecutionPlan.from_dict(plan.to_dict())
        root = execution_map(restored, [], {(plan.id, 1)}, get_species_database())
        self.assertIn("阿利多斯", root.children[0].children[0].title)
        self.assertTrue(restored.needs_replan)
        self.assertFalse(root.actionable)
        self.assertEqual(execution_map(restored, [], set(), get_species_database()).children[0].children, [])

    def test_legacy_plan_renders_without_candidate_snapshot(self):
        plan, inventory = fixture()
        payload = plan.to_dict()
        payload.pop("materials")
        payload.pop("candidate_snapshot")
        restored = ExecutionPlan.from_dict(payload)
        self.assertIsNotNone(execution_map(restored, inventory, set(), get_species_database()))

    def test_legacy_random_donor_locks_when_mother_already_exists(self):
        plan, inventory = fixture()
        plan.steps[0].gender_policy = "random"
        plan.lock_known_counterparts(inventory)
        self.assertEqual(plan.steps[0].gender_policy, "locked")

    def test_stale_suggestion_cannot_replace_live_plan(self):
        a = app_fixture()
        new_plan, _ = fixture()
        new_plan.id = "proposal"
        a.proposed_plan = new_plan
        a.inventory = []
        with patch("app.messagebox.showwarning") as warning, patch("app.save_active_plan") as save:
            a.activate_best_plan()
        warning.assert_called_once()
        save.assert_not_called()
        self.assertEqual(a.active_plan.id, "active")

    def test_scizor_maternal_and_donor_steps_have_locked_genders(self):
        _, inventory = fixture()
        report, candidates = make_report_with_candidates(inventory, "巨钳螳螂", "", "固执", "31/31/31/x/31/31", ["虫"], intermediate_gender_strategy="智能锁定")
        self.assertTrue(candidates, report)
        plan = build_execution_plan(candidates[0])
        for step in plan.steps:
            self.assertEqual(step.gender_policy, "locked")
            if step.child.species == "飞天螳螂":
                self.assertEqual(step.expected_gender, "F")
        self.assertTrue(plan.materials)
        self.assertTrue(plan.candidate_snapshot)

    def test_restart_uses_full_target_not_a_lower_tier_nature_hand(self):
        a = app_fixture()
        plan = a.active_plan
        plan.target_nature = "固执"
        plan.adaptive_nature = True
        plan.candidate_snapshot = {"target_ivs": [31, 31, 31, None, 31, 31]}
        plan.planning_options = {"target_allow_ditto_var": True}
        for name in ("target_species_var", "target_nature_var", "target_lock_nature_var", "target_lock_gender_var",
                     "target_gender_var", "target_alpha_var", "target_hidden_ability_var", "target_egg_moves_var",
                     "target_iv_var", "target_intermediate_gender_strategy_var", "target_allow_ditto_var"):
            setattr(a, name, Mock())
        a.target_iv_vars = [Mock() for _ in range(6)]
        App._restore_plan_target(a, plan)
        a.target_iv_var.set.assert_called_once_with("31/31/31/x/31/31")
        a.target_nature_var.set.assert_called_once_with("固执")
        a.target_allow_ditto_var.set.assert_called_once_with(True)

    def test_centering_uses_full_scrollregion_width(self):
        from mind_map import BreedingMindMap, MindMapNode
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.root_node = MindMapNode(key="root", title="root")
        view.positions = {"root": (1330, 34)}
        view.zoom = 1
        view.update_idletasks = Mock()
        view.canvas = Mock()
        view.canvas.cget.return_value = "0 0 3000 1200"
        view.canvas.winfo_width.return_value = 1000
        view._center_on_root()
        view.canvas.xview_moveto.assert_called_once_with(1 / 3)


if __name__ == "__main__":
    unittest.main()
