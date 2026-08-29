from __future__ import annotations

import unittest

from models import Monster
from execution import build_execution_plan
from planner import make_report, make_report_with_candidates, normalize_nature, parse_iv_requirements
from chain_planner import (
    ChainCandidate,
    ChainState,
    _nature_target_signature,
    _search_rank,
    _state_rank,
    child_gender_policy,
    normalize_text,
)


def monster(
    identifier: str,
    species: str,
    gender: str,
    ivs: list[int | None],
    nature: str = "",
    groups: tuple[str, ...] = ("人型",),
    is_alpha: bool = False,
    has_hidden_ability: bool = False,
    moves: tuple[str, ...] = (),
) -> Monster:
    return Monster(
        id=identifier,
        species=species,
        gender=gender,
        ivs=ivs,
        nature=nature,
        egg_groups=list(groups),
        is_alpha=is_alpha,
        has_hidden_ability=has_hidden_ability,
        moves=list(moves),
        page="1",
        slot="".join(character for character in identifier if character.isdigit()) or "1",
    )


class PlannerTests(unittest.TestCase):
    def test_candidate_snapshot_round_trip_preserves_conversion_tree(self) -> None:
        inventory = [
            monster("TARGET-M", "索罗亚", "M", [31, 31, 1, 1, 1, 1], groups=("陆上",)),
            monster("DITTO", "百变怪", "N", [1, 31, 31, 1, 1, 1], groups=()),
        ]
        _report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/31/x/x/x",
            ["陆上"],
            allow_ditto=False,
            convert_maternal_with_ditto=True,
        )

        restored = ChainCandidate.from_dict(candidates[0].to_dict())

        self.assertTrue(restored.root.maternal_conversion)
        self.assertEqual(restored.root.used_ids, frozenset({"TARGET-M", "DITTO"}))
        self.assertIsNotNone(restored.root.action)

    def test_maternal_conversion_uses_exactly_one_ditto_when_global_switch_is_off(self) -> None:
        inventory = [
            monster("TARGET-M", "索罗亚", "M", [31, 31, 1, 1, 1, 1], groups=("陆上",)),
            monster("DITTO-A", "百变怪", "N", [1, 31, 31, 1, 1, 1], groups=()),
            monster("DITTO-B", "百变怪", "N", [31, 1, 1, 1, 31, 1], groups=()),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/31/x/x/x",
            ["陆上"],
            allow_ditto=False,
            convert_maternal_with_ditto=True,
        )

        self.assertTrue(candidates, report)
        self.assertTrue(candidates[0].root.maternal_conversion)
        self.assertEqual(
            len(candidates[0].root.used_ids & {"DITTO-A", "DITTO-B"}),
            1,
        )
        self.assertIn("单独使用目标公体＋百变怪锁母", report)

    def test_missing_both_target_sexes_buys_target_female_directly(self) -> None:
        _report, candidates = make_report_with_candidates(
            [monster("UNUSED-DITTO", "百变怪", "N", [31, 31, 1, 1, 1, 1], groups=())],
            "索罗亚克",
            "",
            "",
            "31/31/31/x/x/x",
            ["陆上"],
            allow_ditto=False,
            convert_maternal_with_ditto=True,
            strategy="steps",
        )

        self.assertTrue(candidates)
        target_female_leaves: list[ChainState] = []
        pending = [candidates[0].root]
        while pending:
            state = pending.pop()
            if state.action is None:
                if state.is_virtual and state.gender == "F" and state.species == "索罗亚":
                    target_female_leaves.append(state)
                continue
            pending.extend((state.action.parent_a, state.action.parent_b))
        self.assertTrue(target_female_leaves)
        self.assertGreaterEqual(max(state.mask.bit_count() for state in target_female_leaves), 2)
        self.assertNotIn("UNUSED-DITTO", candidates[0].root.used_ids)

    def test_automatic_replan_prefers_the_freshly_hatched_child(self) -> None:
        inventory = [
            monster("older", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1]),
            monster("fresh", "拉鲁拉丝", "F", [31, 31, 2, 2, 2, 2]),
            monster("donor", "凯西", "M", [3, 31, 31, 3, 3, 3]),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            preferred_material_ids={"fresh"},
        )

        self.assertIn("fresh", candidates[0].root.used_ids)
        self.assertNotIn("older", candidates[0].root.used_ids)

    def test_gender_unconfirmed_ditto_child_is_not_reused_in_a_new_normal_route(self) -> None:
        pending = monster("pending", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1])
        pending.gender_unconfirmed = True
        inventory = [
            pending,
            monster("donor", "凯西", "M", [3, 31, 31, 3, 3, 3]),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            allow_ditto=False,
        )

        self.assertTrue(candidates)
        self.assertNotIn("pending", candidates[0].root.used_ids)

    def test_parse_iv_requirements(self) -> None:
        self.assertEqual(parse_iv_requirements("31/31/x/任意/-/0"), [31, 31, None, None, None, 0])

    def test_finds_direct_pair(self) -> None:
        inventory = [
            monster("A1", "拉鲁拉丝", "F", [31, 7, 8, 9, 10, 11]),
            monster("A2", "凯西", "M", [12, 31, 13, 14, 15, 16]),
        ]
        report = make_report(inventory, "拉鲁拉丝", "", "", "31/31/x/x/x/x", ["人型"])
        self.assertIn("共 1 次孵化", report)
        self.assertIn("2 个护腕", report)
        self.assertIn("步骤 1", report)

    def test_hidden_ability_passes_from_target_evolution_line(self) -> None:
        inventory = [
            monster(
                "HA-F",
                "拉鲁拉丝",
                "F",
                [31, 1, 1, 1, 1, 1],
                has_hidden_ability=True,
            ),
            monster("ATK-M", "凯西", "M", [1, 31, 1, 1, 1, 1]),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型"],
            need_hidden_ability=True,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertTrue(candidates[0].root.has_hidden_ability)
        self.assertIn("保留梦特", report)

    def test_unrelated_hidden_ability_father_cannot_unlock_target_line(self) -> None:
        inventory = [
            monster("NORMAL-F", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1]),
            monster(
                "UNRELATED-HA-M",
                "凯西",
                "M",
                [1, 31, 1, 1, 1, 1],
                has_hidden_ability=True,
            ),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型"],
            need_hidden_ability=True,
        )

        self.assertTrue(candidates)
        self.assertGreater(candidates[0].root.purchases, 0)
        self.assertNotEqual(
            candidates[0].root.used_ids,
            frozenset({"NORMAL-F", "UNRELATED-HA-M"}),
        )

    def test_selected_egg_move_is_kept_through_the_chain(self) -> None:
        inventory = [
            monster(
                "MOVE-F",
                "拉鲁拉丝",
                "F",
                [31, 1, 1, 1, 1, 1],
                moves=("定身法",),
            ),
            monster("ATK-M", "凯西", "M", [1, 31, 1, 1, 1, 1]),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型"],
            target_moves=("定身法",),
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertIn("定身法", candidates[0].root.inherited_moves)
        self.assertIn("遗传技能：定身法", report)

    def test_inventory_egg_move_donor_is_used_and_marks_introduction_step(self) -> None:
        inventory = [
            monster("LUCARIO-F", "路卡利欧", "F", [31, 1, 1, 1, 1, 1], groups=("陆上", "人型")),
            monster(
                "LOPUNNY-M",
                "长耳兔",
                "M",
                [1, 31, 1, 1, 1, 1],
                groups=("陆上", "人型"),
                moves=("飞膝踢",),
            ),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "路卡利欧",
            "F",
            "",
            "31/31/x/x/x/x",
            ["陆上", "人型"],
            allow_ditto=False,
            target_moves=("飞膝踢",),
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.used_ids, frozenset({"LUCARIO-F", "LOPUNNY-M"}))
        self.assertEqual(candidates[0].root.introduced_moves, frozenset({"飞膝踢"}))

    def test_missing_egg_move_uses_named_route_donor_from_market(self) -> None:
        _report, candidates = make_report_with_candidates(
            [],
            "路卡利欧",
            "F",
            "",
            "31/31/x/x/x/x",
            ["陆上", "人型"],
            allow_ditto=False,
            target_moves=("飞膝踢",),
        )

        self.assertTrue(candidates)
        leaves: list[ChainState] = []

        def collect(state: ChainState) -> None:
            if state.action is None:
                leaves.append(state)
                return
            collect(state.action.parent_a)
            collect(state.action.parent_b)

        collect(candidates[0].root)
        move_donors = [state for state in leaves if "飞膝踢" in state.inherited_moves]
        self.assertTrue(move_donors)
        self.assertNotIn("兼容雄性", move_donors[0].leaf.species)

    def test_enabled_ditto_is_preferred_over_equivalent_gender_pair(self) -> None:
        inventory = [
            monster("TARGET-M", "拉鲁拉丝", "M", [31, 1, 1, 1, 1, 1]),
            monster("TARGET-F", "拉鲁拉丝", "F", [1, 31, 1, 1, 1, 1]),
            monster("DITTO", "百变怪", "N", [1, 31, 1, 1, 1, 1], groups=()),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型"],
            allow_ditto=True,
        )

        self.assertTrue(candidates)
        self.assertIn("DITTO", candidates[0].root.used_ids)

    def test_male_target_and_ditto_can_create_female_target_line_material(self) -> None:
        inventory = [
            monster(
                "TARGET-M",
                "正电拍拍",
                "M",
                [31, 24, 12, 21, 21, 31],
                groups=("妖精",),
                is_alpha=True,
            ),
            monster(
                "DITTO",
                "百变怪",
                "N",
                [17, 20, 31, 30, 28, 31],
                groups=(),
                is_alpha=True,
            ),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "正电拍拍",
            "F",
            "",
            "31/x/31/x/31/31",
            ["妖精"],
            allow_ditto=True,
            allow_alpha_materials=True,
        )

        self.assertTrue(candidates)
        self.assertTrue({"TARGET-M", "DITTO"}.issubset(candidates[0].root.used_ids))

        converted_to_female = False
        pending = [candidate.root for candidate in candidates]
        while pending:
            state = pending.pop()
            if state.action is None:
                continue
            parent_ids = state.action.parent_a.used_ids | state.action.parent_b.used_ids
            if (
                parent_ids == frozenset({"TARGET-M", "DITTO"})
                and state.species == "正电拍拍"
                and state.gender == "F"
            ):
                converted_to_female = True
                break
            pending.extend((state.action.parent_a, state.action.parent_b))
        self.assertTrue(converted_to_female)

    def test_late_nature_bootstraps_one_female_target_body_before_nature_hand(self) -> None:
        inventory = [
            monster(
                "TARGET-M",
                "索罗亚",
                "M",
                [31, 31, 1, 1, 1, 1],
                groups=("陆上",),
                is_alpha=True,
            ),
            monster(
                "DITTO",
                "百变怪",
                "N",
                [1, 31, 1, 1, 1, 31],
                groups=(),
                is_alpha=True,
            ),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "固执",
            "31/31/31/x/31/31",
            ["陆上"],
            target_alpha=True,
            allow_ditto=True,
            allow_alpha_materials=True,
            nature_strategy="late",
        )

        self.assertTrue(candidates, report)
        best = candidates[0]
        self.assertFalse(best.root.has_nature)
        self.assertEqual(best.root.gender, "F")
        self.assertEqual(best.working_gender, "F")
        self.assertTrue({"TARGET-M", "DITTO"}.issubset(best.root.used_ids))
        self.assertEqual(best.root.everstones, 0)
        self.assertIn("性格策略：母体优先", report)
        self.assertIn("仅从 4 项精确起记录", report)

        execution = build_execution_plan(best)
        checked_counts = [
            sum(value is not None for value in step.child.ivs)
            for step in execution.steps
            if execution.should_check_nature(step)
        ]
        self.assertTrue(checked_counts)
        self.assertTrue(all(value >= 4 for value in checked_counts))
        self.assertTrue(all(
            step.nature_check_role == "ignore"
            for step in execution.steps
            if sum(value is not None for value in step.child.ivs) < 4
        ))

        converted_to_female = False
        pending = [best.root]
        while pending:
            state = pending.pop()
            if state.action is None:
                continue
            parent_ids = state.action.parent_a.used_ids | state.action.parent_b.used_ids
            if (
                parent_ids == frozenset({"TARGET-M", "DITTO"})
                and state.species == "索罗亚"
                and state.gender == "F"
            ):
                converted_to_female = True
            pending.extend((state.action.parent_a, state.action.parent_b))
        self.assertTrue(converted_to_female)

    def test_one_plan_can_exclude_a_material_and_use_an_alternative(self) -> None:
        inventory = [
            monster("KEEP-F", "拉鲁拉丝", "F", [31, 7, 8, 9, 10, 11]),
            monster("RARE-M", "凯西", "M", [12, 31, 13, 14, 15, 16]),
            monster("COMMON-M", "腕力", "M", [17, 31, 18, 19, 20, 21]),
        ]
        _initial_report, initial = make_report_with_candidates(
            inventory, "拉鲁拉丝", "F", "", "31/31/x/x/x/x", ["人型"]
        )
        selected_male = next(value for value in initial[0].root.used_ids if value != "KEEP-F")

        report, replanned = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型"],
            excluded_ids={selected_male},
        )

        self.assertNotIn(selected_male, replanned[0].root.used_ids)
        self.assertEqual(replanned[0].root.purchases, 0)
        self.assertIn("本次规划已排除 1 只受保护库存素材", report)

    def test_finds_two_generation_three_iv_chain_without_reusing_parents(self) -> None:
        inventory = [
            monster("B1", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1]),
            monster("B2", "凯西", "M", [2, 31, 2, 2, 2, 2]),
            monster("B3", "拉鲁拉丝", "F", [3, 31, 3, 3, 3, 3]),
            monster("B4", "腕力", "M", [4, 4, 31, 4, 4, 4]),
        ]
        report = make_report(inventory, "拉鲁拉丝", "F", "", "31/31/31/x/x/x", ["人型"])
        self.assertIn("共 3 次孵化", report)
        self.assertIn("步骤 3", report)
        for slot in range(1, 5):
            self.assertEqual(report.count(f"1-1,{slot}"), 1)

    def test_propagates_nature_with_everstone(self) -> None:
        inventory = [
            monster("C1", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1], nature="胆小"),
            monster("C2", "凯西", "F", [31, 2, 2, 2, 2, 2]),
            monster("C3", "腕力", "M", [3, 31, 3, 3, 3, 3]),
        ]
        report = make_report(inventory, "拉鲁拉丝", "", "胆小", "31/31/x/x/x/x", ["人型"])
        self.assertIn("共 2 次孵化", report)
        self.assertIn("1 个不变之石", report)
        self.assertIn("性格 胆小", report)

    def test_accepts_chinese_ditto_name(self) -> None:
        inventory = [
            monster("D1", "拉鲁拉丝", "M", [31, 1, 1, 1, 1, 1]),
            monster("D2", "百变怪", "N", [2, 31, 2, 2, 2, 2], groups=()),
        ]
        report = make_report(inventory, "拉鲁拉丝", "", "", "31/31/x/x/x/x", ["人型"])
        self.assertIn("共 1 次孵化", report)

    def test_three_v_ditto_is_used_at_its_real_level_when_optimal(self) -> None:
        inventory = [
            monster(
                "ZORUA-M",
                "索罗亚",
                "M",
                [31, 1, 1, 1, 1, 31],
                groups=("陆上",),
                is_alpha=True,
            ),
            monster(
                "DITTO-3V",
                "百变怪",
                "N",
                [1, 31, 31, 1, 1, 31],
                groups=(),
                is_alpha=True,
            ),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/31/x/x/31",
            ["陆上"],
            target_alpha=True,
            allow_ditto=True,
        )

        self.assertTrue(candidates)
        self.assertIn("DITTO-3V", candidates[0].root.used_ids)
        self.assertEqual(candidates[0].root.purchases, 1)
        self.assertEqual(candidates[0].root.breeds, 2)

    def test_preferred_ditto_is_a_constraint_not_only_a_tie_breaker(self) -> None:
        inventory = [
            monster("DIRECT-F3", "索罗亚", "F", [31, 31, 31, 1, 1, 1], groups=("陆上",)),
            monster("DONOR-M3", "长毛狗", "M", [1, 31, 31, 1, 31, 1], groups=("陆上",)),
            monster("TARGET-M2", "索罗亚", "M", [31, 31, 1, 1, 1, 1], groups=("陆上",)),
            monster("DITTO-2V", "百变怪", "N", [1, 31, 31, 1, 1, 1], groups=()),
        ]

        _report, preferred = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/31/x/31/x",
            ["陆上"],
            allow_ditto=True,
        )
        _report, ordinary = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/31/x/31/x",
            ["陆上"],
            allow_ditto=False,
        )

        self.assertIn("DITTO-2V", preferred[0].root.used_ids)
        self.assertEqual(preferred[0].root.breeds, 2)
        self.assertNotIn("DITTO-2V", ordinary[0].root.used_ids)
        self.assertEqual(ordinary[0].root.breeds, 1)

    def test_cross_species_two_v_bridge_feeds_three_v_ditto_then_target_line(self) -> None:
        inventory = [
            monster("BRIDGE-F", "晃晃斑", "F", [31, 1, 1, 1, 1, 31], groups=("陆上",)),
            monster("BRIDGE-M", "长毛狗", "M", [31, 31, 1, 1, 1, 1], groups=("陆上",)),
            monster("DITTO-3V", "百变怪", "N", [31, 1, 1, 1, 31, 31], groups=()),
            monster("TARGET-F4", "索罗亚", "F", [1, 31, 31, 1, 31, 31], groups=("陆上",)),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/31/x/31/31",
            ["陆上"],
            allow_ditto=True,
            intermediate_gender_strategy="smart",
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertEqual(candidates[0].root.breeds, 3)
        self.assertEqual(
            candidates[0].root.used_ids,
            frozenset({"BRIDGE-F", "BRIDGE-M", "DITTO-3V", "TARGET-F4"}),
        )
        self.assertIn("本方案使用", report)
        self.assertNotIn("再次参与孵化前进化为 索罗亚", report)

    def test_market_plan_keeps_one_target_maternal_spine(self) -> None:
        _report, candidates = make_report_with_candidates(
            [],
            "索罗亚克",
            "F",
            "固执",
            "31/31/31/x/31/31",
            ["陆上"],
            target_alpha=True,
            allow_ditto=False,
            nature_strategy="late",
        )

        self.assertTrue(candidates)
        root = candidates[0].root
        pending = [root]
        leaves: list[ChainState] = []
        donor_nodes: list[ChainState] = []
        while pending:
            state = pending.pop()
            if state.action is None:
                leaves.append(state)
                continue
            if state.species == "索罗亚":
                self.assertEqual(state.action.parent_a.species, "索罗亚")
                self.assertEqual(state.action.parent_a.gender, "F")
                self.assertNotEqual(state.action.parent_b.species, "索罗亚")
            else:
                donor_nodes.append(state)
            pending.extend((state.action.parent_a, state.action.parent_b))

        self.assertTrue(donor_nodes)
        self.assertEqual(sum(state.species == "索罗亚" for state in leaves), 1)
        self.assertTrue(any("陆上组兼容" in state.leaf.species for state in leaves if state.leaf))

    def test_target_spine_uses_same_group_inventory_and_ditto_donor_tree(self) -> None:
        inventory = [
            monster("TARGET-F2", "索罗亚", "F", [31, 8, 9, 10, 11, 31], groups=("陆上",), is_alpha=True),
            monster("GROUP-F2", "晃晃斑", "F", [31, 31, 8, 9, 10, 11], groups=("陆上",), is_alpha=True),
            monster("GROUP-M2", "长毛狗", "M", [31, 7, 8, 9, 10, 31], groups=("陆上",), is_alpha=True),
            monster("DITTO-3", "百变怪", "N", [31, 7, 8, 9, 31, 31], groups=(), is_alpha=True),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "F",
            "固执",
            "31/31/31/x/31/31",
            ["陆上"],
            target_alpha=True,
            allow_ditto=True,
            nature_strategy="late",
        )

        best = candidates[0]
        self.assertTrue({"GROUP-F2", "GROUP-M2", "DITTO-3"}.issubset(best.root.used_ids))
        self.assertEqual(best.root.species, "索罗亚")
        self.assertEqual(best.root.gender, "F")
        self.assertFalse(best.root.has_nature)
        self.assertLess(best.root.purchases, 15)
        pending = [best.root]
        has_donor_branch = False
        while pending:
            state = pending.pop()
            if state.action is None:
                continue
            has_donor_branch |= state.species != "索罗亚"
            pending.extend((state.action.parent_a, state.action.parent_b))
        self.assertTrue(has_donor_branch)

    def test_alpha_hidden_ability_nature_target_keeps_executable_maternal_spine(self) -> None:
        inventory = [
            monster(
                "GROUP-F2",
                "晃晃斑",
                "F",
                [31, 31, 8, 9, 10, 11],
                groups=("陆上",),
                is_alpha=True,
            ),
            monster(
                "GROUP-M2",
                "长毛狗",
                "M",
                [31, 7, 8, 9, 10, 31],
                groups=("陆上",),
                is_alpha=True,
            ),
            monster(
                "DITTO-3",
                "百变怪",
                "N",
                [31, 31, 8, 9, 31, 7],
                groups=(),
                is_alpha=True,
            ),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚",
            "",
            "固执",
            "31/31/31/x/31/31",
            ["陆上"],
            target_alpha=True,
            allow_ditto=True,
            strategy="inventory",
            nature_strategy="late",
            intermediate_gender_strategy="智能锁定",
            need_hidden_ability=True,
        )

        self.assertTrue(candidates, report)
        root = candidates[0].root
        self.assertTrue(root.has_hidden_ability)
        self.assertFalse(root.has_nature)
        self.assertEqual(root.gender, "F")
        pending = [root]
        target_internal_females = 0
        while pending:
            state = pending.pop()
            if state.action is None:
                continue
            if state is not root and state.species == "索罗亚":
                self.assertEqual(state.gender, "F")
                self.assertEqual(
                    child_gender_policy(state, root, "", "智能锁定"),
                    "locked",
                )
                target_internal_females += 1
            pending.extend((state.action.parent_a, state.action.parent_b))
        self.assertGreater(target_internal_females, 0)
        self.assertEqual(child_gender_policy(root, root, "F", "智能锁定"), "locked")
        self.assertNotIn("没有可执行方案", report)

    def test_one_shared_iv_between_three_v_parents_cannot_guarantee_four_v(self) -> None:
        inventory = [
            monster("ZORUA-3V", "索罗亚", "M", [31, 31, 31, 1, 1, 1], groups=("陆上",)),
            monster("DITTO-3V", "百变怪", "N", [31, 1, 1, 1, 31, 31], groups=()),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/x/x/31/31",
            ["陆上"],
            allow_ditto=True,
        )

        self.assertTrue(candidates)
        self.assertFalse(
            candidates[0].root.purchases == 0 and candidates[0].root.breeds == 1,
            "only one shared 31 plus two braces cannot guarantee a 4V child",
        )

    def test_cross_species_nature_hit_can_be_promoted_into_final_nature_line(self) -> None:
        inventory = [
            monster("TARGET-5V", "索罗亚", "F", [31, 31, 31, 1, 31, 31], groups=("陆上",)),
            monster(
                "NATURE-3V",
                "晃晃斑",
                "F",
                [31, 31, 1, 1, 1, 31],
                nature="固执",
                groups=("陆上",),
            ),
            monster("DONOR-4V", "长毛狗", "M", [31, 31, 1, 1, 31, 31], groups=("陆上",)),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "固执",
            "31/31/31/x/31/31",
            ["陆上"],
            allow_ditto=False,
            nature_strategy="late",
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertEqual(candidates[0].root.breeds, 2)
        self.assertEqual(candidates[0].root.everstones, 2)
        self.assertEqual(
            candidates[0].root.used_ids,
            frozenset({"TARGET-5V", "NATURE-3V", "DONOR-4V"}),
        )

    def test_same_group_female_can_build_a_male_transfer_parent(self) -> None:
        inventory = [
            monster(
                "SPINDA-F",
                "晃晃斑",
                "F",
                [1, 1, 1, 1, 31, 31],
                groups=("陆上", "人型"),
                is_alpha=True,
            ),
            monster(
                "STOUTLAND-M",
                "长毛狗",
                "M",
                [31, 1, 1, 1, 1, 31],
                groups=("陆上",),
                is_alpha=True,
            ),
            monster(
                "ZORUA-F",
                "索罗亚",
                "F",
                [1, 31, 1, 1, 31, 31],
                groups=("陆上",),
                is_alpha=True,
            ),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/x/x/31/31",
            ["陆上"],
            target_alpha=True,
            allow_ditto=False,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertEqual(candidates[0].root.breeds, 2)
        self.assertEqual(
            candidates[0].root.used_ids,
            frozenset({"SPINDA-F", "STOUTLAND-M", "ZORUA-F"}),
        )

    def test_report_explains_when_matching_alpha_inventory_is_protected(self) -> None:
        inventory = [
            monster(
                "ALPHA-DITTO",
                "百变怪",
                "N",
                [1, 31, 31, 1, 1, 31],
                groups=(),
                is_alpha=True,
            ),
            monster(
                "ALPHA-LAND",
                "长毛狗",
                "M",
                [31, 1, 1, 1, 1, 31],
                groups=("陆上",),
                is_alpha=True,
            ),
        ]

        report, _candidates = make_report_with_candidates(
            inventory,
            "索罗亚克",
            "",
            "",
            "31/31/x/x/x/31",
            ["陆上"],
            target_alpha=False,
            allow_ditto=True,
            allow_alpha_materials=False,
        )

        self.assertIn("检测到 2 只可关联本路线的头目素材", report)
        self.assertIn("其中百变怪 1 只", report)
        self.assertIn("普通目标允许使用头目素材", report)

    def test_ditto_switch_excludes_existing_ditto(self) -> None:
        inventory = [
            monster("D1", "拉鲁拉丝", "M", [31, 1, 1, 1, 1, 1]),
            monster("D2", "百变怪", "N", [2, 31, 2, 2, 2, 2], groups=()),
        ]
        _allowed_report, allowed = make_report_with_candidates(
            inventory, "拉鲁拉丝", "", "", "31/31/x/x/x/x", ["人型"], allow_ditto=True
        )
        _blocked_report, blocked = make_report_with_candidates(
            inventory, "拉鲁拉丝", "", "", "31/31/x/x/x/x", ["人型"], allow_ditto=False
        )
        self.assertEqual(allowed[0].root.purchases, 0)
        self.assertTrue(blocked)
        self.assertNotIn("D2", blocked[0].root.used_ids)
        self.assertGreater(blocked[0].root.purchases, 0)

    def test_normal_target_protects_alpha_inventory_by_default(self) -> None:
        inventory = [
            monster("NORMAL-F", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1]),
            monster("ALPHA-M", "凯西", "M", [31, 2, 31, 2, 2, 2], is_alpha=True),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
        )

        self.assertTrue(candidates)
        self.assertNotIn("ALPHA-M", candidates[0].root.used_ids)
        self.assertGreater(candidates[0].root.purchases, 0)
        self.assertIn("仅使用普通素材；头目库存已保护", report)

    def test_normal_target_can_opt_in_to_alpha_inventory(self) -> None:
        inventory = [
            monster("NORMAL-F", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1]),
            monster("ALPHA-M", "凯西", "M", [31, 2, 31, 2, 2, 2], is_alpha=True),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            allow_alpha_materials=True,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertEqual(candidates[0].root.used_ids, frozenset({"NORMAL-F", "ALPHA-M"}))
        self.assertFalse(candidates[0].root.is_alpha)
        self.assertIn("普通与头目库存均可参与", report)

    def test_alpha_target_never_uses_normal_inventory(self) -> None:
        inventory = [
            monster("ALPHA-F", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1], is_alpha=True),
            monster("NORMAL-M", "凯西", "M", [31, 2, 31, 2, 2, 2]),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            target_alpha=True,
            allow_alpha_materials=True,
        )

        self.assertTrue(candidates)
        self.assertNotIn("NORMAL-M", candidates[0].root.used_ids)
        self.assertGreater(candidates[0].root.purchases, 0)
        self.assertTrue(candidates[0].root.is_alpha)
        self.assertIn("头目目标仅使用头目素材", report)

    def test_full_high_iv_mother_starts_upper_random_nature_hand_before_buying_nature(self) -> None:
        inventory = [
            monster(
                "DRAPION-5V",
                "龙王蝎",
                "F",
                [31, 31, 31, 13, 31, 31],
                nature="坦率",
                groups=("虫", "水中3"),
                is_alpha=True,
            )
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "龙王蝎",
            "M",
            "固执",
            "31/31/31/x/31/31",
            ["虫", "水中3"],
            target_alpha=True,
            allow_ditto=False,
            strategy="steps",
        )

        self.assertTrue(candidates)
        best = candidates[0]
        self.assertEqual(best.nature_phase, "gamble_upper")
        self.assertEqual(best.nature_attempt_level, 4)
        self.assertEqual(best.root.gender, "M")
        self.assertEqual(best.root.mask.bit_count(), 4)
        self.assertFalse(best.root.has_nature)
        self.assertEqual(best.root.breeds, 3)
        self.assertEqual(best.root.purchases, 4)
        self.assertEqual(best.root.existing_leaves, 0)
        self.assertNotIn("DRAPION-5V", best.root.used_ids)
        self.assertEqual(best.nature_strategy, "late")
        self.assertIsNotNone(best.root.action)
        self.assertIn("主动赌性格手第 1 轮", report)
        self.assertIn("库存预检", report)
        self.assertTrue(best.purchase_requirements())
        self.assertFalse(any("性格 固执" in item for item in best.purchase_requirements()))
        self.assertNotIn("当前版本：", report)
        self.assertNotIn("排序目标：", report)
        self.assertNotIn("百变怪：", report)

    def test_five_iv_nature_hand_descends_then_buys_only_two_iv_guarantee(self) -> None:
        target_ivs = [31, 31, 31, None, 31, 31]
        target_key = _nature_target_signature(
            normalize_text("索罗亚"),
            normalize_nature("固执"),
            target_ivs,
            False,
            False,
            frozenset(),
        )
        body = monster(
            "BODY-5V",
            "索罗亚",
            "F",
            [31, 31, 31, 8, 31, 31],
            nature="坦率",
            groups=("陆上",),
        )
        upper = monster(
            "HAND-4V-MISS",
            "陆上组兼容素材",
            "M",
            [31, 31, 31, None, 31, None],
            groups=("陆上",),
        )
        upper.source = "孵化方案 staged 步骤 1"
        upper.breeding_target_key = target_key
        upper.breeding_role = "nature_hand"
        upper.nature_attempt_level = 4
        upper.nature_attempt_result = "miss"

        _report, lower_candidates = make_report_with_candidates(
            [body, upper],
            "索罗亚克",
            "",
            "固执",
            "31/31/31/x/31/31",
            ["陆上"],
            allow_ditto=True,
            nature_strategy="late",
            strategy="steps",
        )

        self.assertTrue(lower_candidates)
        lower_plan = lower_candidates[0]
        self.assertEqual(lower_plan.nature_phase, "gamble_lower")
        self.assertEqual(lower_plan.nature_attempt_level, 3)
        self.assertEqual(lower_plan.root.gender, "F")
        self.assertEqual(lower_plan.root.mask.bit_count(), 3)
        self.assertNotIn("BODY-5V", lower_plan.root.used_ids)
        self.assertNotIn("HAND-4V-MISS", lower_plan.root.used_ids)

        lower = monster(
            "HAND-3V-MISS",
            "陆上组兼容素材",
            "F",
            [31, 31, None, None, 31, None],
            groups=("陆上",),
        )
        lower.source = "孵化方案 staged 步骤 2"
        lower.breeding_target_key = target_key
        lower.breeding_role = "nature_hand"
        lower.nature_attempt_level = 3
        lower.nature_attempt_result = "miss"

        guarantee_report, guarantee_candidates = make_report_with_candidates(
            [body, upper, lower],
            "索罗亚克",
            "",
            "固执",
            "31/31/31/x/31/31",
            ["陆上"],
            allow_ditto=True,
            nature_strategy="late",
            strategy="steps",
        )

        self.assertTrue(guarantee_candidates)
        guarantee = guarantee_candidates[0]
        self.assertEqual(guarantee.nature_phase, "guarantee")
        self.assertTrue(guarantee.root.has_nature)
        self.assertEqual(guarantee.root.purchases, 1)
        self.assertEqual(guarantee.root.everstones, 3)
        self.assertTrue({"BODY-5V", "HAND-4V-MISS", "HAND-3V-MISS"}.issubset(guarantee.root.used_ids))
        requirement = guarantee.purchase_requirements()[0]
        self.assertIn("性格 固执", requirement)
        self.assertEqual(requirement.count("IV=31"), 2)
        self.assertIn("最终保底", guarantee_report)

    def test_four_iv_alpha_stops_at_two_iv_floor_after_upper_hand_misses(self) -> None:
        target_ivs = [31, 31, 31, None, None, 31]
        target_key = _nature_target_signature(
            normalize_text("索罗亚"),
            normalize_nature("固执"),
            target_ivs,
            True,
            False,
            frozenset(),
        )
        body = monster(
            "ALPHA-BODY-4V",
            "索罗亚",
            "F",
            [31, 31, 31, 8, 7, 31],
            nature="坦率",
            groups=("陆上",),
            is_alpha=True,
        )
        upper = monster(
            "ALPHA-HAND-3V-MISS",
            "陆上组兼容素材",
            "M",
            [31, 31, None, None, None, 31],
            groups=("陆上",),
            is_alpha=True,
        )
        upper.source = "孵化方案 alpha-staged 步骤 1"
        upper.breeding_target_key = target_key
        upper.breeding_role = "nature_hand"
        upper.nature_attempt_level = 3
        upper.nature_attempt_result = "miss"

        report, candidates = make_report_with_candidates(
            [body, upper],
            "索罗亚克",
            "",
            "固执",
            "31/31/31/x/x/31",
            ["陆上"],
            target_alpha=True,
            allow_alpha_materials=True,
            allow_ditto=True,
            nature_strategy="late",
            strategy="steps",
        )

        self.assertTrue(candidates, report)
        best = candidates[0]
        self.assertEqual(best.nature_phase, "guarantee")
        self.assertEqual(best.root.purchases, 1)
        self.assertEqual(best.root.breeds, 2)
        self.assertTrue(best.root.has_nature)
        requirement = best.purchase_requirements()[0]
        self.assertIn("头目", requirement)
        self.assertIn("性格 固执", requirement)
        self.assertEqual(requirement.count("IV=31"), 2)

    def test_inventory_audit_and_ready_merge_use_two_existing_two_v_parents(self) -> None:
        inventory = [
            monster("TWO-A", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1]),
            monster("TWO-B", "拉鲁拉丝", "M", [1, 31, 31, 1, 1, 1]),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "固执",
            "31/31/31/31/31/x",
            ["人型"],
            allow_ditto=False,
            nature_strategy="late",
        )

        best = candidates[0]
        self.assertEqual(best.inventory_pool_size, 2)
        self.assertEqual(best.inventory_iv_histogram[2], 2)
        self.assertGreaterEqual(best.root.inventory_breeds, 1)
        self.assertIn("2V 2只", report)

    def test_two_v_inventory_starts_at_two_v_instead_of_becoming_one_v(self) -> None:
        inventory = [
            monster("TWO-AC", "拉鲁拉丝", "F", [31, 1, 31, 1, 1, 1]),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/31/x/x",
            ["人型"],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertEqual(best.root.purchases, 6)
        self.assertEqual(best.root.breeds, 6)

        consuming_nodes: list[ChainState] = []

        def visit(state: ChainState) -> None:
            if state.action is None:
                return
            if any(
                parent.leaf is not None and parent.leaf.id == "TWO-AC"
                for parent in (state.action.parent_a, state.action.parent_b)
            ):
                consuming_nodes.append(state)
            visit(state.action.parent_a)
            visit(state.action.parent_b)

        visit(best.root)
        self.assertEqual(len(consuming_nodes), 1)
        self.assertEqual(consuming_nodes[0].mask.bit_count(), 3)

    def test_two_v_with_only_one_relevant_stat_is_not_spent_as_one_v(self) -> None:
        inventory = [
            # 特防是目标中的 X；这仍然是一只真实 2V，不能为了 HP 把它当 1V 消耗。
            monster("TWO-WITH-X", "拉鲁拉丝", "F", [31, 1, 1, 1, 31, 1]),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/31/x/x",
            ["人型"],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertNotIn("TWO-WITH-X", best.root.used_ids)
        self.assertEqual(best.root.existing_leaves, 0)

    def test_three_v_inventory_starts_at_three_v(self) -> None:
        inventory = [
            monster("THREE-ABC", "拉鲁拉丝", "F", [31, 31, 31, 1, 1, 1]),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/31/x/x",
            ["人型"],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertIn("THREE-ABC", best.root.used_ids)
        self.assertEqual(best.root.purchases, 4)
        self.assertEqual(best.root.breeds, 4)

    def test_evolution_line_members_share_one_breeding_pool(self) -> None:
        inventory = [
            monster("SKORUPI", "钳尾蝎", "F", [31, 1, 1, 1, 1, 1], groups=("虫", "水中3")),
            monster("DRAPION", "龙王蝎", "M", [1, 31, 1, 1, 1, 1], groups=("虫", "水中3")),
        ]

        report, candidates = make_report_with_candidates(
            inventory, "龙王蝎", "F", "", "31/31/x/x/x/x", []
        )

        self.assertTrue(candidates)
        best = candidates[0]
        self.assertEqual(best.root.purchases, 0)
        self.assertEqual(best.root.breeds, 1)
        self.assertEqual(best.root.species, "钳尾蝎")
        self.assertEqual(best.target_species, "龙王蝎")
        self.assertIn("孵蛋目标：钳尾蝎", report)
        self.assertIn("所选形态 龙王蝎（孵化后进化）", report)

    def test_evolved_form_input_uses_first_hatch_form_as_breeding_target(self) -> None:
        report, candidates = make_report_with_candidates(
            [],
            "大嘴蝠",
            "F",
            "",
            "31/31/x/x/x/x",
            [],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertEqual(best.root.species, "超音蝠")
        self.assertEqual(best.offspring_species, "超音蝠")
        self.assertEqual(best.target_species, "大嘴蝠")
        self.assertIn("孵蛋目标：超音蝠", report)
        self.assertIn("所选形态 大嘴蝠（孵化后进化）", report)

    def test_nidoking_keeps_female_spine_and_locks_male_only_for_final_child(self) -> None:
        report, candidates = make_report_with_candidates(
            [],
            "尼多王",
            "M",
            "",
            "31/31/31/x/31/31",
            [],
            allow_ditto=False,
        )

        self.assertTrue(candidates, report)
        best = candidates[0]
        plan = build_execution_plan(best)
        nidoran_intermediates = [
            step
            for step in plan.steps[:-1]
            if step.child.species in {"尼多兰", "尼多朗"}
        ]
        self.assertTrue(nidoran_intermediates)
        self.assertTrue(all(step.child.species == "尼多兰" for step in nidoran_intermediates))
        self.assertTrue(all(step.child.gender == "F" for step in nidoran_intermediates))
        self.assertTrue(all(step.gender_policy == "locked" for step in nidoran_intermediates))
        self.assertEqual(plan.steps[-1].child.species, "尼多朗")
        self.assertEqual(plan.steps[-1].child.gender, "M")
        self.assertEqual(plan.steps[-1].gender_policy, "locked")
        self.assertNotIn("需要百变怪", report)

    def test_nidoking_uses_nidoqueen_mother_and_same_group_male_inventory(self) -> None:
        inventory = [
            monster(
                "NIDOQUEEN-F",
                "尼多后",
                "F",
                [31, 1, 1, 1, 1, 1],
                groups=("怪兽", "陆上"),
            ),
            monster(
                "FIELD-M",
                "长毛狗",
                "M",
                [1, 31, 1, 1, 1, 1],
                groups=("陆上",),
            ),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "尼多王",
            "M",
            "",
            "31/31/x/x/x/x",
            [],
            allow_ditto=False,
        )

        self.assertTrue(candidates, report)
        best = candidates[0]
        self.assertEqual(best.root.used_ids, frozenset({"NIDOQUEEN-F", "FIELD-M"}))
        self.assertEqual(best.root.purchases, 0)
        self.assertEqual(best.root.output_species, "尼多朗")
        self.assertIn("中间代锁母，最终成品锁公", report)

    def test_nidoking_nature_finish_still_changes_to_male_only_at_final_step(self) -> None:
        inventory = [
            monster(
                "FIVE-V-MOTHER",
                "尼多兰",
                "F",
                [31, 31, 31, 1, 31, 31],
                nature="温顺",
                groups=("怪兽", "陆上"),
            ),
            monster(
                "FOUR-V-NATURE",
                "长毛狗",
                "M",
                [31, 31, 31, 1, 31, 2],
                nature="固执",
                groups=("陆上",),
            ),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "尼多王",
            "M",
            "固执",
            "31/31/31/x/31/31",
            [],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertEqual(best.nature_phase, "finish")
        self.assertEqual(best.root.output_species, "尼多朗")
        self.assertEqual(best.root.gender, "M")
        self.assertTrue(best.root.has_nature)
        self.assertEqual(best.root.used_ids, frozenset({"FIVE-V-MOTHER", "FOUR-V-NATURE"}))

    def test_genderless_evolution_line_can_breed_without_ditto(self) -> None:
        inventory = [
            monster("GOLETT", "泥偶小人", "N", [31, 1, 1, 1, 1, 1], groups=("矿物",)),
            monster("GOLURK", "泥偶巨人", "N", [1, 31, 1, 1, 1, 1], groups=("矿物",)),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "泥偶巨人",
            "",
            "",
            "31/31/x/x/x/x",
            [],
            allow_ditto=False,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertEqual(candidates[0].root.breeds, 1)
        self.assertEqual(candidates[0].root.species, "泥偶小人")

    def test_ditto_cannot_be_a_breeding_target(self) -> None:
        report, candidates = make_report_with_candidates(
            [], "百变怪", "", "", "31/x/x/x/x/x", []
        )
        self.assertFalse(candidates)
        self.assertIn("不能通过孵蛋获得", report)

    def test_inventory_rank_preserves_overqualified_subproblem_material(self) -> None:
        exact = ChainState(
            species="钳尾蝎", gender="F", egg_groups=("虫", "水中3"), mask=1,
            has_nature=False, nature="", is_alpha=False, used_ids=frozenset({"exact"}),
            generation=0, breeds=0, braces=0, everstones=0,
        )
        overqualified = ChainState(
            species="钳尾蝎", gender="F", egg_groups=("虫", "水中3"), mask=0b11111,
            has_nature=False, nature="", is_alpha=False, used_ids=frozenset({"five-v"}),
            generation=0, breeds=0, braces=0, everstones=0,
        )
        self.assertLess(
            _search_rank(exact, "inventory", required_mask=1),
            _search_rank(overqualified, "inventory", required_mask=1),
        )

    def test_neutral_nature_target_uses_any_neutral_holder(self) -> None:
        inventory = [
            monster("NT1", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1], nature="认真"),
            monster("NT2", "拉鲁拉丝", "M", [2, 31, 2, 2, 2, 2]),
        ]
        report, candidates = make_report_with_candidates(
            inventory, "拉鲁拉丝", "F", "无修正（任一）", "31/31/x/x/x/x", ["人型"]
        )
        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.nature, "认真")
        self.assertIn("性格 认真", report)

    def test_strategy_changes_primary_ranking_dimension(self) -> None:
        inventory_heavy = ChainState(
            species="拉鲁拉丝", gender="F", egg_groups=("人型",), mask=3,
            has_nature=False, nature="", is_alpha=False,
            used_ids=frozenset({"a", "b", "c", "d"}), generation=2,
            breeds=3, braces=4, everstones=0, purchases=0,
        )
        short_route = ChainState(
            species="拉鲁拉丝", gender="F", egg_groups=("人型",), mask=3,
            has_nature=False, nature="", is_alpha=False,
            used_ids=frozenset({"a", "buy:1"}), generation=1,
            breeds=1, braces=2, everstones=0, purchases=1,
        )
        self.assertLess(_state_rank(inventory_heavy, "inventory"), _state_rank(short_route, "inventory"))
        self.assertLess(_state_rank(short_route, "steps"), _state_rank(inventory_heavy, "steps"))

    def test_reports_missing_iv_material(self) -> None:
        inventory = [monster("E1", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1])]
        report = make_report(inventory, "拉鲁拉丝", "", "", "31/31/x/x/x/x", ["人型"])
        self.assertIn("攻击 IV=31", report)
        self.assertIn("需要补充 1 只", report)

    def test_automatically_enriches_egg_groups(self) -> None:
        inventory = [
            monster("G1", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1], groups=()),
            monster("G2", "凯西", "M", [2, 31, 2, 2, 2, 2], groups=()),
        ]
        report = make_report(inventory, "拉鲁拉丝", "", "", "31/31/x/x/x/x", [])
        self.assertIn("需要补充 0 只", report)
        self.assertIn("蛋组 人型 / 不定形", report)

    def test_unverified_ocr_rows_are_not_used(self) -> None:
        first = monster("U1", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1])
        second = monster("U2", "凯西", "M", [2, 31, 2, 2, 2, 2])
        second.verified = False
        report = make_report([first, second], "拉鲁拉丝", "", "", "31/31/x/x/x/x", [])
        self.assertIn("需要补充 1 只", report)

    def test_partial_cross_species_inventory_reduces_purchases(self) -> None:
        inventory = [
            monster("M1", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1], groups=()),
            monster("M2", "凯西", "M", [2, 31, 2, 2, 2, 2], groups=()),
        ]
        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            [],
        )
        self.assertTrue(candidates)
        self.assertGreaterEqual(candidates[0].root.existing_leaves, 2)
        self.assertLess(candidates[0].root.purchases, 4)

    def test_market_male_is_listed_as_any_compatible_egg_group_species(self) -> None:
        inventory = [monster("MOTHER", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1])]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型", "不定形"],
            allow_ditto=False,
        )

        requirements = "\n".join(candidates[0].purchase_requirements())
        self.assertIn("兼容雄性", requirements)
        self.assertIn("人型/不定形", requirements)

    def test_other_species_female_is_not_treated_as_direct_target_species_parent(self) -> None:
        inventory = [
            monster("TARGET-F", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1]),
            monster("GROUP-F", "凯西", "F", [1, 31, 1, 1, 1, 1]),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型"],
            allow_ditto=False,
        )

        self.assertGreaterEqual(candidates[0].root.purchases, 1)
        self.assertEqual(candidates[0].inventory_target_female_count, 1)
        self.assertEqual(candidates[0].inventory_compatible_male_count, 0)
        self.assertEqual(candidates[0].inventory_other_female_count, 1)
        self.assertIn("其他同组雌性 1只", report)

    def test_other_species_two_v_female_is_not_downgraded_for_upstream_donor(self) -> None:
        inventory = [
            monster("TARGET-F", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1]),
            monster("JYNX-F", "迷唇姐", "F", [1, 31, 31, 1, 1, 1]),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertNotIn("JYNX-F", best.root.used_ids)
        self.assertEqual(best.root.existing_leaves, 1)
        self.assertEqual(best.root.purchases, 3)

    def test_female_only_species_cannot_create_an_impossible_male_donor(self) -> None:
        inventory = [
            monster("TARGET-F", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1]),
            monster("JYNX-F", "迷唇姐", "F", [1, 31, 1, 1, 1, 1]),
            monster("MACHOP-M", "腕力", "M", [1, 1, 31, 1, 1, 1]),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertNotIn("JYNX-F", best.root.used_ids)
        self.assertGreaterEqual(best.root.purchases, 1)
        self.assertEqual(best.inventory_excluded_female_only_count, 1)
        self.assertIn("已排除非目标纯母 1只", report)

    def test_male_only_species_remains_a_compatible_father(self) -> None:
        inventory = [
            monster("TARGET-F", "拉鲁拉丝", "F", [31, 1, 1, 1, 1, 1]),
            monster("HITMON-M", "飞腿郎", "M", [1, 31, 1, 1, 1, 1]),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/x/x/x/x",
            ["人型"],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertEqual(best.root.purchases, 0)
        self.assertEqual(best.root.used_ids, frozenset({"TARGET-F", "HITMON-M"}))

    def test_female_only_species_is_valid_when_breeding_its_own_line(self) -> None:
        inventory = [
            monster("CHANSEY-F", "吉利蛋", "F", [31, 1, 1, 1, 1, 1], groups=("妖精",)),
            monster("CLEFAIRY-M", "皮皮", "M", [1, 31, 1, 1, 1, 1], groups=("妖精",)),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "幸福蛋",
            "F",
            "",
            "31/31/x/x/x/x",
            [],
            allow_ditto=False,
        )

        best = candidates[0]
        self.assertEqual(best.root.purchases, 0)
        self.assertEqual(best.root.species, "吉利蛋")
        self.assertEqual(best.root.used_ids, frozenset({"CHANSEY-F", "CLEFAIRY-M"}))

    def test_finds_standard_five_iv_pyramid(self) -> None:
        leaf_requirements: list[tuple[int, str]] = []

        def add_tree(mask: int, output_gender: str) -> None:
            bits = [index for index in range(6) if mask & (1 << index)]
            if len(bits) == 1:
                leaf_requirements.append((bits[0], output_gender))
                return
            add_tree(mask & ~(1 << bits[-1]), "F")
            add_tree(mask & ~(1 << bits[0]), "M")

        add_tree((1 << 5) - 1, "F")
        inventory = []
        for index, (stat, gender) in enumerate(leaf_requirements, 1):
            ivs = [0] * 6
            ivs[stat] = 31
            inventory.append(monster(f"P{index}", "拉鲁拉丝", gender, ivs))

        report = make_report(inventory, "拉鲁拉丝", "F", "", "31/31/31/31/31/x", ["人型"])
        self.assertIn("共 15 次孵化", report)
        self.assertIn("步骤 15", report)

    def test_six_exact_iv_route_supports_non_perfect_target_value(self) -> None:
        report, candidates = make_report_with_candidates(
            [],
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/0/31/31",
            ["人型"],
            allow_ditto=False,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.mask, 0b111111)
        self.assertEqual(candidates[0].root.breeds, 31)
        self.assertEqual(candidates[0].root.purchases, 32)
        self.assertIn("特攻 IV=0", report)

    def test_six_exact_iv_nature_route_uses_full_nature_pyramid(self) -> None:
        report, candidates = make_report_with_candidates(
            [],
            "黑眼鳄",
            "F",
            "固执",
            "31/31/31/16/31/31",
            ["陆上"],
            allow_ditto=False,
            nature_strategy="late",
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.mask, 0b111111)
        self.assertEqual(candidates[0].root.breeds, 31)
        self.assertEqual(candidates[0].root.everstones, 0)
        self.assertFalse(candidates[0].root.has_nature)
        self.assertIn("性格策略：母体优先", report)

    def test_six_exact_iv_route_starts_from_matching_five_stat_inventory(self) -> None:
        inventory = [
            monster("EXACT-F", "黑眼鳄", "F", [31, 31, 31, 16, 31, 7], groups=("陆上",)),
            monster("EXACT-M", "混混鳄", "M", [8, 31, 31, 16, 31, 31], groups=("陆上",)),
        ]

        _report, candidates = make_report_with_candidates(
            inventory,
            "流氓鳄",
            "F",
            "",
            "31/31/31/16/31/31",
            ["陆上"],
            allow_ditto=False,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].root.breeds, 1)
        self.assertEqual(candidates[0].root.purchases, 0)
        self.assertEqual(candidates[0].root.used_ids, frozenset({"EXACT-F", "EXACT-M"}))

    def test_late_nature_five_iv_starts_with_plain_maternal_pyramid(self) -> None:
        leaf_requirements: list[tuple[int | None, str, str]] = []

        def add_plain(mask: int, output_gender: str) -> None:
            bits = [index for index in range(6) if mask & (1 << index)]
            if len(bits) == 1:
                leaf_requirements.append((bits[0], output_gender, ""))
                return
            add_plain(mask & ~(1 << bits[-1]), "F")
            add_plain(mask & ~(1 << bits[0]), "M")

        def add_nature(mask: int, output_gender: str) -> None:
            bits = [index for index in range(6) if mask & (1 << index)]
            if not bits:
                leaf_requirements.append((None, output_gender, "胆小"))
                return
            add_nature(mask & ~(1 << bits[-1]), "F")
            add_plain(mask, "M")

        add_nature((1 << 5) - 1, "F")
        inventory = []
        for index, (stat, gender, nature) in enumerate(leaf_requirements, 1):
            ivs = [0] * 6
            if stat is not None:
                ivs[stat] = 31
            inventory.append(monster(f"N{index}", "拉鲁拉丝", gender, ivs, nature=nature))

        report = make_report(inventory, "拉鲁拉丝", "F", "胆小", "31/31/31/31/31/x", ["人型"])
        self.assertIn("共 15 次孵化", report)
        self.assertIn("0 个不变之石", report)
        self.assertIn("仅从 4 项精确起记录是否爆出 胆小", report)

    def test_full_nature_chain_mode_keeps_the_original_strict_pyramid(self) -> None:
        report, candidates = make_report_with_candidates(
            [],
            "拉鲁拉丝",
            "F",
            "胆小",
            "31/31/31/31/31/x",
            ["人型"],
            allow_ditto=False,
            nature_strategy="chain",
        )

        self.assertTrue(candidates, report)
        self.assertEqual(candidates[0].root.breeds, 31)
        self.assertEqual(candidates[0].root.everstones, 5)
        self.assertTrue(candidates[0].root.has_nature)

    def test_alpha_target_requires_alpha_on_both_parents(self) -> None:
        inventory = [
            monster("A-alpha", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1], is_alpha=True),
            monster("B-normal", "凯西", "M", [1, 31, 31, 1, 1, 1], is_alpha=False),
        ]

        report, candidates = make_report_with_candidates(
            inventory,
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/x/x/x",
            ["人型"],
            True,
        )

        self.assertTrue(candidates)
        self.assertTrue(candidates[0].root.is_alpha)
        self.assertEqual(candidates[0].root.existing_leaves, 1)
        self.assertEqual(candidates[0].root.purchases, 1)
        self.assertIn("需补充", report)
        self.assertIn("头目", report)

    def test_two_alpha_parents_produce_alpha_without_purchases(self) -> None:
        inventory = [
            monster("AA1", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1], is_alpha=True),
            monster("AA2", "凯西", "M", [1, 31, 31, 1, 1, 1], is_alpha=True),
        ]

        _report, candidates = make_report_with_candidates(
            inventory, "拉鲁拉丝", "F", "", "31/31/31/x/x/x", ["人型"], True
        )

        self.assertTrue(candidates)
        self.assertTrue(candidates[0].root.is_alpha)
        self.assertEqual(candidates[0].root.purchases, 0)

    def test_normal_target_does_not_treat_two_alpha_parents_as_normal(self) -> None:
        inventory = [
            monster("NA1", "拉鲁拉丝", "F", [31, 31, 1, 1, 1, 1], is_alpha=True),
            monster("NA2", "凯西", "M", [1, 31, 31, 1, 1, 1], is_alpha=True),
        ]

        _report, candidates = make_report_with_candidates(
            inventory, "拉鲁拉丝", "F", "", "31/31/31/x/x/x", ["人型"], False
        )

        self.assertTrue(candidates)
        self.assertFalse(candidates[0].root.is_alpha)
        self.assertGreaterEqual(candidates[0].root.purchases, 1)

    def test_alpha_four_v_market_route_starts_from_two_v(self) -> None:
        _report, candidates = make_report_with_candidates(
            [],
            "拉鲁拉丝",
            "F",
            "",
            "31/31/31/31/x/x",
            ["人型"],
            target_alpha=True,
            allow_ditto=False,
        )

        best = candidates[0]
        leaves: list[ChainState] = []

        def collect(state: ChainState) -> None:
            if state.action is None:
                leaves.append(state)
                return
            collect(state.action.parent_a)
            collect(state.action.parent_b)

        collect(best.root)
        self.assertEqual(best.root.breeds, 3)
        self.assertEqual(best.root.purchases, 4)
        self.assertEqual({leaf.effective_material_v for leaf in leaves}, {2})
        self.assertTrue(all(leaf.is_alpha for leaf in leaves))

    def test_alpha_nature_route_has_no_zero_or_one_v_leaves(self) -> None:
        _report, candidates = make_report_with_candidates(
            [],
            "拉鲁拉丝",
            "F",
            "固执",
            "31/31/31/31/x/x",
            ["人型"],
            target_alpha=True,
            allow_ditto=False,
            nature_strategy="late",
        )

        leaves: list[ChainState] = []

        def collect(state: ChainState) -> None:
            if state.action is None:
                leaves.append(state)
                return
            collect(state.action.parent_a)
            collect(state.action.parent_b)

        collect(candidates[0].root)
        self.assertFalse(any(leaf.has_nature for leaf in leaves))
        self.assertTrue(all(leaf.effective_material_v >= 2 for leaf in leaves))


if __name__ == "__main__":
    unittest.main()
