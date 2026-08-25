from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from execution import ExecutionPlan, ExecutionStep, build_execution_plan
from models import Monster
from planner import make_report_with_candidates
from storage import consume_parents_and_add_child, load_inventory, save_inventory, undo_last_consumption


class StorageExecutionTests(unittest.TestCase):
    def test_execution_plan_stops_only_when_the_current_step_needs_purchase(self) -> None:
        ready = ExecutionStep(
            number=1,
            parent_a_id="inventory-a",
            parent_b_id="inventory-b",
            parent_a_label="库存 A",
            parent_b_label="库存 B",
            child=Monster(id="child-1", species="拉鲁拉丝", gender="F", ivs=[31, 31, 31, None, None, None]),
        )
        blocked = ExecutionStep(
            number=2,
            parent_a_id="child-1",
            parent_b_id="buy:missing",
            parent_a_label="步骤 1 子代",
            parent_b_label="交易行补购",
            child=Monster(id="child-2", species="拉鲁拉丝", gender="F", ivs=[31, 31, 31, 31, None, None]),
        )
        plan = ExecutionPlan(
            id="partial-plan",
            target_species="拉鲁拉丝",
            steps=[ready, blocked],
            purchase_requirements=["交易行补购"],
            target_nature="固执",
            adaptive_nature=True,
        )

        self.assertFalse(plan.next_step.requires_purchase)
        self.assertIn("性格机会", plan.status_text())
        ready.completed = True
        self.assertTrue(plan.next_step.requires_purchase)
        self.assertIn("遇到缺料节点", plan.status_text())

        restored = ExecutionPlan.from_dict(plan.to_dict())
        self.assertEqual(restored.target_nature, "固执")
        self.assertTrue(restored.adaptive_nature)

    def test_candidate_becomes_id_based_execution_steps(self) -> None:
        parent_a = Monster(id="a", species="拉鲁拉丝", gender="F", ivs=[31, 1, 1, 1, 1, 1], egg_groups=["人型"])
        parent_b = Monster(id="b", species="凯西", gender="M", ivs=[1, 31, 1, 1, 1, 1], egg_groups=["人型"])
        _report, candidates = make_report_with_candidates(
            [parent_a, parent_b], "拉鲁拉丝", "F", "", "31/31/x/x/x/x", []
        )
        plan = build_execution_plan(candidates[0])
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual({plan.steps[0].parent_a_id, plan.steps[0].parent_b_id}, {"a", "b"})
        self.assertFalse(plan.purchase_requirements)

    def test_smart_gender_strategy_randomizes_low_v_first_branches(self) -> None:
        inventory = [
            Monster(id="a", species="拉鲁拉丝", gender="F", ivs=[31, 1, 1, 1, 1, 1], egg_groups=["人型"]),
            Monster(id="b", species="凯西", gender="M", ivs=[2, 31, 2, 2, 2, 2], egg_groups=["人型"]),
            Monster(id="c", species="拉鲁拉丝", gender="F", ivs=[3, 31, 3, 3, 3, 3], egg_groups=["人型"]),
            Monster(id="d", species="腕力", gender="M", ivs=[4, 4, 31, 4, 4, 4], egg_groups=["人型"]),
        ]
        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            intermediate_gender_strategy="智能锁定",
        )

        plan = build_execution_plan(candidates[0])

        self.assertEqual(plan.gender_strategy, "smart")
        self.assertEqual(plan.steps[-1].gender_policy, "locked")
        self.assertTrue(any(step.gender_policy == "random" for step in plan.steps[:-1]))
        self.assertIn("记录实际性别并重算", plan.status_text())

    def test_smart_strategy_locks_only_counterpart_of_existing_child(self) -> None:
        inventory = [
            Monster(id="ready", species="拉鲁拉丝", gender="F", ivs=[31, 31, 1, 1, 1, 1], egg_groups=["人型"]),
            Monster(id="atk", species="拉鲁拉丝", gender="F", ivs=[2, 31, 2, 2, 2, 2], egg_groups=["人型"]),
            Monster(id="def", species="腕力", gender="M", ivs=[3, 3, 31, 3, 3, 3], egg_groups=["人型"]),
        ]
        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            intermediate_gender_strategy="smart",
        )

        plan = build_execution_plan(candidates[0])

        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].gender_policy, "locked")
        self.assertEqual(plan.steps[0].expected_gender, "M")

    def test_gender_override_and_schema_round_trip(self) -> None:
        step = ExecutionStep(
            number=1,
            parent_a_id="a",
            parent_b_id="b",
            parent_a_label="A",
            parent_b_label="B",
            child=Monster(id="child", species="拉鲁拉丝", gender="F", ivs=[31, 31, None, None, None, None]),
            planned_gender="F",
            gender_policy="random",
            gender_override="M",
        )
        plan = ExecutionPlan(
            id="gender-plan",
            target_species="拉鲁拉丝",
            steps=[step],
            target_gender="",
            gender_strategy="smart",
        )

        restored = ExecutionPlan.from_dict(plan.to_dict())

        self.assertEqual(restored.gender_strategy, "smart")
        self.assertEqual(restored.steps[0].gender_override, "M")
        self.assertEqual(restored.steps[0].expected_gender, "M")
        self.assertTrue(restored.steps[0].outcome_changes_plan)

    def test_late_nature_plan_marks_unstoned_steps_as_adaptive(self) -> None:
        parent_a = Monster(id="a", species="拉鲁拉丝", gender="F", ivs=[31, 31, 1, 1, 1, 1], egg_groups=["人型"])
        parent_b = Monster(id="b", species="拉鲁拉丝", gender="M", ivs=[1, 31, 31, 1, 1, 1], egg_groups=["人型"])
        _report, candidates = make_report_with_candidates(
            [parent_a, parent_b],
            "拉鲁拉丝",
            "F",
            "固执",
            "31/31/31/31/31/x",
            ["人型"],
            allow_ditto=False,
            nature_strategy="late",
        )

        plan = build_execution_plan(candidates[0])

        self.assertTrue(plan.adaptive_nature)
        self.assertEqual(plan.target_nature, "固执")
        self.assertFalse(plan.steps[0].requires_purchase)
        self.assertFalse(plan.steps[0].uses_everstone)

    def test_execution_child_keeps_alpha_only_for_alpha_plan(self) -> None:
        parent_a = Monster(
            id="alpha-a", species="拉鲁拉丝", gender="F", ivs=[31, 31, 1, 1, 1, 1],
            egg_groups=["人型"], is_alpha=True,
        )
        parent_b = Monster(
            id="alpha-b", species="凯西", gender="M", ivs=[1, 31, 31, 1, 1, 1],
            egg_groups=["人型"], is_alpha=True,
        )
        _report, candidates = make_report_with_candidates(
            [parent_a, parent_b], "拉鲁拉丝", "F", "", "31/31/31/x/x/x", [], True
        )

        plan = build_execution_plan(candidates[0])

        self.assertTrue(plan.steps[-1].child.is_alpha)

    def test_execution_preserves_actual_neutral_nature(self) -> None:
        parent_a = Monster(
            id="neutral-a", species="拉鲁拉丝", gender="F", nature="认真",
            ivs=[31, 1, 1, 1, 1, 1], egg_groups=["人型"],
        )
        parent_b = Monster(
            id="neutral-b", species="拉鲁拉丝", gender="M",
            ivs=[1, 31, 1, 1, 1, 1], egg_groups=["人型"],
        )
        _report, candidates = make_report_with_candidates(
            [parent_a, parent_b], "拉鲁拉丝", "F", "无修正（任一）", "31/31/x/x/x/x", []
        )
        plan = build_execution_plan(candidates[0])
        self.assertEqual(plan.steps[-1].child.nature, "认真")

    def test_execution_records_hatched_form_and_final_evolution_target(self) -> None:
        parent_a = Monster(
            id="skorupi", species="钳尾蝎", gender="F",
            ivs=[31, 1, 1, 1, 1, 1], egg_groups=["虫", "水中3"],
        )
        parent_b = Monster(
            id="drapion", species="龙王蝎", gender="M",
            ivs=[1, 31, 1, 1, 1, 1], egg_groups=["虫", "水中3"],
        )
        _report, candidates = make_report_with_candidates(
            [parent_a, parent_b], "龙王蝎", "F", "", "31/31/x/x/x/x", []
        )

        plan = build_execution_plan(candidates[0])

        self.assertEqual(plan.target_species, "龙王蝎")
        self.assertEqual(plan.steps[-1].child.species, "钳尾蝎")
        self.assertIn("进化为最终目标 龙王蝎", plan.steps[-1].child.notes)

    def test_execution_preserves_all_six_exact_target_iv_values(self) -> None:
        parent_a = Monster(
            id="exact-f", species="黑眼鳄", gender="F",
            ivs=[31, 31, 31, 16, 31, 7], egg_groups=["陆上"],
        )
        parent_b = Monster(
            id="exact-m", species="混混鳄", gender="M",
            ivs=[8, 31, 31, 16, 31, 31], egg_groups=["陆上"],
        )
        _report, candidates = make_report_with_candidates(
            [parent_a, parent_b], "流氓鳄", "F", "", "31/31/31/16/31/31", ["陆上"]
        )

        plan = build_execution_plan(candidates[0])

        self.assertEqual(plan.steps[-1].child.ivs, [31, 31, 31, 16, 31, 31])
        self.assertEqual(plan.steps[-1].child.species, "黑眼鳄")

    def test_consumption_is_atomic_and_undoable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}):
            parent_a = Monster(id="parent-a", species="拉鲁拉丝", gender="F", ivs=[31, 1, 1, 1, 1, 1])
            parent_b = Monster(id="parent-b", species="凯西", gender="M", ivs=[1, 31, 1, 1, 1, 1])
            child = Monster(id="child", species="拉鲁拉丝", gender="F", ivs=[31, 31, None, None, None, None])
            save_inventory([parent_a, parent_b])

            consume_parents_and_add_child((parent_a.id, parent_b.id), child, "plan-1", 1)
            self.assertEqual([item.id for item in load_inventory()], ["child"])

            restored = undo_last_consumption()
            self.assertIsNotNone(restored)
            self.assertEqual({item.id for item in load_inventory()}, {"parent-a", "parent-b"})
            self.assertTrue(Path(temp_dir, "PokeMMO-Breeder-Helper", "inventory.db").exists())


if __name__ == "__main__":
    unittest.main()
