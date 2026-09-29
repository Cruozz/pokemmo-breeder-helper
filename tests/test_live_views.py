from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from app import App
from live_data import AlphaReport, CaveRotation, FeedError, load_cache
from live_views import LiveWorkspace


class LiveViewTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": self.directory.name})
        self.env.start()
        self.cache = Path(self.directory.name) / "live.json"
        now = time.time()
        self.alpha = AlphaReport("Salamence", 373, "Hoenn", "Sky Pillar", now - 60, now + 4400)
        date = datetime.now(timezone.utc)
        self.cave = CaveRotation(date.strftime("%Y%m%d") + "-" + str(date.hour // 6), "Bug",
                                 ("Venomoth", "Ferroseed", "Duosion", "Parasect", "Staryu"),
                                 ("Ninjask", "Larvesta"), ("Shellos", "Pinsir"))

    def tearDown(self):
        for child in list(self.root.children.values()):
            child.destroy()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.env.stop()
        self.directory.cleanup()

    def page(self, **kwargs):
        return LiveWorkspace(self.root, cache_path=self.cache, autostart=False, **kwargs)

    def test_success_failure_and_expiry_have_distinct_states(self):
        page = self.page()
        page._apply_result("alpha", self.alpha, None)
        page._apply_result("cave", self.cave, None)
        self.assertEqual(page.alpha_name.get(), "暴飞龙")
        self.assertEqual(page.cave_slots["singles"][0].name_label.cget("text"), "摩鲁蛾")
        self.assertEqual(page.gem_type.get(), "宝石属性：虫")
        self.assertIn("预计仍在出现", page.alpha_status.get())
        page._apply_result("alpha", None, FeedError("连接失败"))
        self.assertIn("待确认", page.alpha_status.get())
        self.assertEqual(page.feeds["alpha"].data, self.alpha)
        self.assertEqual(page.feeds["cave"].error, "")
        with patch("live_views.time.time", return_value=self.cave.expires_at + 1):
            page.update_status()
        self.assertIn("已结束", page.cave_status.get())

    def test_cache_is_marked_unverified_and_pause_frequency_persist(self):
        page = self.page()
        page._apply_result("alpha", self.alpha, None)
        page.auto_var.set(False)
        page.interval_var.set("3 分钟")
        page.settings_changed()
        page.destroy()
        restored = self.page()
        restored.update_status()
        self.assertFalse(restored.auto_var.get())
        self.assertEqual(restored.interval, 180)
        self.assertIn("缓存", restored.status_vars["alpha"].get())
        self.assertIn("待确认", restored.alpha_status.get())

    def test_refresh_is_single_flight_and_does_not_block_tk(self):
        gate = threading.Event()
        calls = []
        def fetch(kind):
            calls.append(kind)
            gate.wait(3)
            return self.alpha if kind == "alpha" else self.cave
        page = self.page(client=Mock(fetch=fetch))
        try:
            page.refresh(manual=True)
            page.refresh(manual=True)
            marker = []
            self.root.after(0, lambda: marker.append(True))
            self.root.update()
            self.assertEqual(marker, [True])
            self.assertTrue(page.in_flight)
            gate.set()
            deadline = time.monotonic() + 3
            while page.in_flight and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.02)
            self.assertFalse(page.in_flight)
            self.assertEqual(calls, ["alpha", "cave"])
            self.assertTrue(page.feeds["cave"].confirmed)
        finally:
            gate.set()

    def test_rate_limit_cannot_be_bypassed_by_manual_refresh(self):
        client = Mock()
        page = self.page(client=client)
        page._apply_result("alpha", None, FeedError("稍后重试", 600))
        page._apply_result("cave", None, FeedError("稍后重试", 600))
        page.refresh(manual=True)
        self.assertFalse(page.in_flight)
        client.fetch.assert_not_called()
        remaining = page.feeds["alpha"].retry_until - time.monotonic()
        page.settings_changed()
        self.assertGreater(page.feeds["alpha"].next_due - time.monotonic(), remaining - 1)

    def test_paused_timer_does_not_make_network_calls(self):
        client = Mock()
        page = self.page(client=client)
        page.network_enabled = True
        page.auto_var.set(False)
        page.after_cancel(page.poll_after)
        page._tick()
        client.fetch.assert_not_called()

    def test_navigation_and_cave_content_fit_minimum_window(self):
        with patch("app.LiveWorkspace", side_effect=lambda parent: LiveWorkspace(parent, cache_path=self.cache, autostart=False)):
            app = App(self.root)
            before = list(app.inventory)
            self.root.geometry("700x600")
            self.root.deiconify()
            app._select_workspace_mode("live")
            self.root.update()
            page = app.live_workspace
            page._apply_result("alpha", self.alpha, None)
            page._apply_result("cave", self.cave, None)
            page.tabs.select(page.cave_page)
            self.root.update()
            width, height = self.root.winfo_width(), self.root.winfo_height()
            stacking = app.workspace_label.master.winfo_children()
            highest_frame = max(stacking.index(frame) for frame in app.workspace_nav_rows)
            for button in app.workspace_nav_items:
                self.assertGreater(stacking.index(button), highest_frame,
                                   "Navigation must not be covered by its wrapping frame")
            for widget in [*app.workspace_nav_items, page.refresh_button, page.interval_combo,
                           *page.cave_slots["singles"], *page.cave_slots["hordes"]]:
                x = widget.winfo_rootx() - self.root.winfo_rootx()
                y = widget.winfo_rooty() - self.root.winfo_rooty()
                self.assertGreater(widget.winfo_width(), 30)
                self.assertLessEqual(x + widget.winfo_width(), width, str(widget))
                self.assertLessEqual(y + widget.winfo_height(), height, str(widget))
            for mode in ("planner", "author", "live", "scan"):
                app._select_workspace_mode(mode)
                self.root.update()
            self.assertEqual(app.inventory, before)
            self.assertFalse((Path(self.directory.name) / "PokeMMO-Breeder-Helper" / "active_plan.json").exists())
            self.assertEqual(page.winfo_manager(), "")

    def test_destroy_cancels_scheduled_callback(self):
        page = self.page()
        callback = page.poll_after
        page.destroy()
        self.assertNotIn(callback, self.root.tk.call("after", "info"))


if __name__ == "__main__":
    unittest.main()
