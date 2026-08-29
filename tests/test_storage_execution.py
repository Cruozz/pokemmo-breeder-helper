from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from execution import ExecutionPlan, ExecutionStep, build_execution_plan
from models import Monster
from planner import make_report_with_candidates
from storage import (
    consume_parents_and_add_child,
    delete_inventory_records,
    find_high_confidence_duplicate_groups,
    load_accounts,
    load_inventory,
    save_accounts,
    save_inventory,
    undo_last_inventory_deletion,
    undo_last_consumption,
)


class StorageExecutionTests(unittest.TestCase):
    def test_bulk_inventory_delete_is_atomic_and_undoable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}):
            first = Monster(id="delete-a", species="凯西", gender="M", ivs=[31, 1, 1, 1, 1, 1])
            second = Monster(id="delete-b", species="腕力", gender="F", ivs=[1, 31, 1, 1, 1, 1])
            keep = Monster(id="keep", species="拉鲁拉丝", gender="F", ivs=[1, 1, 31, 1, 1, 1])
            save_inventory([first, second, keep])

            deleted = delete_inventory_records([first.id, second.id])

            self.assertEqual([item.id for item in deleted], [first.id, second.id])
            self.assertEqual([item.id for item in load_inventory()], [keep.id])

            restored = undo_last_inventory_deletion()

            self.assertEqual({item.id for item in restored}, {first.id, second.id})
            self.assertEqual({item.id for item in load_inventory()}, {first.id, second.id, keep.id})
            self.assertEqual(undo_last_inventory_deletion(), [])

    def test_sibling_execution_steps_are_ready_in_parallel(self) -> None:
        left = ExecutionStep(
            number=1,
            parent_a_id="left-a",
            parent_b_id="left-b",
            parent_a_label="左 A",
            parent_b_label="左 B",
            child=Monster(id="left-child", species="拉鲁拉丝", gender="F", ivs=[31, 31, None, None, None, None]),
        )
        right = ExecutionStep(
            number=2,
            parent_a_id="right-a",
            parent_b_id="right-b",
            parent_a_label="右 A",
            parent_b_label="右 B",
            child=Monster(id="right-child", species="拉鲁拉丝", gender="M", ivs=[None, None, 31, 31, None, None]),
        )
        merge = ExecutionStep(
            number=3,
            parent_a_id=left.child.id,
            parent_b_id=right.child.id,
            parent_a_label="左支子代",
            parent_b_label="右支子代",
            child=Monster(id="merged", species="拉鲁拉丝", gender="F", ivs=[31, 31, 31, 31, None, None]),
        )
        plan = ExecutionPlan(id="parallel", target_species="拉鲁拉丝", steps=[left, right, merge])

        self.assertEqual([step.number for step in plan.ready_steps], [1, 2])
        self.assertTrue(plan.is_step_ready(right))
        self.assertFalse(plan.is_step_ready(merge))
        self.assertIn("可并行执行节点", plan.status_text())

        right.completed = True
        self.assertEqual([step.number for step in plan.ready_steps], [1])
        self.assertFalse(plan.is_step_ready(merge))

        left.completed = True
        self.assertEqual([step.number for step in plan.ready_steps], [3])
        self.assertTrue(plan.is_step_ready(merge))

    def test_duplicate_check_requires_all_five_visible_fields_to_match(self) -> None:
        first = Monster(
            id="first",
            species="长耳兔",
            gender="F",
            nature="固执",
            ivs=[31, 20, 31, 12, 31, 31],
            moves=["飞膝踢", "报恩"],
            account="主账号",
        )
        same = Monster(
            id="same",
            species="长耳兔",
            gender="F",
            nature="固执",
            ivs=[31, 20, 31, 12, 31, 31],
            moves=["飞膝踢", "报恩"],
            account="仓库小号",
        )
        different_move = Monster(
            id="different",
            species="长耳兔",
            gender="F",
            nature="固执",
            ivs=[31, 20, 31, 12, 31, 31],
            moves=["飞膝踢", "电光一闪"],
        )

        groups = find_high_confidence_duplicate_groups([first, same, different_move])

        self.assertEqual([[monster.id for monster in group] for group in groups], [["first", "same"]])

    def test_duplicate_check_ignores_incomplete_ocr_rows(self) -> None:
        first = Monster(id="first", species="凯西", gender="M", nature="胆小", ivs=[31, None, 1, 2, 3, 4], moves=[])
        second = Monster(id="second", species="凯西", gender="M", nature="胆小", ivs=[31, None, 1, 2, 3, 4], moves=[])

        self.assertEqual(find_high_confidence_duplicate_groups([first, second]), [])

    def test_duplicate_check_catches_one_missing_fourth_move_from_ocr(self) -> None:
        three_moves = Monster(
            id="three",
            species="青铜钟",
            gender="N",
            nature="浮躁",
            ivs=[24, 23, 31, 31, 19, 14],
            moves=["重磅冲撞", "日光束", "气象球"],
        )
        four_moves = Monster(
            id="four",
            species=" 青铜钟 ",
            gender="N",
            nature="浮躁",
            ivs=[24, 23, 31, 31, 19, 14],
            moves=["大晴天", "气象球", "日光束", "重磅冲撞"],
        )

        groups = find_high_confidence_duplicate_groups([three_moves, four_moves])

        self.assertEqual([[monster.id for monster in group] for group in groups], [["four", "three"]])

    def test_empty_alt_account_names_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}):
            save_accounts(["主账号", "仓库小号A", "仓库小号B"])
            self.assertEqual(load_accounts(), ["主账号", "仓库小号A", "仓库小号B"])

    def test_purchase_step_becomes_actionable_without_inventory_import(self) -> None:
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
        self.assertTrue(plan.is_step_ready(blocked))
        self.assertIn("无需扫描入库", plan.status_text())

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
        self.assertEqual(plan.steps[0].child.account, "主账号")

    def test_cross_account_parents_leave_child_account_for_confirmation(self) -> None:
        parent_a = Monster(
            id="account-a",
            species="拉鲁拉丝",
            gender="F",
            ivs=[31, 1, 1, 1, 1, 1],
            egg_groups=["人型"],
            account="小号A",
        )
        parent_b = Monster(
            id="account-b",
            species="凯西",
            gender="M",
            ivs=[1, 31, 1, 1, 1, 1],
            egg_groups=["人型"],
            account="小号B",
        )
        _report, candidates = make_report_with_candidates(
            [parent_a, parent_b], "拉鲁拉丝", "F", "", "31/31/x/x/x/x", ["人型"]
        )

        plan = build_execution_plan(candidates[0])

        self.assertEqual(plan.steps[-1].child.account, "待确认")
        self.assertIn("小号A", " ".join((plan.steps[-1].parent_a_label, plan.steps[-1].parent_b_label)))
        self.assertIn("小号B", " ".join((plan.steps[-1].parent_a_label, plan.steps[-1].parent_b_label)))

    def test_execution_child_preserves_hidden_ability_and_selected_move(self) -> None:
        parent_a = Monster(
            id="ha-move-f",
            species="拉鲁拉丝",
            gender="F",
            ivs=[31, 1, 1, 1, 1, 1],
            egg_groups=["人型"],
            has_hidden_ability=True,
            moves=["定身法"],
        )
        parent_b = Monster(
            id="attack-m",
            species="凯西",
            gender="M",
            ivs=[1, 31, 1, 1, 1, 1],
            egg_groups=["人型"],
        )
        _report, candidates = make_report_with_candidates(
            [parent_a, parent_b],
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型"],
            need_hidden_ability=True,
            target_moves=("定身法",),
        )

        plan = build_execution_plan(candidates[0])

        self.assertTrue(plan.steps[-1].child.has_hidden_ability)
        self.assertIn("定身法", plan.steps[-1].child.moves)

    def test_smart_gender_strategy_locks_maternal_and_direct_donor_spines(self) -> None:
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
        self.assertTrue(all(step.gender_policy == "locked" for step in plan.steps))

    def test_child_feeding_ditto_does_not_require_gender_confirmation(self) -> None:
        inventory = [
            Monster(id="bridge-f", species="晃晃斑", gender="F", ivs=[31, 1, 1, 1, 1, 31], egg_groups=["陆上"]),
            Monster(id="bridge-m", species="长毛狗", gender="M", ivs=[31, 31, 1, 1, 1, 1], egg_groups=["陆上"]),
            Monster(id="ditto", species="百变怪", gender="N", ivs=[31, 1, 1, 1, 31, 31]),
            Monster(id="target", species="索罗亚", gender="F", ivs=[1, 31, 31, 1, 31, 31], egg_groups=["陆上"]),
        ]
        _report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/31/x/31/31",
            ["陆上"],
            allow_ditto=True,
            intermediate_gender_strategy="smart",
        )

        plan = build_execution_plan(candidates[0])
        ditto_feed = next(step for step in plan.steps if step.gender_policy == "irrelevant")

        self.assertFalse(ditto_feed.outcome_changes_plan)
        self.assertIn("无需确认性别", ditto_feed.gender_instruction)

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
            in_progress=True,
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
        self.assertTrue(restored.steps[0].in_progress)
        self.assertTrue(restored.is_step_ready(restored.steps[0]))
        self.assertIn("孵化中", restored.status_text())

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

    def test_adaptive_nature_only_checks_the_final_two_iv_tiers(self) -> None:
        def step(number: int, iv_count: int) -> ExecutionStep:
            return ExecutionStep(
                number=number,
                parent_a_id=f"child-{number - 1}" if number > 1 else f"a-{number}",
                parent_b_id=f"b-{number}",
                parent_a_label="父本 A",
                parent_b_label="父本 B",
                child=Monster(
                    id=f"child-{number}",
                    species="索罗亚",
                    gender="F",
                    ivs=[31] * iv_count + [None] * (6 - iv_count),
                ),
            )

        steps = [step(index, index + 1) for index in range(1, 5)]  # 2V、3V、4V、5V
        plan = ExecutionPlan(
            id="nature-checkpoint",
            target_species="索罗亚克",
            steps=steps,
            target_nature="固执",
            adaptive_nature=True,
            target_iv_count=5,
        )

        self.assertEqual(plan.nature_check_min_ivs, 4)
        self.assertFalse(plan.should_check_nature(steps[0]))
        self.assertFalse(plan.should_check_nature(steps[1]))
        self.assertTrue(plan.should_check_nature(steps[2]))
        self.assertTrue(plan.should_check_nature(steps[3]))
        self.assertTrue(plan.is_final_step(steps[3]))
        self.assertFalse(plan.is_final_step(steps[2]))

        restored = ExecutionPlan.from_dict(plan.to_dict())
        self.assertEqual(restored.target_iv_count, 5)
        self.assertEqual(restored.nature_check_min_ivs, 4)

    def test_explicit_nature_roles_separate_maternal_threshold_from_lower_hand_gamble(self) -> None:
        ignored_low = ExecutionStep(
            number=1,
            parent_a_id="a",
            parent_b_id="b",
            parent_a_label="A",
            parent_b_label="B",
            child=Monster(id="low", species="索罗亚", gender="F", ivs=[31, 31, None, None, None, None]),
            nature_check_role="ignore",
        )
        maternal_checkpoint = ExecutionStep(
            number=2,
            parent_a_id="low",
            parent_b_id="c",
            parent_a_label="低档母体",
            parent_b_label="C",
            child=Monster(id="mother-4v", species="索罗亚", gender="F", ivs=[31, 31, 31, None, 31, None]),
            nature_check_role="maternal",
        )
        deliberate_lower_hand = ExecutionStep(
            number=3,
            parent_a_id="d",
            parent_b_id="e",
            parent_a_label="D",
            parent_b_label="E",
            child=Monster(id="hand-3v", species="陆上组兼容素材", gender="F", ivs=[31, 31, None, None, 31, None]),
            nature_check_role="nature_hand",
        )
        plan = ExecutionPlan(
            id="staged-nature",
            target_species="索罗亚克",
            steps=[ignored_low, maternal_checkpoint, deliberate_lower_hand],
            target_nature="固执",
            adaptive_nature=True,
            target_iv_count=5,
            nature_phase="gamble_lower",
            nature_target_key="route-key",
            nature_attempt_level=3,
        )

        self.assertFalse(plan.should_check_nature(ignored_low))
        self.assertTrue(plan.should_check_nature(maternal_checkpoint))
        self.assertTrue(plan.should_check_nature(deliberate_lower_hand))
        ignored_low.completed = True
        maternal_checkpoint.completed = True
        self.assertIn("主动赌性格手", plan.status_text())

        restored = ExecutionPlan.from_dict(plan.to_dict())
        self.assertEqual(restored.nature_phase, "gamble_lower")
        self.assertEqual(restored.nature_target_key, "route-key")
        self.assertEqual(restored.nature_attempt_level, 3)
        self.assertEqual(restored.steps[-1].nature_check_role, "nature_hand")

    def test_adaptive_nature_threshold_scales_with_the_requested_iv_count(self) -> None:
        four_v_plan = ExecutionPlan(
            id="four-v",
            target_species="索罗亚",
            target_nature="固执",
            adaptive_nature=True,
            target_iv_count=4,
        )
        three_v_child = ExecutionStep(
            number=1,
            parent_a_id="a",
            parent_b_id="b",
            parent_a_label="A",
            parent_b_label="B",
            child=Monster(id="3v", species="索罗亚", ivs=[31, 31, 31, None, None, None]),
        )
        self.assertEqual(four_v_plan.nature_check_min_ivs, 3)
        self.assertTrue(four_v_plan.should_check_nature(three_v_child))

        six_exact_plan = ExecutionPlan(
            id="six-exact",
            target_species="黑眼鳄",
            target_nature="固执",
            adaptive_nature=True,
            target_iv_count=6,
        )
        four_exact_child = ExecutionStep(
            number=1,
            parent_a_id="c",
            parent_b_id="d",
            parent_a_label="C",
            parent_b_label="D",
            child=Monster(id="4e", species="黑眼鳄", ivs=[31, 31, 31, 0, None, None]),
        )
        five_exact_child = ExecutionStep(
            number=2,
            parent_a_id="4e",
            parent_b_id="e",
            parent_a_label="4E",
            parent_b_label="E",
            child=Monster(id="5e", species="黑眼鳄", ivs=[31, 31, 31, 0, 31, None]),
        )
        self.assertEqual(six_exact_plan.nature_check_min_ivs, 5)
        self.assertFalse(six_exact_plan.should_check_nature(four_exact_child))
        self.assertTrue(six_exact_plan.should_check_nature(five_exact_child))

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

    def test_consumption_undo_restores_exact_plan_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}):
            parent_a = Monster(id="snapshot-a", species="拉鲁拉丝", gender="F")
            parent_b = Monster(id="snapshot-b", species="凯西", gender="M")
            child = Monster(id="snapshot-child", species="拉鲁拉丝", gender="F")
            snapshot = {"id": "exact-plan", "steps": [{"number": 1, "completed": False}]}
            save_inventory([parent_a, parent_b])

            consume_parents_and_add_child(
                (parent_a.id, parent_b.id),
                child,
                "exact-plan",
                1,
                plan_snapshot=snapshot,
            )
            restored = undo_last_consumption()

            self.assertIsNotNone(restored)
            self.assertEqual(restored[3], snapshot)

    def test_finished_product_is_not_added_to_inventory_and_undo_restores_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}):
            parent_a = Monster(id="final-a", species="雪笠怪", gender="F")
            parent_b = Monster(id="final-b", species="陆上组素材", gender="M")
            finished = Monster(id="finished-product", species="雪笠怪", gender="F")
            save_inventory([parent_a, parent_b])

            consume_parents_and_add_child(
                (parent_a.id, parent_b.id),
                finished,
                "final-plan",
                9,
                add_child_to_inventory=False,
            )

            self.assertEqual(load_inventory(), [])
            restored = undo_last_consumption()
            self.assertIsNotNone(restored)
            self.assertEqual(restored[2].id, finished.id)
            self.assertEqual({item.id for item in load_inventory()}, {parent_a.id, parent_b.id})

    def test_purchase_parent_is_consumed_without_being_added_to_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}):
            inventory_parent = Monster(
                id="inventory-parent",
                species="拉鲁拉丝",
                gender="F",
                ivs=[31, 1, 1, 1, 1, 1],
            )
            purchase_id = "buy:1:人型组兼容雄性:M:1:plain"
            child = Monster(
                id="purchase-child",
                species="拉鲁拉丝",
                gender="F",
                ivs=[31, 31, None, None, None, None],
            )
            save_inventory([inventory_parent])

            consume_parents_and_add_child(
                (inventory_parent.id, purchase_id),
                child,
                "purchase-plan",
                1,
                ("库存母体", "交易行雄性素材"),
            )

            self.assertEqual([item.id for item in load_inventory()], [child.id])
            restored = undo_last_consumption()
            self.assertIsNotNone(restored)
            self.assertEqual([item.id for item in load_inventory()], [inventory_parent.id])
            self.assertNotIn(purchase_id, {item.id for item in load_inventory()})

    def test_two_purchase_parents_can_create_child_without_inventory_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"LOCALAPPDATA": temp_dir}):
            child = Monster(
                id="market-child",
                species="正电拍拍",
                gender="F",
                ivs=[31, None, 31, None, None, None],
            )

            consume_parents_and_add_child(
                ("buy:1:正电拍拍:F:0:plain", "buy:2:妖精组兼容雄性:M:2:plain"),
                child,
                "market-plan",
                1,
                ("交易行母体", "交易行父本"),
            )

            self.assertEqual([item.id for item in load_inventory()], [child.id])
            undo_last_consumption()
            self.assertEqual(load_inventory(), [])


if __name__ == "__main__":
    unittest.main()
