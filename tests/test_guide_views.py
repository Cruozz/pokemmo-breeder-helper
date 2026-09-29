from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from guide_data import get_guide_database
from guide_views import PAGE_TITLES, QueryPage


class GuideViewTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.database = get_guide_database()

    def tearDown(self):
        self.root.destroy()

    def test_native_pages_filter_reset_and_empty_results(self):
        for mode in PAGE_TITLES:
            with self.subTest(mode=mode):
                page = QueryPage(self.root, self.database, mode, lambda *_args: None)
                page.pack(fill="both", expand=True)
                self.root.update()
                self.assertTrue(page.table.rows)
                page.query.set("确定不存在的查询")
                page.refresh()
                self.assertEqual(page.table.rows, [])
                self.assertIn("放宽", page.table.count.get())
                self.assertEqual(str(page.jump["state"]), "disabled")
                page.reset()
                self.root.update()
                self.assertTrue(page.table.rows)
                page.destroy()

    def test_pokedex_details_and_related_navigation(self):
        navigations = []
        page = QueryPage(self.root, self.database, "pokedex", lambda *args: navigations.append(args))
        page.query.set("025")
        page.refresh()
        self.root.update()
        self.assertEqual(len(page.table.rows), 1)
        self.assertIn("皮卡丘", page.detail_title.get())
        self.assertIn("隐藏特性", page.details["base"].get("1.0", "end"))
        page.jump_to_related()
        self.assertEqual(navigations, [("hordes", 25)])

    def test_pokedex_shows_all_species_without_pagination_and_sorts_numerically(self):
        page = QueryPage(self.root, self.database, "pokedex", lambda *_args: None)
        page.table.change_page(1)
        self.assertEqual(page.table.page, 0)
        self.assertEqual(len(page.table.tree.get_children()), 649)
        self.assertEqual(page.table.next_button.winfo_manager(), "")
        self.assertEqual(page.table.previous_button.winfo_manager(), "")
        page.table.sort("total")
        totals = [values[3] for _record, values in page.table.rows]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(page.table.page, 0)
        self.assertEqual(len(page.table.tree.get_children()), 649)
        page.query.set("皮卡丘")
        page.refresh()
        self.assertEqual(len(page.table.tree.get_children()), 1)
        page.reset()
        self.assertEqual(len(page.table.tree.get_children()), 649)

    def test_hordes_have_one_row_per_species_and_all_matching_locations(self):
        navigations = []
        page = QueryPage(self.root, self.database, "hordes", lambda *args: navigations.append(args))
        records = [record for record, _values in page.table.rows]
        self.assertEqual(len(records), len({row.species_id for row in self.database.hordes}))
        multiple = next(record for record in records if len({row.region for row in record.encounters}) > 1)
        page.show_details(multiple)
        content = page.details["base"].get("1.0", "end")
        for region, location in {(row.region, row.location) for row in multiple.encounters}:
            self.assertEqual(content.count(f"{region} · {location}\n"), 1)
        page.jump_to_related()
        self.assertEqual(navigations, [("pokedex", multiple.species_id)])
        page.variables["region"].set("合众")
        page.variables["season"].set("冬")
        page.variables["quantity"].set("5只")
        page.refresh()
        self.assertTrue(page.table.rows)
        for record, _values in page.table.rows:
            self.assertTrue(all(row.region == "合众" and row.season in {"冬", "任意"} and row.quantity == 5
                                for row in record.encounters))

    def test_effort_filters_keep_the_selected_stat(self):
        page = QueryPage(self.root, self.database, "effort", lambda *_args: None)
        page.variables["stat"].set("速度")
        page.variables["season"].set("冬")
        page.variables["quantity"].set("5只")
        page.refresh()
        self.root.update()
        self.assertTrue(page.table.rows)
        self.assertTrue(all(record.season in {"冬", "任意"} and record.quantity == 5 for record, _values in page.table.rows))
        self.assertIn("速度", page.details["base"].get("1.0", "end"))

    def test_workspace_roundtrip_preserves_inventory_and_filters(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            app = App(self.root)
            before = list(app.inventory)
            app._select_workspace_mode("hordes")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                self.root.update()
                if app.guide_workspace is not None and app.guide_workspace.pages:
                    break
                time.sleep(0.02)
            self.assertIn("hordes", app.guide_workspace.pages)
            page = app.guide_workspace.pages["hordes"]
            page.variables["season"].set("冬")
            for mode in ("effort", "pokedex", "planner", "author", "scan", "hordes"):
                app._select_workspace_mode(mode)
                self.root.update()
                expected = PAGE_TITLES.get(mode, {"planner": "孵蛋规划", "author": "作者的话", "scan": "扫描素材"}.get(mode))
                self.assertEqual(app.workspace_mode_var.get(), expected)
                if mode in PAGE_TITLES:
                    self.assertEqual(app.main_pane.winfo_manager(), "")
                    self.assertEqual(app.guide_workspace.winfo_manager(), "pack")
                else:
                    self.assertEqual(app.main_pane.winfo_manager(), "pack")
            self.assertEqual(page.variables["season"].get(), "冬")
            self.assertEqual(app.inventory, before)
            self.assertFalse((Path(directory) / "PokeMMO-Breeder-Helper" / "active_plan.json").exists())

    def test_navigation_fits_minimum_window(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            app = App(self.root)
            self.root.geometry("700x600")
            self.root.deiconify()
            self.root.update()
            buttons = [app.scan_mode_button, app.planner_mode_button, *app.guide_buttons.values(), app.author_mode_button]
            for button in buttons:
                self.assertGreater(button.winfo_width(), 40)
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())

    def test_pending_refresh_is_cancelled_on_destroy(self):
        page = QueryPage(self.root, self.database, "hordes", lambda *_args: None)
        page.query.set("皮卡丘")
        pending = page.pending
        self.assertIn(pending, self.root.tk.call("after", "info"))
        page.destroy()
        self.assertNotIn(pending, self.root.tk.call("after", "info"))

    def test_marked_explanations_are_not_visible(self):
        blocked = ("本地资料", "第三方资料快照", "资料来源：", "点击图片切换", "也可按空格", "整群基础值 =")
        for mode in PAGE_TITLES:
            page = QueryPage(self.root, self.database, mode, lambda *_args: None)
            page.pack(fill="both", expand=True)
            self.root.update()
            pending = [page]
            while pending:
                widget = pending.pop()
                pending.extend(widget.winfo_children())
                if widget.winfo_manager() and "text" in widget.keys():
                    self.assertFalse(any(text in str(widget.cget("text")) for text in blocked))
            if mode == "pokedex":
                self.assertEqual(page.portrait.caption_label.winfo_manager(), "")
                page.portrait.button.invoke()
                self.assertTrue(page.portrait.shiny)
            page.destroy()


if __name__ == "__main__":
    unittest.main()
