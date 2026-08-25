from __future__ import annotations

import unittest

from models import Monster
from planner import make_report, make_report_with_candidates, parse_iv_requirements
from chain_planner import ChainState, _search_rank, _state_rank


def monster(
    identifier: str,
    species: str,
    gender: str,
    ivs: list[int | None],
    nature: str = "",
    groups: tuple[str, ...] = ("人型",),
    is_alpha: bool = False,
) -> Monster:
    return Monster(
        id=identifier,
        species=species,
        gender=gender,
        ivs=ivs,
        nature=nature,
        egg_groups=list(groups),
        is_alpha=is_alpha,
        page="1",
        slot=identifier,
    )


class PlannerTests(unittest.TestCase):
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
        for identifier in ("B1", "B2", "B3", "B4"):
            self.assertEqual(report.count(f"仓库 1/{identifier}"), 1)

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

    def test_high_iv_breeder_uses_one_complementary_nature_purchase(self) -> None:
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
        self.assertEqual(best.root.breeds, 1)
        self.assertEqual(best.root.purchases, 1)
        self.assertEqual(best.root.existing_leaves, 1)
        self.assertIn("DRAPION-5V", best.root.used_ids)
        self.assertEqual(best.nature_strategy, "late")
        self.assertIsNotNone(best.root.action)
        top_parents = (best.root.action.parent_a, best.root.action.parent_b)
        self.assertEqual(sorted(parent.mask.bit_count() for parent in top_parents), [4, 5])
        self.assertEqual({parent.has_nature for parent in top_parents}, {False, True})
        self.assertIn("后置性格", report)
        self.assertIn("库存预检", report)
        requirement = best.purchase_requirements()[0]
        self.assertIn("性格 固执", requirement)
        self.assertEqual(requirement.count("IV=31"), 4)
        self.assertNotIn("当前版本：", report)
        self.assertNotIn("排序目标：", report)
        self.assertNotIn("百变怪：", report)

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
        _report, candidates = make_report_with_candidates(
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
        self.assertEqual(candidates[0].root.breeds, 63)
        self.assertEqual(candidates[0].root.everstones, 6)
        self.assertTrue(candidates[0].root.has_nature)

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

    def test_finds_standard_five_iv_nature_pyramid(self) -> None:
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
        self.assertIn("共 31 次孵化", report)
        self.assertIn("5 个不变之石", report)

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
        self.assertTrue(any(leaf.has_nature for leaf in leaves))
        self.assertTrue(all(leaf.effective_material_v >= 2 for leaf in leaves))


if __name__ == "__main__":
    unittest.main()
