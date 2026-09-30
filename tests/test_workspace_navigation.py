import os
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import App
from models import Monster


class WorkspaceNavigationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": self.directory.name})
        self.environment.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)
        self.root.geometry("700x600")
        self.root.deiconify()
        self.root.update()

    def tearDown(self):
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.environment.stop()
        self.directory.cleanup()

    def test_three_entries_show_separate_pages_in_narrow_and_wide_windows(self):
        app = self.app
        buttons = [app.scan_mode_button, app.inventory_mode_button, app.planner_mode_button]
        self.assertEqual([button.cget("text") for button in app.workspace_nav_items[1:4]],
                         ["扫描素材", "素材库存", "孵蛋规划"])
        pages = [app.current_tab, app.inventory_tab, app.planner_tab]
        self.assertFalse(any(child.winfo_class() == "TNotebook" for child in app.right_panel.winfo_children()))
        for geometry in ("700x600", "1200x800"):
            self.root.geometry(geometry)
            self.root.update()
            for index, button in enumerate(buttons):
                with self.subTest(geometry=geometry, page=button.cget("text")):
                    button.invoke()
                    self.root.update()
                    self.assertEqual(app.workspace_mode_var.get(), button.cget("text"))
                    for page_index, page in enumerate(pages):
                        self.assertEqual(bool(page.winfo_ismapped()), page_index == index)
                        self.assertEqual(buttons[page_index].cget("style"),
                                         "Primary.TButton" if page_index == index else "TButton")
                    self.assertEqual(bool(app.scan_controls_panel.winfo_ismapped()), index == 0)
                    self.assertEqual(bool(app.scan_status_frame.winfo_ismapped()), index == 0)
                    if index:
                        self.assertEqual(tuple(map(str, app.main_pane.panes())), (str(app.right_panel),))
                        self.assertGreater(app.right_panel.winfo_width(), self.root.winfo_width() - 40)
                    for nav_button in buttons:
                        right = nav_button.winfo_rootx() + nav_button.winfo_width()
                        self.assertLessEqual(right, self.root.winfo_rootx() + self.root.winfo_width())

    def test_roundtrip_preserves_scan_inventory_and_planner_state(self):
        app = self.app
        app.species_var.set("暴鲤龙")
        app.iv_var.set("x/x/31/x/31/31")
        app.inventory_filter_var.set("暴鲤龙")
        app.target_species_var.set("暴鲤龙")
        app.target_nature_var.set("固执")
        app.target_alpha_var.set("头目")
        for mode in ("planner", "author", "inventory", "scan", "inventory", "planner"):
            app._select_workspace_mode(mode)
            self.root.update()
        self.assertEqual(app.species_var.get(), "暴鲤龙")
        self.assertEqual(app.iv_var.get(), "x/x/31/x/31/31")
        self.assertEqual(app.inventory_filter_var.get(), "暴鲤龙")
        self.assertEqual(app.target_species_var.get(), "暴鲤龙")
        self.assertEqual(app.target_nature_var.get(), "固执")
        self.assertEqual(app.target_alpha_var.get(), "头目")
        app._select_workspace_mode("scan")
        app._set_compact_scan_view("preview")
        self.root.update()
        self.assertEqual(tuple(map(str, app.main_pane.panes())), (str(app.left_panel),))
        app._set_compact_scan_view("result")
        self.root.update()
        self.assertTrue(app.current_tab.winfo_ismapped())

    def test_duplicate_location_and_inventory_edit_use_the_correct_workspace(self):
        app = self.app
        monster = Monster(id="test-alpha", species="暴鲤龙", gender="F", nature="固执",
                          ivs=[None, None, 31, None, 31, 31], is_alpha=True)
        app.inventory = [monster]
        app.refresh_inventory_tree()
        app._select_workspace_mode("author")
        tree = SimpleNamespace(selection=lambda: ("pair",))
        app._focus_duplicate_record(tree, {"pair": (monster.id, "other")}, 0, None)
        self.root.update()
        self.assertEqual(app.workspace_mode_var.get(), "素材库存")
        self.assertTrue(app.inventory_tab.winfo_ismapped())
        self.assertEqual(app.inventory_tree.selection(), (monster.id,))
        app.edit_inventory_selected()
        self.root.update()
        self.assertEqual(app.workspace_mode_var.get(), "扫描素材")
        self.assertTrue(app.current_tab.winfo_ismapped())
        self.assertEqual(app.editing_monster_id, monster.id)
        self.assertEqual(app.species_var.get(), monster.species)
        self.assertEqual(app.iv_var.get(), monster.iv_string)


if __name__ == "__main__":
    unittest.main()
