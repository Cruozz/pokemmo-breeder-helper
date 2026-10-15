import os
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import App, UI_COLORS
from execution import ExecutionPlan
from execution_view import execution_map
from mind_map import MindMapNode
from route_view import BreedingRouteView, text_steps, held_item, GENDER_FILLS
from species_data import get_species_database
from test_route_colors import color_fixture


class TextRouteTests(unittest.TestCase):
    def test_stages_follow_dependencies_not_step_number_and_ignore_context(self):
        first = MindMapNode("one", "one", step_number=9)
        second = MindMapNode("two", "two", step_number=1, children=[first])
        parallel = MindMapNode("parallel", "parallel", step_number=7)
        final = MindMapNode("final", "final", step_number=10, children=[second, parallel])
        context = MindMapNode("annotation", "not an operation", children=[final])
        self.assertEqual([(step.stage, step.node.step_number) for step in text_steps(context)],
                         [(1, 7), (1, 9), (2, 1), (3, 10)])

    def test_real_plan_roundtrip_keeps_parents_items_names_and_complete_history(self):
        _, plan, inventory = color_fixture()
        plan.steps[0].completed = True
        plan = ExecutionPlan.from_dict(plan.to_dict())
        root = execution_map(plan, inventory, {(plan.id, step.number) for step in plan.steps}, get_species_database())
        entries = text_steps(root)
        self.assertEqual(len(entries), len(plan.steps))
        by_number = {entry.node.step_number: entry for entry in entries}
        for step in plan.steps:
            node = by_number[step.number].node
            self.assertEqual(node.species_name, step.child.species)
            self.assertEqual([held_item(parent) for parent in node.children], [step.item_a or "无需道具", step.item_b or "无需道具"])
            for parent in node.children:
                if parent.step_number is not None:
                    self.assertLess(by_number[parent.step_number].stage, by_number[step.number].stage)
        self.assertTrue(by_number[plan.steps[0].number].node.completed)


class TextRouteUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.root.geometry("620x620")

    def tearDown(self):
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()

    def view(self, on_select=None):
        result = BreedingRouteView(self.root, colors=UI_COLORS, font_family="Microsoft YaHei",
                                   on_step_activate=Mock(), on_step_select=on_select)
        result.pack(fill="both", expand=True)
        return result

    def test_switch_scroll_render_gender_and_step_selection_without_plan_mutation(self):
        _, plan, inventory = color_fixture()
        route = execution_map(plan, inventory, set(), get_species_database())
        before = plan.to_dict()
        selection = Mock()
        view = self.view(selection)
        view.set_root(route)
        self.root.update()
        view.map.set_zoom(0.8)
        self.root.update()
        view.map.canvas.xview_moveto(0.3)
        view.map.canvas.yview_moveto(0.25)
        previous_view = view.map.canvas.xview(), view.map.canvas.yview()
        view.set_mode("text")
        self.root.update()
        canvas = view.text.canvas
        self.assertTrue(canvas.find_withtag("text-sprite"))
        fills = {canvas.itemcget(item, "fill") for item in canvas.find_withtag("text-monster")}
        self.assertTrue(set(GENDER_FILLS.values()) <= fills)
        labels = [canvas.itemcget(item, "text") for item in canvas.find_all() if canvas.type(item) == "text"]
        self.assertIn("不变之石", [held_item(parent) for step in view.text.steps for parent in step.node.children])
        self.assertFalse(any("性格：" in text or "成本" in text or "未定位" in text for text in labels))
        self.assertTrue(canvas.find_withtag("text-iv"))
        self.assertEqual(float(canvas.cget("scrollregion").split()[2]), canvas.winfo_width() - 2)
        first = next(entry for entry in view.text._layouts if entry[2] == "step")
        view.text._click(SimpleNamespace(x=30, y=first[0] + 15 - canvas.canvasy(0)))
        selection.assert_called_once_with(first[3].step_number)
        view.text._yview("moveto", 1)
        self.root.update()
        self.assertGreater(canvas.yview()[0], 0)
        self.assertTrue(any(canvas.itemcget(item, "text") == f"步骤 {plan.steps[-1].number}"
                            for item in canvas.find_all() if canvas.type(item) == "text"))
        end_scroll = canvas.yview()
        view.set_mode("map")
        self.root.update()
        self.assertEqual(view.map.zoom, 0.8)
        self.assertEqual((view.map.canvas.xview(), view.map.canvas.yview()), previous_view)
        view.set_mode("text")
        self.root.update()
        self.assertEqual(canvas.yview(), end_scroll)
        self.assertEqual(plan.to_dict(), before)

    def test_small_width_single_result_and_clear_never_show_previous_plan(self):
        view = self.view()
        self.root.geometry("380x440")
        view.set_mode("text")
        view.set_root(MindMapNode("leaf", "commentary", species_name="玛狃拉", species_id=461, gender="F",
                                 iv_values=("31", "31", "31", "0", "31", "31")))
        self.root.update()
        canvas = view.text.canvas
        self.assertTrue(canvas.find_withtag("text-sprite"))
        self.assertIn("玛狃拉 ♀", [canvas.itemcget(item, "text") for item in canvas.find_withtag("text-species")])
        bounds = canvas.bbox("all")
        self.assertGreaterEqual(bounds[0], 0)
        self.assertLessEqual(bounds[2], canvas.winfo_width())
        view.set_root(None, "没有路线")
        self.root.update()
        self.assertFalse(canvas.find_withtag("text-monster"))
        self.assertEqual(canvas.itemcget(canvas.find_all()[0], "text"), "没有路线")
        view.set_mode("map")
        self.assertEqual(view.map.node_count, 0)

    def test_app_shares_full_history_and_preview_is_read_only_in_both_windows(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"LOCALAPPDATA": folder}):
            app = App(self.root)
            _, plan, inventory = color_fixture()
            app.inventory = inventory
            app.active_plan = plan
            app.proposed_plan = plan
            plan.steps[0].completed = True
            app.plan_view_mode = "active"
            app._render_plan_tree(None)
            app.plan_map.set_mode("text")
            self.root.update()
            self.assertEqual(len(app.plan_map.text.steps), len(plan.steps))
            app.open_detached_plan_map()
            self.root.update()
            self.assertEqual(app.detached_plan_map.mode.get(), "text")
            self.assertEqual(len(app.detached_plan_map.text.steps), len(plan.steps))
            self.assertTrue(app._can_execute_displayed_plan())
            app.plan_view_mode = "proposal"
            app._render_plan_tree(color_fixture()[0])
            self.root.update()
            self.assertFalse(app._can_execute_displayed_plan())
            self.assertFalse(any(entry.node.actionable for entry in app.plan_map.text.steps))
            app.plan_map_window.destroy()


if __name__ == "__main__":
    unittest.main()
