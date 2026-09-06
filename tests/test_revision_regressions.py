"""Desktop review regressions. All execution writes use a temporary database."""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import App
from chain_planner import ChainCandidate
from execution import build_execution_plan
from mind_map import MindMapNode
from models import Monster
from planner import make_report_with_candidates
from storage import consume_parents_and_add_child, load_inventory, save_inventory, undo_last_consumption


IVS = [31, None, 31, 31, 31, 31]


def material(identifier, species, gender, ivs, nature="温顺", alpha=True, hidden=False, groups=()):
    return Monster(id=identifier, species=species, gender=gender, ivs=ivs,
                   nature=nature, is_alpha=alpha, has_hidden_ability=hidden,
                   egg_groups=list(groups), verified=True,
                   source="孵化方案 regression" if groups else "")


class RevisionRegressionTests(unittest.TestCase):
    def plan(self, inventory, target="尼多王", alpha=True, hidden=True, ivs=IVS):
        report, candidates = make_report_with_candidates(
            inventory, target, "M", "内敛",
            "/".join("x" if value is None else str(value) for value in ivs), [],
            target_alpha=alpha, need_hidden_ability=hidden, allow_ditto=False,
        )
        self.assertTrue(candidates, report)
        return candidates[0]

    def body(self, species="尼多兰", alpha=True):
        return material("body", species, "F", IVS, alpha=alpha, hidden=True)

    def test_incompatible_lower_hit_or_miss_does_not_enter_empty_merge(self):
        for species, target in (("尼多兰", "尼多王"), ("索罗亚", "索罗亚克")):
            for nature in ("内敛", "温顺"):
                with self.subTest(target=target, nature=nature):
                    body = self.body(species)
                    upper = material("upper", "长毛狗", "M", [31, None, 31, 31, 31, None])
                    lower = material("bad-lower", "风速狗", "F", [31, None, 31, None, None, 31], nature)
                    candidate = self.plan([body, upper, lower], target)
                    self.assertEqual(candidate.nature_phase, "gamble_lower")
                    self.assertEqual(candidate.retained_body_id, body.id)
                    self.assertEqual(candidate.retained_upper_id, upper.id)
                    self.assertFalse({body.id, upper.id} & candidate.root.used_ids)
                    self.assertEqual(candidate.root.mask & ~0b011101, 0)
                    self.assertTrue(candidate.root.is_alpha)

    def test_manual_mother_is_in_map_without_attempt_metadata(self):
        body = self.body()
        candidate = self.plan([body])
        app = App.__new__(App)
        app.inventory = [body]
        current = MindMapNode(key="current", title="性格手")
        wrapped = app._wrap_staged_nature_context(
            candidate, current, map_key_prefix="test", species_sprite_id=lambda _: 1)
        self.assertEqual(wrapped.children[1], current)
        self.assertIn(body.id, wrapped.children[0].key)
        self.assertNotIn(body.id, candidate.root.used_ids)

    def test_retained_snapshot_does_not_switch_to_newer_or_excluded_material(self):
        body = self.body()
        candidate = ChainCandidate.from_dict(self.plan([body]).to_dict())
        newer = Monster.from_dict(dict(body.to_dict(), id="newer", updated_at="2099-01-01"))
        newer.breeding_target_key = candidate.nature_target_key
        newer.breeding_role = "maternal"
        newer.nature_attempt_level = 5
        newer.nature_attempt_result = "miss"
        app = App.__new__(App)
        app.inventory = [newer, body]
        args = dict(role="maternal", level=5, gender="F")
        self.assertIs(app._latest_failed_nature_material(candidate, **args), body)
        app.plan_excluded_ids = {body.id}
        self.assertIsNone(app._latest_failed_nature_material(candidate, **args))
        app.plan_excluded_ids = set()
        app.inventory = [newer]
        self.assertIsNone(app._latest_failed_nature_material(candidate, **args))

    def test_legacy_candidate_still_loads(self):
        snapshot = self.plan([self.body()]).to_dict()
        snapshot.pop("retained_body_id")
        snapshot.pop("retained_upper_id")
        restored = ChainCandidate.from_dict(snapshot)
        self.assertIsNone(restored.retained_body_id)

    def test_just_completed_mother_is_preferred_over_older_equivalent(self):
        older = self.body()
        fresh = Monster.from_dict(dict(older.to_dict(), id="fresh-body"))
        report, candidates = make_report_with_candidates(
            [older, fresh], "尼多王", "M", "内敛", "31/x/31/31/31/31", [],
            target_alpha=True, need_hidden_ability=True, allow_ditto=False,
            preferred_material_ids={fresh.id})
        self.assertTrue(candidates, report)
        self.assertTrue(all(candidate.retained_body_id == fresh.id for candidate in candidates))

    def test_hand_and_maternal_reports_do_not_claim_wrong_evolution(self):
        candidate = self.plan([self.body()])
        self.assertIn("独立性格手", candidate.description())
        self.assertNotIn("进化为", candidate.description())
        plan = build_execution_plan(candidate)
        self.assertNotIn("进化为最终目标", plan.steps[-1].child.notes)
        candidate.nature_phase = "maternal"
        self.assertFalse(candidate.final_evolution_from("尼多兰", "F"))
        candidate.nature_phase = "finish"
        self.assertFalse(candidate.final_evolution_from("尼多兰", "F"))
        self.assertTrue(candidate.final_evolution_from("尼多朗", "M"))
        self.assertFalse(candidate.final_evolution_from("长毛狗", "M"))

    def test_inventory_pair_after_eight_male_only_profiles_is_used(self):
        body = self.body("索罗亚")
        clutter = [material(f"male-{i}", f"aa{i}组素材", "M", [31, None, None, None, None, None],
                            groups=("陆上",)) for i in range(12)]
        female = material("use-female", "长毛狗", "F", [31, None, 31, 31, None, None])
        male = material("use-male", "风速狗", "M", [31, None, 31, None, 31, None])
        candidate = self.plan([body, *clutter, female, male], "索罗亚克")
        self.assertEqual(candidate.inventory_pool_size, 15)
        self.assertEqual(candidate.nature_phase, "gamble_upper")
        self.assertEqual(candidate.root.purchases, 0)
        self.assertEqual(candidate.root.breeds, 1)
        self.assertEqual(candidate.root.used_ids, {female.id, male.id})

    def test_different_target_egg_groups_do_not_make_invalid_lower_hand(self):
        # Nidoran shares Monster/Field; a Water1/Monster father must receive a
        # Monster or Water1 hand, not an unrelated Field-only female.
        body = self.body()
        upper = material("upper", "水箭龟", "M", [31, None, 31, 31, 31, None])
        lower = material("lower", "长毛狗", "F", [31, None, 31, None, 31, None], "内敛")
        candidate = self.plan([body, upper, lower])
        self.assertEqual(candidate.nature_phase, "gamble_lower")
        self.assertTrue(set(candidate.root.egg_groups) & {"怪兽", "水中1"})
        self.assertNotIn(lower.id, candidate.root.used_ids)

    def test_ocr_hidden_ability_name_is_not_diamond_evidence(self):
        app = App.__new__(App)
        record = SimpleNamespace(display_name="索罗亚", allowed_genders=("F", "M"), id=570, egg_groups=("陆上",))
        app._resolve_ocr_species = lambda _: (record, True)
        app.reference_db = MagicMock()
        app.reference_db.canonical_ability.side_effect = lambda value: value
        app.reference_db.hidden_ability_names.return_value = ["测试梦特名"]
        for name in ("species", "gender", "nature", "alpha", "ability", "hidden_ability", "iv", "moves", "item", "groups", "recent_scan"):
            var = SimpleNamespace(value="")
            var.set = lambda value, var=var: setattr(var, "value", value)
            var.get = lambda var=var: var.value
            setattr(app, f"{name}_var", var)
        app.raw_text_box = MagicMock()
        app._set_batch_parameters_compact = lambda _: None
        app._set_compact_scan_view = lambda _: None
        app.layout_orientation = "wide"
        for diamond, alpha, expected in ((False, False, False), (True, False, True), (False, True, True)):
            with self.subTest(diamond=diamond, alpha=alpha):
                app._apply_parsed_result(dict(species="索罗亚", ability="测试梦特名", gender="F",
                                              has_hidden_ability=diamond, is_alpha=alpha))
                self.assertEqual(app.hidden_ability_var.get(), expected)

    def test_four_iv_alpha_floor_keeps_second_egg_group_market_option(self):
        ivs = [31, None, 31, 31, 31, None]
        body = material("body", "索罗亚", "F", ivs, hidden=True)
        upper = material("upper", "双组测试素材", "M", [31, None, 31, None, 31, None],
                         groups=("水中1", "陆上"))
        candidate = self.plan([body, upper], "索罗亚克", ivs=ivs)
        self.assertEqual(candidate.nature_phase, "guarantee")
        self.assertEqual(candidate.root.purchases, 1)
        self.assertEqual(candidate.root.breeds, 2)
        self.assertTrue(candidate.root.has_hidden_ability)

    def test_four_iv_and_five_iv_ordinary_routes_use_relative_gamble_tiers(self):
        for level in (4, 5):
            with self.subTest(level=level):
                ivs = [31] * level + [None] * (6 - level)
                body = material("body", "索罗亚", "F", ivs, alpha=False, hidden=True)
                candidate = self.plan([body], "索罗亚克", alpha=False, ivs=ivs)
                self.assertEqual(candidate.nature_phase, "gamble_upper")
                self.assertEqual(candidate.root.mask.bit_count(), level - 1)
                self.assertFalse(candidate.root.is_alpha)

    def test_enabled_ditto_cannot_consume_parked_mother_during_hand_gamble(self):
        body = self.body()
        ditto = material("ditto", "百变怪", "N", [31, None, 31, 31, 31, None])
        report, candidates = make_report_with_candidates(
            [body, ditto], "尼多王", "M", "内敛", "31/x/31/31/31/31", [],
            target_alpha=True, need_hidden_ability=True, allow_ditto=True)
        self.assertTrue(candidates, report)
        for candidate in candidates:
            self.assertEqual(candidate.nature_phase, "gamble_upper")
            self.assertEqual(candidate.root.mask.bit_count(), 4)
            self.assertNotIn(body.id, candidate.root.used_ids)
            self.assertEqual(candidate.retained_body_id, body.id)

    def test_full_miss_sequence_persists_parents_and_undo_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            body = self.body()
            save_inventory([body])
            for expected_phase in ("gamble_upper", "gamble_lower", "guarantee"):
                candidate = self.plan(load_inventory())
                self.assertEqual(candidate.nature_phase, expected_phase)
                execution = build_execution_plan(candidate)
                snapshot = {**execution.to_dict(), "_candidate_snapshot": candidate.to_dict()}
                for step in execution.steps:
                    step.child.nature = "内敛" if expected_phase == "guarantee" else "温顺"
                    if step.child.breeding_role:
                        step.child.nature_attempt_result = "hit" if expected_phase == "guarantee" else "miss"
                    consume_parents_and_add_child(
                        (step.parent_a_id, step.parent_b_id), step.child,
                        plan_id=execution.id, step_number=step.number, plan_snapshot=snapshot,
                        add_child_to_inventory=not (expected_phase == "guarantee" and step is execution.steps[-1]),
                    )
                if expected_phase != "guarantee":
                    self.assertIn(body.id, {item.id for item in load_inventory()})
                else:
                    self.assertTrue(candidate.root.has_hidden_ability)
                    self.assertTrue(candidate.root.is_alpha)
                    self.assertEqual(execution.steps[-1].child.species, "尼多朗")
                    self.assertEqual(execution.steps[-1].child.gender, "M")
                    self.assertNotIn(execution.steps[-1].child.id, {item.id for item in load_inventory()})
                result = undo_last_consumption()
                self.assertIsNotNone(result)
                self.assertEqual(result[3], snapshot)
                self.assertEqual(ChainCandidate.from_dict(result[3]["_candidate_snapshot"]).to_dict(), candidate.to_dict())
                last = execution.steps[-1]
                consume_parents_and_add_child((last.parent_a_id, last.parent_b_id), last.child,
                                             plan_id=execution.id, step_number=last.number,
                                             add_child_to_inventory=expected_phase != "guarantee")


if __name__ == "__main__":
    unittest.main()
