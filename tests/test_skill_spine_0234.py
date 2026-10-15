import json
from dataclasses import replace
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from app import UI_COLORS
from breeding_cost import ACTIVE_BOOK, PriceBook
from chain_planner import ChainCandidate, _virtual_materials, _egg_move_seed_states, _forced_child
from execution import ExecutionPlan, build_execution_plan
from execution_view import execution_map
from models import Monster
from planner import make_report_with_candidates
from reference_data import get_reference_database
from route_view import BreedingRouteView, text_steps
from species_data import get_species_database
from test_egg_moves import profile


MOVES = {"神通力", "临别礼物"}
TARGET = "31/x/31/31/31/31"


def material(key, species, gender, stats, moves=(), nature="认真"):
    return Monster(id=key, species=species, gender=gender, nature=nature,
                   ivs=[31 if index in stats else 1 for index in range(6)],
                   egg_groups=list(get_species_database().get(species).egg_groups),
                   moves=list(moves), is_alpha=True, has_hidden_ability=True, verified=True)


def stock():
    return [material("zorua", "索罗亚", "M", (2, 4)),
            material("ditto", "百变怪", "N", (0, 2)),
            material("vulpix", "六尾", "M", (0, 2, 3)),
            material("stunky", "臭鼬噗", "M", (0, 2, 3, 5), ("临别礼物",))]


def plan_for(inventory, **kwargs):
    report, candidates = make_report_with_candidates(
        inventory, "索罗亚", "", "胆小", TARGET, [],
        target_alpha=True, allow_ditto=False, convert_maternal_with_ditto=True,
        need_hidden_ability=True, target_moves=sorted(MOVES), nature_strategy="late",
        max_purchase_v=2, **kwargs,
    )
    if not candidates:
        raise AssertionError(report)
    return candidates[0]


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


class SkillSpineTests(unittest.TestCase):
    def assert_mechanically_replayable(self, plan):
        available = {key: Monster.from_dict(value) for key, value in plan.materials.items()}
        consumed = set()
        reference = get_reference_database()
        for step in plan.steps:
            self.assertFalse({step.parent_a_id, step.parent_b_id} & consumed)
            a, b = available[step.parent_a_id], available[step.parent_b_id]
            self.assertTrue(a.is_alpha and b.is_alpha and step.child.is_alpha)
            a_moves = set(a.moves) | {value["move"] for value in step.preparations if value["parent_id"] == a.id}
            b_moves = set(b.moves) | {value["move"] for value in step.preparations if value["parent_id"] == b.id}
            for move in step.child.moves:
                self.assertIn(move, a_moves | b_moves)
                if move not in reference.inheritable_moves(step.child.species):
                    self.assertTrue(reference.move_preparation_sources(move).get(step.child.species, "").startswith("升级至"))
                    self.assertTrue(move in a_moves and move in b_moves or
                                    a.species == "百变怪" and move in b_moves or b.species == "百变怪" and move in a_moves)
            for index, value in enumerate(step.child.ivs):
                if value == 31:
                    self.assertTrue(a.ivs[index] == b.ivs[index] == 31 or
                                    a.ivs[index] == 31 and step.item_a == ("HP", "攻击", "防御", "特攻", "特防", "速度")[index] + "护腕" or
                                    b.ivs[index] == 31 and step.item_b == ("HP", "攻击", "防御", "特攻", "特防", "速度")[index] + "护腕")
            consumed.update((step.parent_a_id, step.parent_b_id))
            available[step.child.id] = step.child

    def test_inventory_male_converts_then_grows_and_imports_both_moves_without_zorua_purchase(self):
        inventory = stock()
        before = [monster.to_dict() for monster in inventory]
        candidate = plan_for(inventory)
        self.assertEqual((candidate.root.purchases, candidate.root.breeds), (0, 3))
        self.assertTrue(candidate.root.maternal_conversion)
        plan = build_execution_plan(candidate)
        self.assertEqual([sum(value == 31 for value in step.child.ivs) for step in plan.steps], [3, 4, 5])
        self.assertEqual([step.child.species for step in plan.steps], ["索罗亚"] * 3)
        self.assertEqual(set(plan.steps[1].child.moves), {"神通力"})
        self.assertEqual(set(plan.steps[2].child.moves), MOVES)
        self.assertEqual(plan.steps[1].preparations[0]["species"], "六尾")
        self.assertEqual([monster.to_dict() for monster in inventory], before)
        self.assert_mechanically_replayable(plan)
        self.assertEqual(plan.nature_check_min_ivs, 5)
        self.assertEqual([plan.should_check_nature(step) for step in plan.steps], [False, False, True])

    def test_purchase_ceiling_two_builds_foreign_skill_sires_and_never_buys_another_zorua(self):
        candidate = plan_for(stock()[:2])
        self.assertTrue(candidate.root.maternal_conversion)
        purchases = [node for node in self.walk_states(candidate.root) if node.is_virtual]
        self.assertTrue(purchases)
        self.assertTrue(all(node.leaf.species != "索罗亚" and node.effective_material_v == 2 for node in purchases))
        self.assertEqual(set(candidate.root.inherited_moves), MOVES)
        plan = build_execution_plan(candidate)
        self.assert_mechanically_replayable(plan)

    @staticmethod
    def walk_states(state):
        yield state
        if state.action:
            yield from SkillSpineTests.walk_states(state.action.parent_a)
            yield from SkillSpineTests.walk_states(state.action.parent_b)

    def test_snapshot_execution_and_both_presentations_keep_learning_instructions(self):
        candidate = ChainCandidate.from_dict(json.loads(json.dumps(plan_for(stock()).to_dict())))
        plan = ExecutionPlan.from_dict(json.loads(json.dumps(build_execution_plan(candidate).to_dict())))
        self.assertEqual(plan.maternal_nature_min_ivs, 5)
        self.assertEqual(plan.steps[1].preparations[0]["move"], "神通力")
        root = execution_map(plan, stock(), set(), get_species_database())
        vulpix = next(node for node in walk(root) if node.species_name == "六尾")
        self.assertIn("神通力", " ".join(vulpix.preparation_text))
        self.assertIn("配种前", vulpix.detail)
        self.assertIn("神通力", vulpix.route_moves)
        self.assertEqual(len(text_steps(root)), len(plan.steps))
        self.assertTrue(any("配种前准备 六尾" in source for source in candidate.egg_move_sources()))

    def test_preparation_is_a_separate_manual_quote_and_is_counted_once(self):
        candidate = plan_for(stock())
        book = PriceBook({"include_inventory_value": False, "gender_overrides": {"570:F": 25000}})
        report = book.report(candidate.root, "F", "smart")
        preparations = [line for line in report.lines if line.kind == "技能准备"]
        self.assertEqual(len(preparations), 1)
        self.assertIsNone(preparations[0].unit_price)
        key = preparations[0].key
        self.assertTrue(key.startswith("prepare:"))
        self.assertIsNone(book.reference(book.materials[key]))
        previous = report.total_known
        book.prices[key] = 2300
        report = book.report(candidate.root, "F", "smart")
        self.assertEqual(report.total_known - previous, 2300)
        self.assertEqual(next(line.quantity for line in report.lines if line.key == key), 1)
        restored = PriceBook(book.to_dict())
        self.assertEqual(restored.report(candidate.root, "F", "smart").total_known, report.total_known)

    def test_existing_dual_skill_body_finishes_with_foreign_nature_sire_without_skill_requirements(self):
        inventory = [material("body", "索罗亚", "F", (0, 2, 3, 4, 5), MOVES),
                     material("hand", "长毛狗", "M", (0, 2, 3, 4), nature="胆小")]
        candidate = plan_for(inventory)
        self.assertEqual((candidate.root.breeds, candidate.root.purchases), (1, 0))
        self.assertTrue(candidate.root.has_nature)
        self.assertEqual(candidate.root.nature, "胆小")
        plan = build_execution_plan(candidate)
        self.assertEqual(set(plan.steps[0].child.moves), MOVES)
        self.assertIn("不变之石", (plan.steps[0].item_a, plan.steps[0].item_b))
        self.assertFalse(plan.steps[0].preparations)
        self.assert_mechanically_replayable(plan)

    def test_same_line_prepared_market_bundle_requires_explicit_quote_when_anchor_exists(self):
        from test_egg_moves import state
        anchor = state("anchor", "索罗亚", "F")
        book = PriceBook()
        token = ACTIVE_BOOK.set(book)
        try:
            args = (profile("索罗亚"), [31, None, None, None, None, None], False, "", False)
            leaves = _virtual_materials(*args, existing_leaves=[anchor], target_moves=frozenset(MOVES))
            self.assertFalse(any("egg-move-prepared-" in leaf.leaf.id for leaf in leaves))
            row = next(row for row in book.materials.values() if row["conditions"].get("species") == "索罗亚"
                       and set(row["conditions"].get("moves", ())) == MOVES and row["conditions"]["gender"] == "M")
            book.prices[row["key"]] = 20000
            leaves = _virtual_materials(*args, existing_leaves=[anchor], target_moves=frozenset(MOVES))
            self.assertTrue(any("egg-move-prepared-" in leaf.leaf.id and leaf.gender == "M" for leaf in leaves))
        finally:
            ACTIVE_BOOK.reset(token)

    def test_declining_completion_mentions_preparations_and_does_not_consume_inventory(self):
        plan = build_execution_plan(plan_for(stock()))
        plan.steps[0].completed = True
        instance = App.__new__(App)
        instance.active_plan = plan
        instance.plan_view_mode = "active"
        instance.displayed_plan_id = plan.id
        instance.plan_worker_busy = False
        instance.plan_candidate_cache = {}
        before = plan.to_dict()
        with patch("app.messagebox.askyesno", return_value=False) as confirm:
            instance.complete_next_step(plan.steps[1])
        self.assertIn("技能准备", confirm.call_args.args[1])
        self.assertIn("神通力", confirm.call_args.args[1])
        self.assertEqual(plan.to_dict(), before)

    def test_reference_does_not_turn_egg_chain_or_unknown_species_into_native_learning(self):
        reference = get_reference_database()
        self.assertIn("六尾", reference.move_preparation_sources("神通力"))
        self.assertIn("臭鼬噗", reference.move_preparation_sources("临别礼物"))
        self.assertNotIn("索罗亚", reference.move_preparation_sources("临别礼物"))
        self.assertNotIn("信使鸟", reference.move_preparation_sources("临别礼物"))

    def test_native_level_up_move_requires_both_parents_or_non_ditto_source(self):
        from test_egg_moves import state
        mother = state("v-f", "六尾", "F", ["神通力"])
        father = state("v-m", "六尾", "M", ["神通力"])
        child = _forced_child(mother, father, profile("六尾"), "M")
        self.assertIn("神通力", child.inherited_moves)
        father = state("other", "伊布", "M")
        child = _forced_child(mother, father, profile("六尾"), "M")
        self.assertNotIn("神通力", child.inherited_moves)
        ditto = state("d", "百变怪", "N")
        child = _forced_child(mother, ditto, profile("六尾"), "F")
        self.assertIn("神通力", child.inherited_moves)

    def test_skill_only_import_cannot_replace_an_established_maternal_iv(self):
        from test_egg_moves import state
        mother = replace(state("mother", "索罗亚", "F"), mask=21, material_v=3)
        father = replace(state("father", "臭鼬噗", "M", ["临别礼物"]), mask=33, material_v=2)
        seeds = _egg_move_seed_states([mother, father], frozenset({"临别礼物"}))
        self.assertFalse(any(seed.species == "索罗亚" for seed in seeds))
        father = replace(father, mask=5)
        seeds = _egg_move_seed_states([mother, father], frozenset({"临别礼物"}))
        self.assertTrue(any(seed.species == "索罗亚" and seed.mask == mother.mask for seed in seeds))

    def test_six_iv_mother_can_import_moves_across_two_foreign_upgrade_sires(self):
        inventory = [material("body4", "索罗亚", "F", (0, 1, 2, 3)),
                     material("memento4", "臭鼬噗", "M", (1, 2, 3, 4), ("临别礼物",)),
                     material("extra5", "六尾", "M", (1, 2, 3, 4, 5))]
        report, candidates = make_report_with_candidates(
            inventory, "索罗亚", "F", "", "31/31/31/31/31/31", [], target_alpha=True,
            allow_ditto=False, target_moves=sorted(MOVES), max_purchase_v=2,
        )
        self.assertTrue(candidates, report)
        self.assertEqual((candidates[0].root.purchases, candidates[0].root.breeds), (0, 2))
        self.assertEqual(set(candidates[0].root.inherited_moves), MOVES)
        self.assert_mechanically_replayable(build_execution_plan(candidates[0]))

    def test_inventory_strategy_uses_prices_to_choose_between_equally_sized_skill_purchases(self):
        inventory = [material("body2", "索罗亚", "F", (0, 2))]
        book = PriceBook({"include_inventory_value": False, "gender_overrides": {"570:F": 25000}})
        args = (inventory, "索罗亚", "F", "", "31/x/31/31/x/x", [])
        options = dict(target_alpha=True, allow_ditto=False, target_moves=["临别礼物"], max_purchase_v=2,
                       cost_pricing=book, strategy="inventory")
        make_report_with_candidates(*args, **options)
        for row in list(book.materials.values()):
            c = row["conditions"]
            if c.get("gender") == "M" and c.get("ivs") == [None, None, 31, 31, None, None] and c.get("moves") == ["临别礼物"]:
                if c.get("species") in {"臭鼬噗", "信使鸟"}:
                    book.prices[row["key"]] = 5000 if c["species"] == "臭鼬噗" else 350000
        report, candidates = make_report_with_candidates(*args, **options)
        self.assertTrue(candidates, report)
        self.assertEqual((candidates[0].root.purchases, candidates[0].root.breeds), (1, 1))
        purchases = [state.leaf.species for state in self.walk_states(candidates[0].root) if state.is_virtual]
        self.assertEqual(purchases, ["臭鼬噗"])


class SkillSpineUITests(unittest.TestCase):
    def test_learning_instructions_wrap_in_text_mode_and_can_be_priced(self):
        candidate = plan_for(stock())
        plan = build_execution_plan(candidate)
        root = tk.Tk()
        root.attributes("-alpha", 0)
        try:
            root.geometry("380x620")
            view = BreedingRouteView(root, colors=UI_COLORS, font_family="Microsoft YaHei", on_step_activate=lambda _: None)
            view.pack(fill="both", expand=True)
            view.set_root(execution_map(plan, stock(), set(), get_species_database()))
            view.set_mode("text")
            root.update()
            second = next(item for item in view.text._layouts if item[2] == "step" and item[3].step_number == 2)
            view.text.canvas.yview_moveto(second[0] / view.text._height)
            root.update()
            labels = [view.text.canvas.itemcget(item, "text") for item in view.text.canvas.find_withtag("text-skill")]
            self.assertTrue(any("配种前须准备" in label and "神通力" in label for label in labels))
            bounds = view.text.canvas.bbox("all")
            self.assertGreaterEqual(bounds[0], 0)
            self.assertLessEqual(bounds[2], view.text.canvas.winfo_width())
            from cost_views import CostDialog
            with tempfile.TemporaryDirectory() as directory:
                book = PriceBook({"include_inventory_value": False})
                report = book.report(candidate.root, "F", "smart")
                key = next(line.key for line in report.lines if line.kind == "技能准备")
                dialog = CostDialog(root, book=book, path=Path(directory) / "prices.json", inventory=[], candidates=[candidate])
                root.update()
                dialog.material_tree.selection_set(key)
                dialog.price_var.set("0")
                dialog.set_material_price()
                self.assertEqual(dialog.book.prices[key], 0)
                dialog.save()
                from breeding_cost import load_price_book
                self.assertEqual(load_price_book(Path(directory) / "prices.json").prices[key], 0)
                dialog.close()
        finally:
            for callback in root.tk.call("after", "info"):
                root.after_cancel(callback)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
