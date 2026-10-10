import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from parallel_guide import ParallelGuideWorkspace, guide_profile, verify_guide_assets


class ParallelGuideTests(unittest.TestCase):
    def test_completed_draft_and_all_bundled_resources_match_manifest(self):
        assets = verify_guide_assets()
        self.assertEqual((assets["phases"], assets["steps"]), (26, 132))
        self.assertEqual(assets["draft_sha256"], "5e795a9334ff4bddb6803f7b6eca9665dd129d1900077ea0ae0ec34020a07b6c")

    def test_ninth_workspace_fits_and_preserves_existing_state(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}), \
                patch("app.ParallelGuideWorkspace", side_effect=lambda parent: ParallelGuideWorkspace(parent, autostart=False)):
            root = tk.Tk()
            try:
                app = App(root)
                self.assertIsNone(app.parallel_workspace)
                app.target_species_var.set("耿鬼")
                app.inventory_filter_var.set("固执")
                before = list(app.inventory)
                expected = ["扫描素材", "素材库存", "孵蛋规划", "群怪分布", "精灵图鉴", "努力值",
                            "平行五通攻略", "实时情报", "作者的话"]
                self.assertEqual([button.cget("text") for button in app.workspace_nav_items[1:]], expected)
                for geometry in ("700x600", "1200x800"):
                    root.geometry(geometry)
                    root.update()
                    for mode in ("parallel", "effort", "parallel", "inventory", "planner", "author", "scan"):
                        app._select_workspace_mode(mode)
                        root.update()
                        self.assertEqual(bool(app.parallel_workspace.winfo_ismapped()), mode == "parallel")
                        self.assertEqual(app.parallel_mode_button.cget("style"), "Primary.TButton" if mode == "parallel" else "TButton")
                        for button in app.workspace_nav_items:
                            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), root.winfo_rootx() + root.winfo_width())
                self.assertIsNone(app.parallel_workspace.process)
                self.assertEqual(app.inventory, before)
                self.assertEqual(app.target_species_var.get(), "耿鬼")
                self.assertEqual(app.inventory_filter_var.get(), "固执")
                self.assertFalse((Path(directory) / "PokeMMO-Breeder-Helper" / "active_plan.json").exists())
                self.assertEqual(guide_profile(), Path(directory) / "PokeMMO-Breeder-Helper" / "parallel-guide" / "profile")
            finally:
                for callback in root.tk.call("after", "info"):
                    root.after_cancel(callback)
                root.destroy()

    def test_missing_host_reports_error_without_breaking_navigation(self):
        root = tk.Tk()
        try:
            page = ParallelGuideWorkspace(root, autostart=False)
            with tempfile.TemporaryDirectory() as directory, patch("parallel_guide.guide_runtime", return_value=Path(directory)):
                page.start()
                self.assertIsNone(page.process)
                self.assertIn("缺少攻略阅读组件", page.message.cget("text"))
                self.assertEqual(page.retry_button.winfo_manager(), "pack")
        finally:
            root.destroy()
